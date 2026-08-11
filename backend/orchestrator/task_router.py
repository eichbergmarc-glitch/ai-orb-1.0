"""Task Router – leitet klassifizierte Aufgaben an die passenden Module.

Der Router ist die Stelle, an der entschieden wird, ob eine Aufgabe lokal
und ohne Sprachmodell erledigt werden kann (Programm starten, Datei suchen,
Systemstatus, Transparenzauskunft) oder ob sie an einen KI-Provider
weitergereicht werden muss.

Der Router führt selbst keine Systembefehle aus, sondern ruft ausschließlich
:class:`~backend.system.desktop_control.DesktopControl` auf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from backend.orchestrator import intent_classifier as intents
from backend.orchestrator.intent_classifier import IntentResult
from backend.system.desktop_control import DesktopControl
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class RouteResult:
    """Ergebnis einer Weiterleitung durch den Task Router."""

    handled_locally: bool
    response: str = ""
    requires_llm: bool = False
    requires_confirmation: bool = False
    module: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled_locally": self.handled_locally,
            "response": self.response,
            "requires_llm": self.requires_llm,
            "requires_confirmation": self.requires_confirmation,
            "module": self.module,
            "data": self.data,
        }


#: Signatur eines Handlers: erhält Originaltext und Intent-Ergebnis.
RouteHandler = Callable[[str, IntentResult], Awaitable[RouteResult]]


class TaskRouter:
    """Leitet Aufgaben an lokale Module oder an den KI-Provider."""

    def __init__(self, desktop: DesktopControl | None = None) -> None:
        self._desktop = desktop or DesktopControl()
        self._handlers: dict[str, RouteHandler] = {}
        self._register_defaults()

    def register(self, intent: str, handler: RouteHandler) -> None:
        """Registriert einen Handler für einen Intent.

        Skills und Plugins können hierüber eigene Intents bedienen, ohne
        den Kern zu verändern.
        """

        self._handlers[intent] = handler

    def _register_defaults(self) -> None:
        self.register(intents.APP_START, self._handle_app_start)
        self.register(intents.APP_CLOSE, self._handle_app_close)
        self.register(intents.FILE_SEARCH, self._handle_file_search)
        self.register(intents.TERMINAL, self._handle_terminal)
        self.register(intents.BROWSER, self._handle_browser)
        self.register(intents.SYSTEM_STATUS, self._handle_system_status)

    async def route(self, text: str, intent: IntentResult) -> RouteResult:
        """Leitet eine Anfrage weiter.

        Returns:
            Ein :class:`RouteResult`. Ist ``handled_locally`` ``False``,
            muss die Anfrage an einen KI-Provider weitergereicht werden.
        """

        handler = self._handlers.get(intent.intent)
        if handler is None:
            return RouteResult(handled_locally=False, requires_llm=True, module="ai_provider")

        try:
            result = await handler(text, intent)
        except Exception:  # noqa: BLE001 - ein Modulfehler darf den Orb nicht stoppen.
            logger.exception("Fehler im Handler für Intent '%s'.", intent.intent)
            return RouteResult(
                handled_locally=True,
                response="Bei der Ausführung ist ein Fehler aufgetreten. Ich habe die Aktion abgebrochen.",
                module=intent.intent,
            )

        logger.info(
            "Intent '%s' an Modul '%s' geleitet (lokal=%s).",
            intent.intent,
            result.module,
            result.handled_locally,
        )
        return result

    # --- Standard-Handler ---------------------------------------------------------

    async def _handle_app_start(self, text: str, intent: IntentResult) -> RouteResult:
        applications = intent.entities.get("applications") or []
        if not applications:
            applications = self._guess_application(text)

        if not applications:
            # Nicht in der Liste erkannt – das ist KEINE Absage.
            #
            # Die Liste kennt acht Programme. Alles andere endete hier mit
            # „Ich habe nicht erkannt, welches Programm gestartet werden
            # soll" – und das Sprachmodell, das „mach mir Spotify auf"
            # mühelos versteht, wurde nie gefragt. Es kennt das Werkzeug
            # 'programm_starten', und das startet im offenen Modus jedes
            # Programm auf diesem Rechner.
            logger.info(
                "Kein gelistetes Programm in '%s' erkannt – das Sprachmodell "
                "übernimmt mit dem Werkzeug 'programm_starten'.",
                text[:80],
            )
            return RouteResult(handled_locally=False, requires_llm=True, module="ai_provider")

        result = self._desktop.launch(applications[0])

        # Scheitert der schnelle lokale Weg, ist das kein Endergebnis.
        #
        # Der lokale Start kennt nur den Eintrag aus config.yaml. Findet er
        # das Programm nicht, kann das Sprachmodell es immer noch: Es kennt
        # das Werkzeug 'programm_starten', das ueber Suchpfad, Windows-
        # Registrierung und den Windows-Starter geht und deutsche Namen
        # uebersetzt. Frueher endete es hier mit „nicht gefunden", und der
        # maechtigere Weg wurde nie versucht.
        if not result.success:
            logger.info(
                "Lokaler Start von '%s' fehlgeschlagen (%s) – das Sprachmodell "
                "versucht es mit dem Werkzeug.",
                applications[0], result.message,
            )
            return RouteResult(handled_locally=False, requires_llm=True, module="ai_provider")

        return RouteResult(
            handled_locally=True,
            response=result.message,
            module="desktop",
            data=result.to_dict(),
        )

    async def _handle_app_close(self, text: str, intent: IntentResult) -> RouteResult:
        applications = intent.entities.get("applications") or self._guess_application(text)
        if not applications:
            return RouteResult(
                handled_locally=True,
                response="Ich habe nicht erkannt, welches Programm beendet werden soll.",
                module="desktop",
            )

        result = self._desktop.close(applications[0])
        return RouteResult(
            handled_locally=True,
            response=result.message,
            requires_confirmation=result.requires_confirmation,
            module="desktop",
            data=result.to_dict(),
        )

    async def _handle_file_search(self, text: str, intent: IntentResult) -> RouteResult:
        files = intent.entities.get("files") or []
        pattern = files[0] if files else self._extract_search_term(text)
        if not pattern:
            return RouteResult(
                handled_locally=True,
                response="Wonach genau soll ich suchen?",
                module="dateien",
            )

        result = self._desktop.find_files(pattern)
        if result.success:
            matches = (result.details or {}).get("matches", [])
            preview = "\n".join(f"• {match}" for match in matches[:10])
            response = f"{result.message}\n{preview}"
        else:
            response = result.message

        return RouteResult(
            handled_locally=True,
            response=response,
            module="dateien",
            data=result.to_dict(),
        )

    async def _handle_terminal(self, text: str, intent: IntentResult) -> RouteResult:
        result = self._desktop.launch("terminal")
        return RouteResult(
            handled_locally=True,
            response=result.message,
            module="desktop",
            data=result.to_dict(),
        )

    async def _handle_browser(self, text: str, intent: IntentResult) -> RouteResult:
        urls = intent.entities.get("urls") or []
        if urls:
            # Eine ausdrückliche Adresse wird direkt geöffnet.
            if urls[0].startswith("file"):
                result = self._desktop.open_path(urls[0])
            else:
                result = self._desktop.open_url(urls[0])
            return RouteResult(
                handled_locally=True,
                response=result.message,
                module="desktop",
                data={"url": urls[0], **result.to_dict()},
            )

        # Steckt in der Anfrage mehr als das bloße Öffnen – „zeig mir das
        # Wetter im Browser", „such im Browser nach …" –, gehört sie NICHT
        # hierher. Früher wurde in solchen Fällen stumpf der Browser
        # gestartet und der eigentliche Auftrag fiel unter den Tisch: Der
        # Benutzer bat um das Wetter und bekam ein leeres Fenster oder gar
        # nichts. Jetzt entscheidet das Sprachmodell mit seinen Werkzeugen
        # (browser_oeffnen, internet_suchen), was wirklich gemeint ist.
        if not self._is_bare_open_command(text):
            return RouteResult(handled_locally=False, requires_llm=True, module="ai_provider")

        applications = intent.entities.get("applications") or ["browser"]
        result = self._desktop.launch(applications[0])
        return RouteResult(
            handled_locally=True,
            response=result.message,
            module="desktop",
            data=result.to_dict(),
        )

    @staticmethod
    def _is_bare_open_command(text: str) -> bool:
        """Ob die Anfrage nur „mach den Browser auf" bedeutet – nicht mehr.

        Der Maßstab: Nach Abzug der Öffnen-Wörter und des Programmnamens
        bleibt praktisch nichts übrig. Bleibt etwas übrig, ist es ein
        Auftrag, den das Sprachmodell verstehen muss.
        """

        import re

        filler = {
            "öffne", "oeffne", "öffnen", "oeffnen", "starte", "starten",
            "mach", "mache", "auf", "bitte", "mal", "den", "die", "das",
            "einen", "eine", "ein", "meinen", "meine", "mein", "browser",
            "chrome", "edge", "firefox", "webbrowser", "internetbrowser",
        }
        words = [word for word in re.findall(r"\w+", text.lower()) if word not in filler]
        return len(words) == 0

    async def _handle_system_status(self, text: str, intent: IntentResult) -> RouteResult:
        status = self._desktop.system_status()
        response = (
            f"System: {status['platform']} {status['release']} ({status['machine']}), "
            f"{status['cpu_count']} CPU-Kerne, "
            f"{status['disk_free_gb']} GB von {status['disk_total_gb']} GB frei."
        )
        return RouteResult(
            handled_locally=True,
            response=response,
            module="system",
            data=status,
        )

    # --- Hilfsfunktionen -------------------------------------------------------------

    def _guess_application(self, text: str) -> list[str]:
        """Sucht in der Eingabe nach einem freigegebenen Programm.

        Nutzt :meth:`DesktopControl.find_in_text`, das auch Aliase kennt –
        „Editor“, „VS Code“, „Dateimanager“ und so fort. Der frühere Weg
        prüfte nur die Programmnamen und übersah deshalb jeden Alias.
        """

        return self._desktop.find_in_text(text)

    @staticmethod
    def _extract_search_term(text: str) -> str:
        """Extrahiert den Suchbegriff aus einer Suchanfrage."""

        lowered = text.lower()
        for marker in ("suche", "finde", "wo ist", "such nach"):
            if marker in lowered:
                index = lowered.index(marker) + len(marker)
                return text[index:].strip(" ?.!\"'")
        return ""
