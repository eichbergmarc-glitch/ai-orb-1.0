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
from backend.studium.vorlesungs_session import ist_vorlesungssegment
from backend.config import get_config
from backend.system.desktop_control import DesktopControl
from backend.system.performance_trace import current_turn_trace
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


def _kennung() -> str:
    """Die Korrelations-Kennung dieses Zuges, falls eine anliegt."""

    trace = current_turn_trace()
    return getattr(trace, "turn_id", "-") if trace is not None else "-"


#: Die möglichen Ausgänge einer Weiterleitung.
STATUS_LOKAL = "lokal_beantwortet"
STATUS_AN_MODELL = "an_modell"
STATUS_UNSICHER = "unsicher"


@dataclass
class RouteResult:
    """Ergebnis einer Weiterleitung durch den Task Router.

    ``handled_locally`` allein war zu wenig, und das war der teuerste
    Konstruktionsfehler der Anfrageverarbeitung: Ein einziges Wahr beendete
    den Zug endgültig - ohne Begründung, ohne Angabe, wie sicher die
    Zuordnung war, und ohne Weg zurück. Am 31.08.2026 genügte deshalb das
    Wort „Aufgabe" in „Ich wiederhole die Aufgabe, suche nach einer Wohnung
    und zeige mir die Ergebnisse im Browser an", um die ganze Anfrage in
    eine Aufgabenstatistik zu verwandeln.

    Jetzt trägt das Ergebnis vier weitere Angaben:

    * ``status``: wie es ausgegangen ist (siehe die STATUS_-Konstanten),
    * ``begruendung``: im Klartext, fürs Protokoll,
    * ``konfidenz``: wie sicher sich die zuständige Stelle ist (0.0-1.0),
    * ``rueckfall_erlaubt``: ob die Anfrage bei Zweifeln an das Modell
      weitergereicht werden darf. Handelnde Module (Programm starten,
      Terminal) setzen das nicht - eine ausgeführte Aktion wiederholt man
      nicht. Reine Auskünfte setzen es.

    ``handled_locally`` bleibt als schmale Fassade erhalten, damit die
    bestehenden Aufrufer und Tests unverändert weiterlaufen.
    """

    handled_locally: bool
    response: str = ""
    requires_llm: bool = False
    requires_confirmation: bool = False
    module: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    #: Wie es ausgegangen ist.
    status: str = ""
    #: Warum - im Klartext.
    begruendung: str = ""
    #: Wie sicher sich die zuständige Stelle ist. 1.0 heisst: keine Zweifel.
    konfidenz: float = 1.0
    #: Ob bei Zweifeln an das Modell weitergereicht werden darf.
    rueckfall_erlaubt: bool = False

    @property
    def ist_endgueltig(self) -> bool:
        """Ob dieser Zug hier wirklich zu Ende ist.

        Genau diese Frage stellte vorher niemand: ``handled_locally`` wurde
        als Tatsache gelesen, nicht als Einschätzung.
        """

        return self.handled_locally and self.status != STATUS_UNSICHER

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled_locally": self.handled_locally,
            "response": self.response,
            "requires_llm": self.requires_llm,
            "requires_confirmation": self.requires_confirmation,
            "module": self.module,
            "data": self.data,
            "status": self.status or (
                STATUS_LOKAL if self.handled_locally else STATUS_AN_MODELL
            ),
            "begruendung": self.begruendung,
            "konfidenz": round(self.konfidenz, 2),
            "rueckfall_erlaubt": self.rueckfall_erlaubt,
        }


#: Signatur eines Handlers: erhält Originaltext und Intent-Ergebnis.
RouteHandler = Callable[[str, IntentResult], Awaitable[RouteResult]]


class TaskRouter:
    """Leitet Aufgaben an lokale Module oder an den KI-Provider."""

    def __init__(self, desktop: DesktopControl | None = None) -> None:
        self._desktop = desktop or DesktopControl()
        self._handlers: dict[str, RouteHandler] = {}
        #: Unter dieser Konfidenz beendet eine lokale Auskunft den Zug nicht.
        self._min_konfidenz = float(
            get_config().get("routing.min_konfidenz", 0.4) or 0.4
        )
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

        # Letzte Schutzschranke vor lokalen Systemaktionen. Selbst wenn ein
        # vorgeschalteter oder ein Plugin-Klassifikator den internen Satz
        # "beende den Abschnitt" als APP_CLOSE meldet, ist eine markierte
        # Vorlesung immer eine Modellantwort und niemals Desktop-Steuerung.
        if ist_vorlesungssegment(text):
            return RouteResult(
                handled_locally=False,
                requires_llm=True,
                module="ai_provider",
            )

        handler = self._handlers.get(intent.intent)
        if handler is None:
            return RouteResult(
                handled_locally=False,
                requires_llm=True,
                module="ai_provider",
                status=STATUS_AN_MODELL,
                begruendung=f"fuer Intent '{intent.intent}' ist kein lokales Modul zustaendig",
                konfidenz=float(getattr(intent, "score", 0.0) or 0.0),
            )

        try:
            result = await handler(text, intent)
        except Exception:  # noqa: BLE001 - ein Modulfehler darf den Orb nicht stoppen.
            logger.exception("Fehler im Handler für Intent '%s'.", intent.intent)
            return RouteResult(
                handled_locally=True,
                response="Bei der Ausführung ist ein Fehler aufgetreten. Ich habe die Aktion abgebrochen.",
                module=intent.intent,
            )

        result = self._bewerten(text, intent, result)

        logger.info(
            "[%s] Tor 4 Router: Intent '%s' an Modul '%s' (lokal=%s, "
            "status=%s, Konfidenz %.2f, Rueckfall=%s) - %s",
            _kennung(),
            intent.intent,
            result.module,
            result.handled_locally,
            result.status,
            result.konfidenz,
            result.rueckfall_erlaubt,
            result.begruendung or "ohne weitere Begruendung",
        )
        return result

    def _bewerten(
        self, text: str, intent: IntentResult, result: RouteResult
    ) -> RouteResult:
        """Ergänzt Status, Konfidenz und Begründung - und lässt zurückfallen.

        Die Regel in einem Satz: Eine lokale Zuordnung, die sich selbst
        nicht sicher ist und deren Modul nur Auskunft gibt, darf den Zug
        nicht endgültig beenden.

        Sie greift ausdrücklich NICHT bei Modulen, die etwas getan haben -
        ein gestartetes Programm startet man nicht ein zweites Mal, nur
        weil die Zuordnung knapp war. Solche Handler setzen
        ``rueckfall_erlaubt`` nicht.
        """

        if not result.handled_locally:
            result.status = result.status or STATUS_AN_MODELL
            result.begruendung = result.begruendung or "kein lokales Modul zustaendig"
            return result

        if not result.rueckfall_erlaubt:
            result.status = result.status or STATUS_LOKAL
            result.begruendung = (
                result.begruendung
                or f"Modul '{result.module}' hat abschliessend geantwortet"
            )
            return result

        schwelle = float(self._min_konfidenz)
        if result.konfidenz >= schwelle:
            result.status = STATUS_LOKAL
            result.begruendung = (
                result.begruendung
                or f"lokale Auskunft, Konfidenz {result.konfidenz:.2f} >= {schwelle:.2f}"
            )
            return result

        result.status = STATUS_UNSICHER
        result.handled_locally = False
        result.requires_llm = True
        result.data = {
            **(result.data or {}),
            "verworfene_lokale_antwort": result.response,
            "urspruengliches_modul": result.module,
        }
        result.begruendung = (
            f"Konfidenz {result.konfidenz:.2f} unter {schwelle:.2f} - die "
            f"lokale Auskunft aus '{result.module}' wird nicht als Antwort "
            "genommen, der Hauptweg uebernimmt"
        )
        result.response = ""
        result.module = "ai_provider"
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
