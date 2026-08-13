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
from typing import Any

from backend.config import get_config
from backend.events.event_bus import EventBus
from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.providers import PROVIDER_TYPES
from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.system.logging_setup import get_logger
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
        self._ollama_service: Any | None = None

        self._health = ProviderHealth(
            interval_seconds=float(self._ai_config.get("health_check_interval", 60))
        )
        self._health.set_change_callback(self._on_availability_changed)

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

            provider = provider_type(dict(section))
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
            provider_type = PROVIDER_TYPES.get(str(section.get("engine", engine)))
            if provider_type is None:
                logger.error("Unbekannter zusätzlicher Provider: '%s'", engine)
                continue
            provider = provider_type(dict(section))
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
                self._active_name = self._primary_name or self._fallback_name

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
        if aufwaermen is None:
            return
        try:
            await aufwaermen()
        except Exception:  # noqa: BLE001
            logger.debug("Das Vorwaermen des Providers ist fehlgeschlagen.", exc_info=True)

    async def stop(self) -> None:
        """Beendet die Überwachung."""

        await self._health.stop()
        for provider in self._providers.values():
            aufraeumen = getattr(provider, "shutdown", None)
            if aufraeumen is None:
                continue
            try:
                await aufraeumen()
            except Exception:  # noqa: BLE001
                logger.debug("Provider-Aufraeumen fehlgeschlagen.", exc_info=True)
        if self._ollama_service is not None:
            await asyncio.to_thread(self._ollama_service.stop)

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

            if start_services and name == "ollama":
                if await self._prepare_ollama(provider):
                    self._health.note_success(name, 0.0)
                    return name
        return None

    async def _prepare_ollama(self, provider: BaseProvider) -> bool:
        """Startet Ollama bei Bedarf und prueft das konfigurierte Modell."""

        from backend.launcher.ollama_service import OllamaService

        if self._ollama_service is None:
            self._ollama_service = OllamaService(
                base_url=str(provider.settings.get("base_url", "")),
                model=provider.model,
            )
        state = await asyncio.to_thread(
            self._ollama_service.prepare,
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
        await self._event_bus.publish(
            "ai.provider.changed",
            {
                "action": action,
                "provider": self._active_name,
                "model": provider.model if provider else None,
                "mode": self._operating_mode,
                "offline": self.offline_mode,
                **extra,
            },
        )

    # --- Anfragen ---------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        preferred: str | None = None,
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

        order: list[str] = []
        allowed = set(self.local_provider_names) if self.offline_mode else set(self._providers)
        for candidate in (preferred, self._active_name, self._primary_name, self._fallback_name):
            if candidate and candidate in allowed and candidate not in order:
                order.append(candidate)
        for name in self._providers:
            if name in allowed and name not in order:
                order.append(name)

        if not order:
            raise ProviderError("Kein KI-Provider konfiguriert.")

        last_error: Exception | None = None
        for name in order:
            provider = self._providers[name]
            started = time.perf_counter()
            try:
                response = await provider.chat(
                    messages, temperature=temperature, max_tokens=max_tokens
                )
                self._health.note_success(name, time.perf_counter() - started)
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
                self._health.note_error(name, timeout="Timeout" in str(error))
                logger.warning("Provider '%s' fehlgeschlagen: %s", name, error)

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

        allowed = set(self.local_provider_names) if self.offline_mode else set(self._providers)
        name = preferred if preferred in allowed else self._active_name
        if name not in allowed:
            name = self._primary_name if self._primary_name in allowed else None
        if not name or name not in self._providers:
            name = next((candidate for candidate in self._providers if candidate in allowed), "")
        if not name:
            raise ProviderError("Kein KI-Provider konfiguriert.")

        provider = self._providers[name]
        started = time.perf_counter()
        try:
            async for piece in provider.chat_stream(
                messages, temperature=temperature, max_tokens=max_tokens
            ):
                yield piece
            self._health.note_success(name, time.perf_counter() - started)
        except ProviderError as error:
            self._health.note_error(name, timeout="Timeout" in str(error))
            raise

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

        ``images`` nimmt diese Stelle entgegen, gibt sie aber nicht weiter:
        Kein Provider hier kann Bilddaten im Gesprächsverlauf entgegen-
        nehmen. Sie stillschweigend fallen zu lassen wäre schlimmer als der
        alte Fehler, deshalb sagt es die Ausnahme deutlich – und die
        aufrufende Stelle kann auf einen Weg ausweichen, den es wirklich
        gibt.

        Raises:
            ProviderError: Wenn Bilddaten mitgegeben werden.
        """

        if images:
            raise ProviderError(
                "Bilddaten lassen sich diesen Anbietern nicht im Verlauf "
                "mitgeben. Nutze einen Anbieter, der Dateien selbst öffnet, "
                "und nenne ihm den Pfad."
            )

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
        return {
            "active": self._active_name,
            "active_model": provider.model if provider else None,
            "mode": self._operating_mode,
            "offline": self.offline_mode,
            "local_providers": self.local_provider_names,
            "primary": self._primary_name,
            "fallback": self._fallback_name,
            "auto_switch": self._auto_switch,
            "switch_immediately": self._switch_immediately,
            "pending_switch": self._pending_switch,
            "health": self._health.snapshot(),
        }
