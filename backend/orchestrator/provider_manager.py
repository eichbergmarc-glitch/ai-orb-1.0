"""AI Provider Manager – Auswahl und Umschaltung des Sprachmodells.

Beim Start wird geprüft, ob der primäre Provider (Hermes) erreichbar ist.
Ist er es nicht, wird automatisch auf den Fallback (Ollama) gewechselt.
Zur Laufzeit läuft eine periodische Gesundheitsprüfung; wird der primäre
Provider wieder verfügbar, wird je nach Konfiguration sofort oder erst
nach Ende der laufenden Unterhaltung zurückgewechselt.

Beim Wechsel geht kein Kontext verloren: Der Gesprächsverlauf wird vom
Conversation Manager verwaltet und ist providerunabhängig.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.orchestrator.provider_health import ProviderHealth, internet_reachable
from backend.orchestrator.providers import PROVIDER_TYPES
from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.system.logging_setup import get_logger
from backend.system.performance_trace import mark_stage
from backend.utils.store import JsonStore

logger = get_logger(__name__)


class ProviderManager:
    """Verwaltet alle konfigurierten KI-Provider und deren Auswahl."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        mode_store: JsonStore | None = None,
    ) -> None:
        config = get_config()
        self._ai_config = config.section("ai")
        self._event_bus = event_bus

        self._providers: dict[str, BaseProvider] = {}
        self._primary_name: str | None = None
        self._fallback_name: str | None = None
        self._active_name: str | None = None

        self._auto_switch = bool(self._ai_config.get("auto_switch", True))
        self._switch_immediately = bool(self._ai_config.get("switch_immediately", False))
        self._pending_switch: str | None = None
        self._conversation_active = False
        local_routing = self._ai_config.get("local_routing") or {}
        self._local_routing_config = (
            dict(local_routing) if isinstance(local_routing, dict) else {}
        )
        # Auf der CPU duerfen LFM und das kleine Nebenmodell nie gleichzeitig
        # rechnen. Cloud-Anfragen bleiben parallel moeglich; nur lokale
        # Inferenz wird serialisiert. Das verhindert, dass zwei Ollama-
        # Runner einander Kerne und Speicherbandbreite wegnehmen.
        self._local_inference_lock = asyncio.Lock()
        # Quotenfehler werden fuer eine kurze Zeit gemerkt. Andernfalls
        # wuerde jeder parallel gestartete Subagent erneut denselben bereits
        # limitierten Anbieter anfragen und erst danach ausweichen.
        self._quota_cooldowns: dict[str, float] = {}

        # Der vom Benutzer gewaehlte Betriebsmodus ist Laufzeitstatus und
        # gehoert deshalb nicht in die statische config.yaml. Er bleibt in
        # einer kleinen lokalen Datei ueber Neustarts hinweg erhalten.
        configured_mode = str(config.get("routing.mode", "auto")).strip().lower()
        if configured_mode not in {"auto", "offline"}:
            configured_mode = "auto"
        self._mode_store = mode_store or JsonStore(
            "provider_mode.json", {"mode": configured_mode}
        )
        stored_mode = str(self._mode_store.get("mode", configured_mode)).strip().lower()
        self._operating_mode = stored_mode if stored_mode in {"auto", "offline"} else configured_mode
        self._ollama_services: dict[str, Any] = {}

        connectivity_hosts = (
            self._ai_config.get("connectivity_check_hosts")
            or config.get("routing.connectivity_check_hosts", ())
            or ()
        )
        connectivity_timeout = float(
            self._ai_config.get(
                "connectivity_check_timeout",
                config.get("routing.connectivity_check_timeout", 1.5),
            )
        )

        async def _connectivity_check() -> bool:
            kwargs: dict[str, Any] = {"timeout_seconds": connectivity_timeout}
            if connectivity_hosts:
                kwargs["hosts"] = tuple(str(host) for host in connectivity_hosts)
            return await internet_reachable(**kwargs)

        self._connectivity_check = _connectivity_check
        self._connectivity_cache_seconds = max(
            0.0,
            float(
                self._ai_config.get(
                    "connectivity_cache_seconds",
                    config.get("routing.connectivity_cache_seconds", 5.0),
                )
            ),
        )
        self._last_connectivity_check = 0.0
        self._last_connectivity_result: bool | None = None
        self._connectivity_lock = asyncio.Lock()

        self._health = ProviderHealth(
            interval_seconds=float(self._ai_config.get("health_check_interval", 60)),
            connectivity_check=_connectivity_check,
        )
        # Der Uebergabestand der Kategorien. Faellt er aus, bleibt alles
        # bei Claude - das ist der sichere Ausgang.
        try:
            from backend.lernen.uebergabe import Uebergabe

            self._uebergabe: Any | None = Uebergabe()
        except Exception:  # noqa: BLE001
            logger.debug("Der Uebergabestand ist nicht lesbar.", exc_info=True)
            self._uebergabe = None
        self._uebergabe_zaehler: dict[str, int] = {}

        self._health.set_change_callback(self._on_availability_changed)
        self._health.set_busy_check(lambda: self._conversation_active)

        self._build_providers()
        if self.offline_mode:
            self._health.set_allowed_providers(self.local_provider_names)

    # --- Aufbau ---------------------------------------------------------------

    def _build_providers(self) -> None:
        """Erzeugt alle in ``config.yaml`` konfigurierten Provider."""

        for role in ("primary", "fallback"):
            section = self._ai_config.get(role) or {}
            engine = str(section.get("engine", "")).strip()
            if not engine:
                continue
            provider_type = PROVIDER_TYPES.get(engine)
            if provider_type is None:
                logger.error("Unbekannter Provider-Typ in config.yaml: '%s'", engine)
                continue

            provider_settings = dict(section)
            provider_settings.setdefault("instance_name", engine)
            provider = provider_type(provider_settings)
            self._providers[engine] = provider
            self._health.register(provider)

            if role == "primary":
                self._primary_name = engine
            else:
                self._fallback_name = engine

            logger.info(
                "Provider '%s' registriert (Rolle=%s, Modell=%s).",
                engine,
                role,
                provider.model or "(nicht gesetzt)",
            )

        # Zusätzliche Provider aus dem optionalen Abschnitt "additional".
        for engine, section in (self._ai_config.get("additional") or {}).items():
            if not bool(section.get("enabled", True)):
                logger.info(
                    "Zusätzlicher Provider '%s' ist in config.yaml deaktiviert.",
                    engine,
                )
                continue
            provider_type = PROVIDER_TYPES.get(str(section.get("engine", engine)))
            if provider_type is None:
                logger.error("Unbekannter zusätzlicher Provider: '%s'", engine)
                continue
            provider_settings = dict(section)
            provider_settings.setdefault("instance_name", engine)
            provider = provider_type(provider_settings)
            self._providers[engine] = provider
            self._health.register(provider)
            logger.info("Zusätzlicher Provider '%s' registriert.", engine)

    # --- Start / Stop ----------------------------------------------------------

    async def start(self) -> None:
        """Wählt beim Start den passenden Provider und startet die Überwachung."""

        # Beim Start ausdruecklich nachfragen: Hier gibt es noch keine
        # gelungene Antwort, an der sich die Erreichbarkeit ablesen liesse.
        results = await self._health.check_now(force=True)
        logger.info("Provider-Verfügbarkeit beim Start: %s", results)

        if self.offline_mode:
            # Ein gespeicherter Offlinebetrieb darf auch waehrend des Starts
            # niemals kurz ein Cloud-Modell aktivieren. Ist Ollama noch nicht
            # oben, wird es hier automatisch vorbereitet.
            local = await self._ready_local_provider(results=results, start_services=True)
            self._active_name = local or next(iter(self.local_provider_names), None)
        else:
            mode = str(self._ai_config.get("provider", "auto")).lower()
            if mode != "auto" and mode in self._providers:
                self._active_name = mode
            elif self._primary_name and results.get(self._primary_name):
                self._active_name = self._primary_name
            elif self._fallback_name and results.get(self._fallback_name):
                self._active_name = self._fallback_name
            else:
                # Fehlt das Internet und Ollama war beim Start noch nicht
                # aktiv, darf der blosse installierte Claude-Client nicht
                # gewinnen. Ollama wird hier hochgefahren und als
                # voruebergehender Ersatz gewaehlt. Der Benutzermodus bleibt
                # dabei "auto"; bei wiederhergestelltem Netz kehrt der
                # Gesundheitswaechter selbststaendig zu Claude zurueck.
                local = await self._ready_local_provider(
                    results=results,
                    start_services=True,
                )
                self._active_name = (
                    local or self._primary_name or self._fallback_name
                )

        logger.info("Aktiver Provider: %s", self._active_name)
        await self._publish_provider_event("selected")
        await self._health.start()
        await self.prewarm()

    async def prewarm(self) -> None:
        """Lässt Provider sich vorbereiten, die das können.

        Der Claude-Code-Provider hält dafür einen Prozess bereit, der auf
        die nächste Frage wartet. Das Starten kostet auf einem
        Windows-Rechner mehrere Sekunden – die sollen beim Hochfahren
        anfallen, nicht mitten im Gespräch.

        Fehlschläge werden bewusst nur vermerkt: Vorwärmen ist eine
        Beschleunigung, keine Voraussetzung.
        """

        provider = self.active_provider
        aufwaermen = getattr(provider, "prewarm", None) or getattr(provider, "waermen", None)
        if aufwaermen is not None:
            try:
                await aufwaermen()
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Das Vorwaermen des Providers ist fehlgeschlagen.", exc_info=True
                )

        self._waerme_lokale_modelle()

    def _waerme_lokale_modelle(self) -> None:
        """Laedt die lokalen Rueckfallmodelle im Hintergrund in den Speicher.

        Bisher waermte der Orb ausschliesslich den AKTIVEN Provider vor -
        im Regelfall also Claude. Die lokalen Modelle, die einspringen
        sollen, wenn Claude nicht kann, blieben kalt. Genau dann kostete
        der Rueckfall am meisten:

            12:44:13  claude_code faellt aus (Anmeldung abgelaufen)
            12:45:13  ollama - keine Antwortverbindung in 60 s
            12:47:05  ollama - dasselbe noch einmal
            12:48:23  erst ollama_fast antwortet

        Das Laden geschieht deshalb hier und im Hintergrund: Der Start
        wartet nicht darauf, und der Benutzer bezahlt es nicht mitten in
        seiner ersten Frage. Es ist eine Beschleunigung, keine Bedingung -
        scheitert es, faellt nichts aus, es dauert nur wieder laenger.

        Der Richter-Provider der Messlaeufe bleibt aussen vor: Er wird im
        Dialog nie gefragt, wuerde aber als groesstes Modell den meisten
        Speicher belegen.
        """

        if not bool(getattr(self, "_ai_config", {}).get("prewarm_local", True)):
            return

        laufend = getattr(self, "_lokal_waerme_task", None)
        if laufend is not None and not laufend.done():
            return

        aktiv = self._active_name
        namen: list[str] = []
        for kandidat in (
            self._fallback_name,
            str(self._local_routing_config.get("main_provider", "")).strip(),
            str(self._local_routing_config.get("fast_provider", "")).strip(),
        ):
            if not kandidat or kandidat == aktiv or kandidat in namen:
                continue
            anbieter = self._providers.get(kandidat)
            if anbieter is None or not anbieter.is_local:
                continue
            if getattr(anbieter, "waermen", None) is None:
                continue
            namen.append(kandidat)

        if not namen:
            return

        async def _lauf() -> None:
            # Nacheinander, nicht gleichzeitig: Zwei Modelle, die sich
            # zeitgleich in denselben Arbeitsspeicher laden, brauchen
            # zusammen laenger als nacheinander - und blockieren dabei
            # eine echte Frage, falls eine dazwischenkommt.
            for name in namen:
                anbieter = self._providers.get(name)
                if anbieter is None:
                    continue
                try:
                    async with self._inference_slot(anbieter):
                        await anbieter.waermen()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Das lokale Modell '%s' liess sich nicht vorwaermen.",
                        name,
                        exc_info=True,
                    )

        logger.info(
            "Die lokalen Rueckfallmodelle werden im Hintergrund vorgewaermt: %s",
            ", ".join(namen),
        )
        self._lokal_waerme_task = asyncio.create_task(
            _lauf(), name="provider-lokal-waermen"
        )

    async def stop(self) -> None:
        """Beendet die Überwachung."""

        waerme = getattr(self, "_lokal_waerme_task", None)
        if waerme is not None and not waerme.done():
            waerme.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await waerme
        self._lokal_waerme_task = None

        await self._health.stop()
        for provider in self._providers.values():
            aufraeumen = getattr(provider, "shutdown", None)
            if aufraeumen is None:
                continue
            try:
                await aufraeumen()
            except Exception:  # noqa: BLE001
                logger.debug("Provider-Aufraeumen fehlgeschlagen.", exc_info=True)
        for service in self._ollama_services.values():
            await asyncio.to_thread(service.stop)
        self._ollama_services.clear()

    # --- Auswahl ---------------------------------------------------------------

    @property
    def active_provider(self) -> BaseProvider | None:
        """Der aktuell aktive Provider."""

        if self._active_name is None:
            return None
        return self._providers.get(self._active_name)

    @property
    def active_name(self) -> str | None:
        """Name des aktuell aktiven Providers."""

        return self._active_name

    @property
    def operating_mode(self) -> str:
        """Aktueller Laufzeitmodus: ``auto`` oder strikt ``offline``."""

        return self._operating_mode

    @property
    def offline_mode(self) -> bool:
        return self._operating_mode == "offline"

    @property
    def local_provider_names(self) -> list[str]:
        """Alle konfigurierten Provider, die nachweislich lokal sind."""

        return [name for name, provider in self._providers.items() if provider.is_local]

    @property
    def local_routing_active(self) -> bool:
        """Ob die rein lokale Mehrmodell-Verteilung gerade greifen darf.

        Sie ist bei einem ausdruecklichen Offlinebefehl aktiv. Im
        Automatikmodus wird sie ebenfalls aktiv, sobald der tatsaechlich
        aktive Provider lokal ist oder alle bekannten Cloud-Provider als
        nicht erreichbar gelten. Bei einer gesunden Onlineverbindung bleibt
        sie aus; das Nebenmodell mischt sich dann nicht in Cloud-Dialoge ein.
        """

        if not bool(self._local_routing_config.get("enabled", False)):
            return False
        if self.offline_mode:
            return True
        if self.active_provider is not None and self.active_provider.is_local:
            return True

        cloud_names = [
            name for name, provider in self._providers.items() if not provider.is_local
        ]
        local_names = self.local_provider_names
        if not local_names:
            return False
        cloud_available = any(self._health.record(name).available for name in cloud_names)
        local_available = any(self._health.record(name).available for name in local_names)
        return local_available and not cloud_available

    def local_provider_for(self, role: str = "main") -> str | None:
        """Liefert den konfigurierten lokalen Haupt- oder Nebenprovider.

        Ausserhalb des lokalen Betriebs gibt die Methode absichtlich
        ``None`` zurueck. Aufrufer koennen sie daher gefahrlos fuer eine
        bedingte Aufgabenverteilung verwenden, ohne Onlineanfragen
        versehentlich lokal umzuleiten.
        """

        if not self.local_routing_active:
            return None
        key = "fast_provider" if str(role).lower() in {"fast", "side", "neben"} else "main_provider"
        name = str(self._local_routing_config.get(key, "")).strip()
        provider = self._providers.get(name)
        if provider is None or not provider.is_local:
            return None
        return name

    async def set_operating_mode(
        self, mode: str, *, persist: bool = True
    ) -> dict[str, Any]:
        """Schaltet verbindlich zwischen Offline- und Automatikbetrieb um.

        Im Offlinebetrieb wird die Verfuegbarkeit des lokalen Modells vor
        dem Umschalten geprueft. Erst wenn es wirklich antwortbereit ist,
        wird der Modus aktiviert. Cloud-Fallbacks sind dann sowohl fuer
        normale als auch fuer gestreamte Antworten ausgeschlossen.
        """

        requested = str(mode).strip().lower()
        if requested in {"online", "automatic", "automatisch"}:
            requested = "auto"
        if requested not in {"auto", "offline"}:
            return {
                "success": False,
                "mode": self._operating_mode,
                "message": "Unbekannter Betriebsmodus. Moeglich sind offline und online.",
            }

        previous_mode = self._operating_mode
        previous_provider = self._active_name

        if requested == "offline":
            local = await self._ready_local_provider(start_services=True)
            if not local:
                names = ", ".join(self.local_provider_names) or "keiner"
                return {
                    "success": False,
                    "mode": previous_mode,
                    "provider": previous_provider,
                    "message": (
                        "Der Offlinebetrieb wurde nicht aktiviert, weil kein lokales "
                        f"Modell einsatzbereit ist. Konfigurierte lokale Provider: {names}. "
                        "Pruefe bitte Ollama und das konfigurierte Modell."
                    ),
                }
            self._operating_mode = "offline"
            self._health.set_allowed_providers(self.local_provider_names)
            self._pending_switch = None
            self._active_name = local
            await self._suspend_cloud_providers()
            message = (
                f"Offlinebetrieb ist aktiv. Ich verwende jetzt {local} mit "
                f"{self._providers[local].model} und falle nicht auf ein Cloud-Modell zurueck."
            )
        else:
            # Waehren der frischen Pruefung bereits den Automatikmodus setzen,
            # damit der Health-Callback einen wieder erreichbaren Primaer-
            # provider nicht wegen des alten Offlineflags verwirft.
            self._operating_mode = "auto"
            self._health.set_allowed_providers(None)
            results = await self._health.check_now(force=True)
            target = None
            if self._primary_name and results.get(self._primary_name):
                target = self._primary_name
            elif self._fallback_name and results.get(self._fallback_name):
                target = self._fallback_name
            else:
                target = await self._first_available()
            if target:
                self._active_name = target
            message = (
                "Onlinebetrieb ist wieder aktiv. Die Modellauswahl erfolgt automatisch"
                + (f"; aktuell verwende ich {self._active_name}." if self._active_name else ".")
            )

        if persist:
            try:
                self._mode_store.set("mode", self._operating_mode)
            except OSError:
                logger.exception("Der Provider-Betriebsmodus liess sich nicht speichern.")

        await self._publish_provider_event(
            "mode_changed",
            reason="sprachbefehl",
            previous=previous_provider,
            previous_mode=previous_mode,
        )
        await self.prewarm()
        return {
            "success": True,
            "mode": self._operating_mode,
            "provider": self._active_name,
            "model": self.active_provider.model if self.active_provider else None,
            "message": message,
        }

    async def _ready_local_provider(
        self,
        *,
        results: dict[str, bool] | None = None,
        start_services: bool = False,
    ) -> str | None:
        """Findet ein wirklich antwortbereites lokales Modell."""

        for name in self.local_provider_names:
            provider = self._providers[name]
            available = bool(results.get(name)) if results is not None else False
            if results is None:
                try:
                    available = await provider.is_available()
                except Exception:  # noqa: BLE001
                    available = False
            if available:
                self._health.note_success(name, 0.0)
                return name

            if start_services and str(provider.settings.get("engine", "")) == "ollama":
                if await self._prepare_ollama(name, provider):
                    self._health.note_success(name, 0.0)
                    return name
        return None

    async def _prepare_ollama(self, name: str, provider: BaseProvider) -> bool:
        """Startet Ollama bei Bedarf und prueft das konfigurierte Modell."""

        from backend.launcher.ollama_service import OllamaService

        service = self._ollama_services.get(name)
        if service is None:
            service = OllamaService(
                base_url=str(provider.settings.get("base_url", "")),
                model=provider.model,
            )
            self._ollama_services[name] = service
        state = await asyncio.to_thread(
            service.prepare,
            download_model=False,
        )
        if not bool(state.get("ready")):
            logger.warning("Offline-Modell nicht bereit: %s", state.get("message", ""))
            return False
        try:
            return bool(await provider.is_available())
        except Exception:  # noqa: BLE001
            logger.exception("Ollama meldet sich bereit, Provider-Pruefung scheiterte.")
            return False

    async def _suspend_cloud_providers(self) -> None:
        """Beendet wartende Cloud-Prozesse beim bewussten Offlinewechsel."""

        for provider in self._providers.values():
            if provider.is_local:
                continue
            shutdown = getattr(provider, "shutdown", None)
            if shutdown is None:
                continue
            try:
                result = shutdown()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.debug("Cloud-Provider liess sich nicht anhalten.", exc_info=True)

    def begin_conversation(self) -> None:
        """Markiert den Beginn einer Unterhaltung.

        Solange eine Unterhaltung läuft, wird ein anstehender Providerwechsel
        aufgeschoben, sofern ``switch_immediately`` deaktiviert ist.
        """

        self._conversation_active = True

    async def end_conversation(self) -> None:
        """Markiert das Ende einer Unterhaltung und führt aufgeschobene
        Providerwechsel aus."""

        self._conversation_active = False
        if self._pending_switch is not None:
            target = self._pending_switch
            self._pending_switch = None
            await self._activate(target, reason="unterhaltung_beendet")

    async def _on_availability_changed(self, name: str, available: bool) -> None:
        """Reagiert auf Verfügbarkeitsänderungen eines Providers."""

        if not self._auto_switch:
            return

        if self.offline_mode:
            # Ein erzwungener Offlinebetrieb darf niemals aufgrund einer
            # Gesundheitsmeldung in die Cloud wechseln.
            if not available and name == self._active_name:
                alternative = await self._first_available(
                    exclude=name, local_only=True
                )
                if alternative:
                    await self._activate(alternative, reason="lokaler_ausfall")
            return

        if not available and name == self._active_name:
            # Aktiver Provider ausgefallen: sofort auf eine Alternative wechseln.
            alternative = await self._first_available(exclude=name)
            if alternative:
                await self._activate(alternative, reason="ausfall")
            return

        if available and name == self._primary_name and self._active_name != name:
            # Primärer Provider wieder da.
            if self._switch_immediately or not self._conversation_active:
                await self._activate(name, reason="primär_wieder_verfügbar")
            else:
                self._pending_switch = name
                logger.info(
                    "Primärer Provider wieder verfügbar; Wechsel nach Ende "
                    "der Unterhaltung vorgemerkt."
                )

    async def _first_available(
        self, *, exclude: str | None = None, local_only: bool = False
    ) -> str | None:
        for name in [self._primary_name, self._fallback_name, *self._providers]:
            if not name or name == exclude:
                continue
            if local_only and name not in self.local_provider_names:
                continue
            if self._health.record(name).available:
                return name
        return None

    async def _activate(self, name: str, *, reason: str) -> None:
        if self.offline_mode and name not in self.local_provider_names:
            logger.warning(
                "Providerwechsel auf '%s' blockiert: Offlinebetrieb ist aktiv.", name
            )
            return
        if name == self._active_name or name not in self._providers:
            return
        previous = self._active_name
        self._active_name = name
        logger.info("Providerwechsel: %s → %s (Grund: %s)", previous, name, reason)
        await self._publish_provider_event("switched", reason=reason, previous=previous)

    async def _publish_provider_event(self, action: str, **extra: Any) -> None:
        if self._event_bus is None:
            return
        provider = self.active_provider
        temporary_local_fallback = bool(
            not self.offline_mode and provider is not None and provider.is_local
        )
        await self._event_bus.publish(
            "ai.provider.changed",
            {
                "action": action,
                "provider": self._active_name,
                "model": provider.model if provider else None,
                "mode": self._operating_mode,
                "offline": self.offline_mode,
                "temporary_local_fallback": temporary_local_fallback,
                "selection": (
                    "user_offline"
                    if self.offline_mode
                    else "automatic_local_fallback"
                    if temporary_local_fallback
                    else "automatic_cloud"
                ),
                **extra,
            },
        )

    # --- Anfragen ---------------------------------------------------------------

    async def _probe_connectivity(self, *, force: bool = False) -> bool:
        """Liefert schnell den Netzzustand und buendelt parallele Pruefungen."""

        checker = getattr(self, "_connectivity_check", None)
        if checker is None:
            # Kleine, per ``__new__`` gebaute Test-/Werkbank-Manager besitzen
            # absichtlich keinen Netzwerkwaechter. Das ist kein Netzausfall.
            return True

        now = time.monotonic()
        cached = getattr(self, "_last_connectivity_result", None)
        last = float(getattr(self, "_last_connectivity_check", 0.0))
        max_age = float(getattr(self, "_connectivity_cache_seconds", 5.0))
        if not force and cached is not None and now - last <= max_age:
            return bool(cached)

        lock = getattr(self, "_connectivity_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._connectivity_lock = lock
        async with lock:
            now = time.monotonic()
            cached = getattr(self, "_last_connectivity_result", None)
            last = float(getattr(self, "_last_connectivity_check", 0.0))
            if not force and cached is not None and now - last <= max_age:
                return bool(cached)
            try:
                result = bool(await checker())
            except Exception:  # noqa: BLE001 - im Zweifel Provider selbst pruefen.
                logger.debug(
                    "Internetpruefung vor der Anfrage fehlgeschlagen; "
                    "Cloud-Provider wird normal versucht.",
                    exc_info=True,
                )
                return True
            self._last_connectivity_check = time.monotonic()
            self._last_connectivity_result = result
            return result

    async def _activate_network_fallback(self) -> bool:
        """Schaltet im Automatikmodus Modell und Stimme gemeinsam lokal."""

        if self.offline_mode:
            return True
        self._health.note_network_unavailable()
        local = await self._ready_local_provider(
            results={
                name: self._health.record(name).available
                for name in self._providers
            },
            start_services=True,
        )
        if not local:
            logger.warning(
                "Internet ist nicht erreichbar und kein lokaler Provider "
                "liess sich starten."
            )
            return False
        await self._activate(local, reason="internet_nicht_erreichbar")
        return True

    async def _ensure_network_route(self) -> None:
        """Faengt einen Netzausfall vor einem langen Cloud-Aufruf ab."""

        provider = self.active_provider
        if self.offline_mode or provider is None or provider.is_local:
            return
        if await self._probe_connectivity():
            return
        await self._activate_network_fallback()

    @staticmethod
    def _is_connectivity_error(error: BaseException) -> bool:
        lowered = str(error).lower()
        markers = (
            "network is unreachable",
            "network error",
            "no route to host",
            "name resolution",
            "temporary failure in name resolution",
            "getaddrinfo",
            "failed to fetch",
            "unable to connect",
            "cannot connect",
            "connection refused",
            "connection reset",
            "connection aborted",
            "connect timeout",
            "enotfound",
            "econnrefused",
            "econnreset",
            "netzwerk ist nicht erreichbar",
            "netzwerkfehler",
            "verbindung fehlgeschlagen",
            "verbindung abgebrochen",
            "keine internetverbindung",
        )
        return any(marker in lowered for marker in markers)

    async def _handle_possible_network_error(
        self, provider: BaseProvider, error: BaseException
    ) -> None:
        """Bestaetigt Cloud-Verbindungsfehler und aktiviert Ollama sofort."""

        if provider.is_local or self.offline_mode:
            return
        if getattr(self, "_connectivity_check", None) is None:
            return
        lowered = str(error).lower()
        definite = self._is_connectivity_error(error)
        timed_out = "timeout" in lowered or "zeitlimit" in lowered
        if not definite and not timed_out:
            return
        if not definite and await self._probe_connectivity(force=True):
            # Das Netz steht - dann liegt es am Anbieter selbst.
            #
            # Bisher endete der Fall hier: kein Wechsel, kein Vermerk, kein
            # Unterschied zur naechsten Anfrage. Bei einer Hotspot-
            # Anmeldeseite oder einem traegen Anbieter kostete deshalb JEDE
            # Frage erneut das volle Zeitlimit, unbegrenzt oft. Der
            # Gesundheitseintrag weiss nach zwei Fehlschlaegen Bescheid -
            # nur erfuhr davon niemand, weil ``note_error`` selbst keinen
            # Wechsel ausloest. Diese Meldung holt das nach.
            if timed_out and not self._health.record(provider.name).available:
                logger.warning(
                    "Provider '%s' laeuft wiederholt ins Zeitlimit, obwohl das "
                    "Netz erreichbar ist. Es wird auf eine Alternative "
                    "gewechselt.",
                    provider.name,
                )
                await self._on_availability_changed(provider.name, False)
            return
        self._last_connectivity_result = False
        self._last_connectivity_check = time.monotonic()
        await self._activate_network_fallback()

    @asynccontextmanager
    async def _inference_slot(self, provider: BaseProvider):
        """Serialisiert lokale CPU-Inferenz, laesst Cloud aber parallel."""

        if provider.is_local and bool(
            self._local_routing_config.get("sequential_only", True)
        ):
            async with self._local_inference_lock:
                yield
            return
        yield

    def _provider_order(
        self,
        preferred: str | None = None,
        *,
        fast_dialog: bool = False,
        kategorie: str = "",
    ) -> list[str]:
        """Baut die Reihenfolge fuer eine Anfrage.

        Ein expliziter Wunsch stammt von einem Subagenten. In diesem Fall
        werden nach dessen Wunsch zuerst die konfigurierten externen
        Subagenten-Provider und das lokale Modell versucht; der aktive
        Hauptprovider (meist Claude) kommt erst danach. Normale Dialogzuege
        behalten dagegen unveraendert den aktiven Hauptprovider an erster
        Stelle.
        """

        allowed = (
            set(self.local_provider_names)
            if self.offline_mode
            else set(self._providers)
        )
        now = time.monotonic()
        cooldowns = getattr(self, "_quota_cooldowns", {})
        order: list[str] = []
        #: Bekannt gestoerte Anbieter. Sie fliegen nicht raus, sie ruecken
        #: nach hinten - siehe ``_ist_bekannt_gestoert``.
        nachrangig: list[str] = []

        if preferred:
            configured = getattr(self, "_ai_config", {}).get(
                "subagent_fallback_order", []
            )
            candidates = (
                preferred,
                *configured,
                self._fallback_name,
                self._active_name,
                self._primary_name,
            )
        else:
            order_key = (
                "dialog_fallback_order" if fast_dialog else "capable_fallback_order"
            )
            configured = getattr(self, "_ai_config", {}).get(order_key, [])
            if not configured:
                configured = getattr(self, "_ai_config", {}).get(
                    "dialog_fallback_order", []
                )
            candidates = (
                self._active_name,
                self._primary_name,
                *configured,
                self._fallback_name,
            )

        # Die stufenweise Uebergabe an das lokale Modell.
        #
        # Hat eine Kategorie ihre Pruefungen bestanden, wird der
        # entsprechende Anteil ihrer Anfragen lokal bearbeitet - und zwar
        # deterministisch ausgelost, damit sich derselbe Fall im Test
        # wiederholen laesst. Solange keine Kategorie geprueft ist, steht
        # ueberall 0 %, und hier aendert sich nichts.
        lokal_zuerst = self._lokal_uebernimmt(kategorie)
        if lokal_zuerst:
            candidates = (lokal_zuerst, *candidates)

        for candidate in (*candidates, *self._providers):
            name = str(candidate or "").strip()
            if not name or name not in allowed or name in order or name in nachrangig:
                continue
            if cooldowns.get(name, 0.0) > now:
                logger.debug("Provider '%s' wegen Quoten-Sperrfrist uebersprungen.", name)
                continue
            if self._ist_bekannt_gestoert(name):
                logger.debug(
                    "Provider '%s' ist als nicht erreichbar vermerkt und wird "
                    "nach hinten gestellt.",
                    name,
                )
                nachrangig.append(name)
                continue
            order.append(name)
        # Die gestoerten kommen ans Ende und nicht in den Papierkorb: Der
        # Gesundheitsvermerk kann veraltet sein, und lieber ein spaeter
        # Versuch als gar keine Antwort.
        return order + nachrangig

    def _lokal_uebernimmt(self, kategorie: str, *, wurf: int | None = None) -> str:
        """Ob das lokale Modell diese Anfrage bearbeiten soll.

        Gibt den Namen des lokalen Providers zurueck, wenn ja, sonst "".

        Die Auslosung ist absichtlich nicht zufaellig, sondern haengt an
        Kategorie und Zaehler: Derselbe Fall faellt im Test immer gleich
        aus. Wer den Anteil auf 25 % stellt, bekommt jede vierte Anfrage
        lokal - nachvollziehbar, nicht ungefaehr.
        """

        if not kategorie or self.offline_mode:
            return ""
        uebergabe = getattr(self, "_uebergabe", None)
        if uebergabe is None:
            return ""
        try:
            anteil = int(uebergabe.anteil_lokal(kategorie))
        except Exception:  # noqa: BLE001 - die Uebergabe darf nie den Zug reissen.
            return ""
        if anteil <= 0:
            return ""

        name = self.local_provider_for("main") or self._fallback_name or ""
        if not name or name not in self._providers:
            return ""

        if anteil >= 100:
            return name

        zaehler = getattr(self, "_uebergabe_zaehler", {})
        naechster = int(zaehler.get(kategorie, 0)) + 1
        zaehler[kategorie] = naechster
        self._uebergabe_zaehler = zaehler
        gezogen = wurf if wurf is not None else ((naechster * 37) % 100)
        return name if gezogen < anteil else ""

    def _ist_bekannt_gestoert(self, name: str) -> bool:
        """Ob ein Anbieter nachweislich nicht erreichbar ist.

        Vorher richtete sich die Reihenfolge allein nach den
        Quoten-Sperrfristen. Der Gesundheitswaechter wusste laengst, dass
        ein Anbieter tot ist - gefragt wurde er trotzdem als Erster, und
        zwar bei jeder einzelnen Anfrage bis zum vollen Zeitlimit. Genau
        diese Wartezeit faellt hier weg.

        Nur ein BELEGTER Ausfall zaehlt: entweder eine echte Pruefung
        (``last_check``) oder zwei Fehlschlaege in Folge. Ein Anbieter, der
        noch nie geprueft wurde - etwa unmittelbar nach dem Start -, gilt
        nicht als gestoert und behaelt seinen Platz.
        """

        entry = self._health.record(name)
        if entry.available:
            return False
        return entry.last_check > 0 or entry.consecutive_failures >= 2

    @staticmethod
    def _messages_for_provider(
        provider: BaseProvider, messages: list[ChatMessage]
    ) -> list[ChatMessage]:
        """Verdichtet nur den explizit dafuer konfigurierten Schnellprovider.

        Der zentrale Verlauf bleibt unangetastet. Gekuerzt wird lediglich die
        Kopie fuer diesen einen lokalen Aufruf, damit ein Claude-Ausfall nicht
        ploetzlich tausende alte Prompt-Tokens auf der CPU vorrechnen muss.
        """

        settings = provider.settings
        recent = max(0, int(settings.get("recent_messages", 0) or 0))
        character_limit = max(
            0, int(settings.get("max_input_characters", 0) or 0)
        )
        compact_system = str(settings.get("compact_system_prompt", "")).strip()
        if not (recent or character_limit or compact_system):
            return messages

        history = [message for message in messages if message.role != "system"]
        if recent:
            history = history[-recent:]
        compact: list[ChatMessage] = []
        if compact_system:
            compact.append(ChatMessage(role="system", content=compact_system))
        elif messages and messages[0].role == "system":
            compact.append(messages[0])
        compact.extend(history)

        if character_limit:
            # Neueste Nachrichten sind wichtiger. Der Systemprompt bleibt
            # vollstaendig; der Rest wird von hinten in das Budget gepackt.
            system = compact[:1] if compact and compact[0].role == "system" else []
            budget = max(256, character_limit - sum(len(m.content) for m in system))
            selected: list[ChatMessage] = []
            for message in reversed(compact[len(system):]):
                if selected and len(message.content) > budget:
                    break
                content = message.content[-budget:] if len(message.content) > budget else message.content
                selected.append(ChatMessage(role=message.role, content=content))
                budget -= len(content)
                if budget <= 0:
                    break
            compact = [*system, *reversed(selected)]
        return compact

    def _is_fast_dialog(self, max_tokens: int | None) -> bool:
        limit = int(getattr(self, "_ai_config", {}).get("fast_dialog_max_tokens", 160))
        return max_tokens is not None and 0 < max_tokens <= max(1, limit)

    #: Fehler, die sich beim zweiten Versuch garantiert wiederholen.
    #:
    #: Am 06.09. stand claude_code mit abgelaufener Anmeldung den ganzen
    #: Vormittag an erster Stelle: erster Fehlschlag 12:44:13, zweiter
    #: 12:46:05 - und erst der zweite setzte den Anbieter auf "nicht
    #: verfuegbar". Der Benutzer bezahlte den Ausgang eines Versuchs, der
    #: schon feststand. Eine Anmeldung wird nicht dadurch gueltig, dass
    #: man es sofort noch einmal probiert.
    _ENDGUELTIGE_FEHLER: tuple[str, ...] = (
        "nicht angemeldet",
        "not logged in",
        "please log in",
        "authenticate",
        "authentication",
        "unauthorized",
        "http 401",
        "oauth session expired",
        "session expired",
        "invalid api key",
        "ungueltiger schluessel",
    )

    def _note_provider_error(self, name: str, error: ProviderError) -> None:
        """Erfasst Fehler und setzt bei Quotenproblemen eine Sperrfrist."""

        lowered = str(error).lower()
        endgueltig = any(marker in lowered for marker in self._ENDGUELTIGE_FEHLER)
        if endgueltig:
            logger.warning(
                "Provider '%s' ist nicht angemeldet oder nicht berechtigt (%s). "
                "Er wird sofort nach hinten gestellt, statt bei der naechsten "
                "Frage erneut zu kosten.",
                name,
                error,
            )
        self._health.note_error(
            name,
            timeout="timeout" in lowered or "zeitlimit" in lowered,
            fatal=endgueltig,
        )
        quota_markers = (
            "http 429",
            "rate limit",
            "rate_limit",
            "usage limit",
            "quota",
            "kontingent",
            "nutzungsgrenze",
            "zu viele anfragen",
        )
        if any(marker in lowered for marker in quota_markers):
            no_credit_markers = (
                "insufficient_quota", "no credits remaining",
                "credit_balance_exhausted", "credit balance exhausted",
            )
            setting = (
                "exhausted_quota_cooldown_seconds"
                if any(marker in lowered for marker in no_credit_markers)
                else "quota_cooldown_seconds"
            )
            seconds = float(getattr(self, "_ai_config", {}).get(
                setting, 21600 if setting.startswith("exhausted") else 300
            ))
            self._quota_cooldowns = getattr(self, "_quota_cooldowns", {})
            self._quota_cooldowns[name] = time.monotonic() + max(10.0, seconds)
            logger.warning(
                "Provider '%s' hat sein Kontingent erreicht und wird fuer %.0f "
                "Sekunden bei Subagenten uebersprungen.",
                name,
                max(10.0, seconds),
            )

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        preferred: str | None = None,
        kategorie: str = "",
    ) -> ProviderResponse:
        """Führt eine Chat-Anfrage über den aktiven (oder gewünschten) Provider aus.

        Schlägt die Anfrage fehl, wird automatisch der nächste verfügbare
        Provider versucht, bevor ein Fehler ausgelöst wird.

        Args:
            messages: Der Gesprächsverlauf.
            temperature: Optionale Kreativitätssteuerung.
            max_tokens: Optionale Längenbegrenzung.
            preferred: Optionaler Wunschprovider (z. B. wenn der
                Orchestrator für eine Teilaufgabe bewusst das lokale
                Modell nutzen möchte).

        Raises:
            ProviderError: Wenn kein Provider die Anfrage bearbeiten konnte.
        """

        await self._ensure_network_route()
        order = self._provider_order(
            preferred,
            fast_dialog=self._is_fast_dialog(max_tokens),
            kategorie=kategorie,
        )

        if not order:
            raise ProviderError("Kein KI-Provider konfiguriert.")

        last_error: Exception | None = None
        for name in order:
            provider = self._providers[name]
            provider_messages = self._messages_for_provider(provider, messages)
            started = time.perf_counter()
            try:
                mark_stage("provider_requested")
                async with self._inference_slot(provider):
                    response = await provider.chat(
                        provider_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                self._health.note_success(name, time.perf_counter() - started)
                mark_stage("provider_first_text")
                if name != self._active_name:
                    # Ein einzelner Ausweichtreffer macht den Ausweichprovider
                    # NICHT zum neuen Standard.
                    #
                    # Das war der Grund, warum Werkzeuge "zuerst gehen und dann
                    # ploetzlich nicht mehr": Setzte Claude ein einziges Mal
                    # kurz aus, sprang Ollama ein - und BLIEB ab da aktiv. Der
                    # Rest der Sitzung lief dann am schwaecheren lokalen Modell,
                    # das die Bilddatei nicht lesen kann (Bildschirm-Ansehen)
                    # und Werkzeugaufrufe kaum trifft. Aus einem Wackler wurde
                    # so ein Dauerzustand.
                    #
                    # Welcher Provider DAUERHAFT aktiv ist, entscheidet allein
                    # der Gesundheitswaechter anhand echter Verfuegbarkeit. Ein
                    # Wackler faellt fuer DIESE Anfrage aus, die naechste
                    # versucht wieder zuerst den starken Provider.
                    logger.info(
                        "Anfrage ueber Ausweichprovider '%s' beantwortet - "
                        "aktiv bleibt '%s'.",
                        name,
                        self._active_name or "unbekannt",
                    )
                return response
            except ProviderError as error:
                last_error = error
                self._note_provider_error(name, error)
                await self._handle_possible_network_error(provider, error)
                logger.warning("Provider '%s' fehlgeschlagen: %s", name, error)
            except Exception as error:  # noqa: BLE001 - Fallback muss weiterlaufen.
                # Ein Adapter sollte technische Fehler als ProviderError
                # vereinheitlichen. Tut er das einmal nicht (z. B. ein
                # Windows-Prozessfehler), darf dadurch trotzdem nicht der
                # komplette Dialogzug abbrechen. Der naechste Provider ist
                # genau fuer diesen Fall konfiguriert.
                wrapped = ProviderError(f"{name}: unerwarteter Fehler - {error}")
                last_error = wrapped
                self._note_provider_error(name, wrapped)
                await self._handle_possible_network_error(provider, wrapped)
                logger.exception(
                    "Provider '%s' ist unerwartet fehlgeschlagen; "
                    "der naechste Provider uebernimmt.",
                    name,
                )

        raise ProviderError(
            f"Alle Provider fehlgeschlagen. Letzter Fehler: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        preferred: str | None = None,
        kategorie: str = "",
    ) -> AsyncIterator[str]:
        """Streamt die Antwort des aktiven Providers Stück für Stück.

        Anders als :meth:`chat` wird hier bewusst NICHT über mehrere
        Provider hinweg zurückgefallen: Sobald das erste Stück gesprochen
        ist, lässt sich der Anbieter nicht mehr wechseln, ohne dass es
        holpert. Streaming ist ein Versprechen auf einen durchgehenden
        Fluss – ein Providerwechsel mittendrin bräche genau das. Scheitert
        der Stream, meldet sich der Fehler, und die aufrufende Stelle kann
        auf den gewöhnlichen :meth:`chat` zurückfallen.
        """

        await self._ensure_network_route()
        order = self._provider_order(
            preferred,
            fast_dialog=self._is_fast_dialog(max_tokens),
            kategorie=kategorie,
        )
        if not order:
            raise ProviderError("Kein KI-Provider konfiguriert.")

        last_error: ProviderError | None = None
        for candidate in order:
            provider = self._providers[candidate]
            provider_messages = self._messages_for_provider(provider, messages)
            started = time.perf_counter()
            delivered = False
            try:
                mark_stage("provider_requested")
                async with self._inference_slot(provider):
                    async for piece in provider.chat_stream(
                        provider_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ):
                        if piece:
                            mark_stage("provider_first_text")
                            delivered = True
                            yield piece
                self._health.note_success(candidate, time.perf_counter() - started)
                return
            except ProviderError as error:
                last_error = error
                self._note_provider_error(candidate, error)
                await self._handle_possible_network_error(provider, error)
                if delivered:
                    raise
                logger.warning(
                    "Provider '%s' lieferte noch keinen Text (%s); "
                    "der naechste Provider uebernimmt.",
                    candidate,
                    error,
                )
            except Exception as error:  # noqa: BLE001 - vor Text sicher ausweichen.
                wrapped = ProviderError(
                    f"{candidate}: unerwarteter Streamingfehler - {error}"
                )
                last_error = wrapped
                self._note_provider_error(candidate, wrapped)
                await self._handle_possible_network_error(provider, wrapped)
                if delivered:
                    raise wrapped from error
                logger.exception(
                    "Provider '%s' scheiterte vor dem ersten Text unerwartet; "
                    "der naechste Provider uebernimmt.",
                    candidate,
                )

        raise ProviderError(
            f"Alle Provider blieben vor dem ersten Antworttext aus: {last_error}"
        )

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        images: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Bequemlichkeitsfunktion für eine Einzelanfrage ohne Verlauf.

        ``system_prompt`` wird als eigene Nachricht vorangestellt – so, wie
        es der Gesprächsverlauf auch tut.

        Warum das hier ausdrücklich steht und nicht einfach durchgereicht
        wird: Vorher gingen alle zusätzlichen Angaben unbesehen an
        :meth:`chat` weiter, und die kennt weder ``system_prompt`` noch
        ``images``. Jeder Aufruf mit einem Systemprompt endete deshalb in
        einem TypeError – und weil die Bildauswertung genau so aufruft,
        konnte der Orb nie etwas auf dem Bildschirm sehen. Der Fehler
        stand nur im Protokoll; nach aussen kam bloss "die Auswertung ist
        fehlgeschlagen".

        ``images`` wird nur an einen Provider weitergegeben, der diese
        Faehigkeit ausdruecklich meldet. Dadurch kann OpenAI Bildschirmbilder
        ueber die Responses API auswerten, waehrend lokale Textmodelle
        weiterhin ehrlich auf OCR oder einen anderen Weg zurueckfallen.

        Raises:
            ProviderError: Wenn kein aktiver Provider Bilddaten unterstuetzt.
        """

        if images:
            provider = self.active_provider
            image_method = getattr(provider, "complete_with_images", None)
            if provider is None or not bool(
                getattr(provider, "supports_images", False)
            ) or not callable(image_method):
                raise ProviderError(
                    "Der aktive Anbieter kann keine Bilddaten verarbeiten."
                )
            temperature = kwargs.pop("temperature", None)
            max_tokens = kwargs.pop("max_tokens", None)
            if kwargs:
                unexpected = ", ".join(sorted(str(key) for key in kwargs))
                raise TypeError(f"Unbekannte Bildparameter: {unexpected}")
            started = time.perf_counter()
            response = await image_method(
                prompt,
                system_prompt=system_prompt,
                images=images,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self._health.note_success(
                self._active_name or provider.name,
                time.perf_counter() - started,
            )
            return response.text

        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))

        response = await self.chat(messages, **kwargs)
        return response.text

    async def is_any_available(self) -> bool:
        """Prüft, ob überhaupt ein Sprachmodell nutzbar ist."""

        results = await self._health.check_now()
        return any(results.values())

    # --- Transparenz ---------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Gibt den vollständigen Providerstatus zurück.

        Beantwortet die Transparenzfrage "Warum hast du dieses Modell
        gewählt?" mit nachvollziehbaren Daten.
        """

        provider = self.active_provider
        temporary_local_fallback = bool(
            not self.offline_mode and provider is not None and provider.is_local
        )
        return {
            "active": self._active_name,
            "active_model": provider.model if provider else None,
            "mode": self._operating_mode,
            "offline": self.offline_mode,
            # Ein lokaler Provider im Automatikmodus ist KEIN Wechsel des
            # Betriebsmodus. Diese getrennte Angabe verhindert, dass UI und
            # Sprache einen voruebergehenden Claude-Ausfall faelschlich als
            # vom Benutzer aktivierten Offlinebetrieb darstellen.
            "temporary_local_fallback": temporary_local_fallback,
            "selection": (
                "user_offline"
                if self.offline_mode
                else "automatic_local_fallback"
                if temporary_local_fallback
                else "automatic_cloud"
            ),
            "local_providers": self.local_provider_names,
            "local_routing": {
                "active": self.local_routing_active,
                "main": self.local_provider_for("main"),
                "fast": self.local_provider_for("fast"),
                "sequential_only": bool(
                    self._local_routing_config.get("sequential_only", True)
                ),
            },
            "primary": self._primary_name,
            "fallback": self._fallback_name,
            "auto_switch": self._auto_switch,
            "switch_immediately": self._switch_immediately,
            "pending_switch": self._pending_switch,
            "health": self._health.snapshot(),
        }
