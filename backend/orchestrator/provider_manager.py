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

logger = get_logger(__name__)


class ProviderManager:
    """Verwaltet alle konfigurierten KI-Provider und deren Auswahl."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
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

        self._health = ProviderHealth(
            interval_seconds=float(self._ai_config.get("health_check_interval", 60))
        )
        self._health.set_change_callback(self._on_availability_changed)

        self._build_providers()

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
        aufwaermen = getattr(provider, "prewarm", None)
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

    async def _first_available(self, *, exclude: str | None = None) -> str | None:
        for name in [self._primary_name, self._fallback_name, *self._providers]:
            if not name or name == exclude:
                continue
            if self._health.record(name).available:
                return name
        return None

    async def _activate(self, name: str, *, reason: str) -> None:
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
        for candidate in (preferred, self._active_name, self._primary_name, self._fallback_name):
            if candidate and candidate in self._providers and candidate not in order:
                order.append(candidate)
        for name in self._providers:
            if name not in order:
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

        name = preferred or self._active_name or self._primary_name
        if not name or name not in self._providers:
            name = next(iter(self._providers), "")
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
            "primary": self._primary_name,
            "fallback": self._fallback_name,
            "auto_switch": self._auto_switch,
            "switch_immediately": self._switch_immediately,
            "pending_switch": self._pending_switch,
            "health": self._health.snapshot(),
        }
