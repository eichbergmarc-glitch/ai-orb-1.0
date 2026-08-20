"""Werkzeugmaschine – lässt das Sprachmodell Werkzeuge benutzen.

Das Verfahren ist bewusst textbasiert. Die Anbieter, mit denen AI-Orb
arbeitet, unterscheiden sich stark darin, ob und wie sie Werkzeugaufrufe
unterstützen – die Claude-Code-Befehlszeile liefert Text, die Messages-API
strukturierte Blöcke, Ollama je nach Modell gar nichts. Ein eigenes
Textprotokoll läuft überall gleich und lässt sich prüfen, ohne dass ein
Anbieter ausgetauscht werden müsste.

Der Ablauf:

1. Die Frage geht mit einer Werkzeugbeschreibung an das Modell.
2. Antwortet das Modell mit einem ``WERKZEUG``-Block, wird er ausgeführt –
   nach Freigabe durch die Sicherheitsschicht.
3. Das Ergebnis geht zurück ans Modell, das damit weiterarbeitet.
4. Das wiederholt sich, bis das Modell ohne Werkzeugaufruf antwortet oder
   die Obergrenze erreicht ist.

Die Obergrenze ist keine Formalie: Ohne sie kann ein Modell in eine
Schleife geraten, in der es dasselbe Werkzeug endlos aufruft. Zusätzlich
wird erkannt, wenn zweimal hintereinander derselbe Aufruf mit denselben
Angaben kommt – dann wird abgebrochen und das offen gesagt.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from backend.config import get_config
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolResult
from backend.tools.registry import ToolRegistry

logger = get_logger(__name__)

#: Wie ein Werkzeugaufruf im Text aussieht.
#: Ein Werkzeugaufruf in einem eingezäunten Block.
#:
#: Deutlich grosszügiger als zuvor, und das ist keine Bequemlichkeit,
#: sondern die Behebung eines Fehlers, den man von aussen nicht sehen
#: konnte: Der Orb benutzte seine Werkzeuge nicht.
#:
#: Vorher stand hier ``r"```(?:werkzeug|tool)\s*\n(.*?)\n```"``. Diese
#: Zeile verlangt dreierlei zugleich - die Zäunung muss genau
#: ``werkzeug`` oder ``tool`` heissen, nach ihr muss ein Zeilenumbruch
#: stehen, und VOR der schliessenden Zäunung ebenfalls. Fehlt eines
#: davon, findet das Muster nichts, der Aufruf wird stillschweigend
#: verworfen, und der Orb antwortet, als habe er nie eines gewollt.
#:
#: Alle drei Abweichungen sind alltäglich. Modelle schreiben ``json``
#: statt ``werkzeug``, sie hängen die schliessende Zäunung an die letzte
#: geschweifte Klammer, sie lassen die Zäunung ganz weg. Nichts davon ist
#: ein Fehler des Modells - es ist ein Fehler, so eng zu lesen.
#:
#: Die Sprachmarke ist jetzt beliebig; was ein Aufruf ist, entscheidet
#: der INHALT (siehe ``_ist_aufruf``) und nicht die Beschriftung.
TOOL_CALL_PATTERN = re.compile(
    r"```[a-zA-Z_]*[ \t]*\r?\n?(.*?)```",
    re.DOTALL,
)

#: Ein Aufruf ohne Codeblock – manche Modelle lassen ihn weg.
BARE_CALL_PATTERN = re.compile(
    r"WERKZEUG\s*:\s*(\{.*?\})",
    re.DOTALL | re.IGNORECASE,
)

#: Die Schlüssel, an denen ein Aufruf zu erkennen ist.
_AUFRUF_SCHLUESSEL = ("werkzeug", "tool")


#: Wendungen, mit denen sich ein Modell um die Werkzeugbenutzung drueckt.
#:
#: Sie zu erkennen aendert nichts am Ablauf - aber sie stehen dann im
#: Protokoll als das, was sie sind. Der Benutzer meldete "der Orb kann auf
#: kein Werkzeug zugreifen"; im Protokoll stand nur "kein Werkzeug
#: aufgerufen". Ob der Orb nicht wollte oder ob er behauptete, nicht zu
#: koennen, war daraus nicht zu lesen - und das sind zwei verschiedene
#: Fehler.
_AUSREDEN: tuple[str, ...] = (
    "kann nicht suchen", "keine suche", "nicht suchen",
    "keinen zugriff", "kein zugriff", "nicht zugreifen",
    "keine internetverbindung", "kein internet", "nicht ins internet",
    "keine werkzeuge", "kein werkzeug zur", "steht mir nicht zur verf",
    "habe keine moeglichkeit", "habe keine möglichkeit",
    "in echtzeit", "wissensstand", "stichtag meines wissens",
    # Der Bildschirm-/Seh-Fall: Der Benutzer bittet den Orb hinzusehen, und
    # er redet sich heraus, statt 'bildschirm_ansehen' zu rufen.
    "nicht anschauen", "nicht ansehen", "nicht ansehe", "nicht analysieren",
    "kann kein video", "kann kein bild", "keinen bildschirm",
    "nicht auswerten", "nicht angemeldet", "nicht aktiviert",
    "kann den bildschirm nicht", "sehe den bildschirm nicht",
    # Dateien/PDF: Seit es ein Schreib- und PDF-Werkzeug gibt, ist auch das
    # eine falsche Ausrede und muss denselben Nachhakweg nehmen.
    "kann kein pdf", "keine pdf erzeug", "kein pdf erzeug",
    "pdf nicht erstellen", "kein werkzeug, das eine pdf",
)


def _klingt_nach_ausrede(text: str) -> bool:
    """Ob die Antwort das Nichtkoennen behauptet, statt es zu tun."""

    knapp = text.lower()
    return any(wendung in knapp for wendung in _AUSREDEN)


def _ausdruecklich_verlangtes_werkzeug(
    messages: list[Any], names: list[str]
) -> str:
    """Erkennt eine ausdrückliche Bitte, ein benanntes Werkzeug zu nutzen."""

    for message in reversed(messages):
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if isinstance(message, dict):
            role = message.get("role")
            content = message.get("content")
        if role != "user":
            continue
        knapp = str(content or "").lower()
        # Natuerliche Auftraege nennen selten den technischen Werkzeugnamen.
        # "Erstelle eine PDF" ist trotzdem genauso eindeutig wie "benutze
        # pdf_erstellen" und darf nicht als freiwillige Option behandelt
        # werden.
        if "pdf" in knapp and any(
            marker in knapp
            for marker in (
                "erstell", "mach", "generier", "speicher", "exportier",
                "anleg", "druck",
            )
        ):
            return "pdf_erstellen"
        if any(marker in knapp for marker in ("such", "recherchier", "schau nach")):
            return "internet_suchen"
        if not any(wort in knapp for wort in ("benutz", "nutz", "verwende", "werkzeug")):
            return ""
        for name in names:
            if name.lower() in knapp:
                return name
        return "passendes Werkzeug" if "werkzeug" in knapp else ""
    return ""


def _ist_aufruf(payload: Any) -> bool:
    """Ob ein gelesenes JSON-Gebilde wirklich ein Werkzeugaufruf ist.

    Nötig, weil die Zäunung jetzt beliebig beschriftet sein darf: Ein
    Modell, das ein Beispiel-JSON zeigt, soll damit kein Werkzeug starten.
    Entschieden wird am Schlüssel, nicht an der Beschriftung.
    """

    return isinstance(payload, dict) and any(
        str(payload.get(schluessel) or "").strip() for schluessel in _AUFRUF_SCHLUESSEL
    )


def _freie_objekte(text: str) -> list[str]:
    """Findet JSON-Objekte im Fliesstext, ohne Zäunung und ohne Vorwort.

    Ein regulärer Ausdruck kann verschachtelte Klammern nicht zuverlässig
    fassen; deshalb wird hier gezählt. Zurückgegeben werden nur Objekte,
    in denen "werkzeug" oder "tool" überhaupt vorkommt - alles andere
    aufzusammeln hiesse, jede Zahlenliste in einer Antwort zu untersuchen.
    """

    gefunden: list[str] = []
    tiefe = 0
    start = -1
    in_text = False
    entwertet = False
    for i, zeichen in enumerate(text):
        if in_text:
            if entwertet:
                entwertet = False
            elif zeichen == "\\":
                entwertet = True
            elif zeichen == '"':
                in_text = False
            continue
        if zeichen == '"':
            in_text = True
        elif zeichen == "{":
            if tiefe == 0:
                start = i
            tiefe += 1
        elif zeichen == "}":
            if tiefe > 0:
                tiefe -= 1
                if tiefe == 0 and start >= 0:
                    stueck = text[start : i + 1]
                    if any(f'"{s}"' in stueck for s in _AUFRUF_SCHLUESSEL):
                        gefunden.append(stueck)
                    start = -1

    # Ein Objekt, das nie zuging - die abgeschnittene Antwort.
    #
    # Genau das stand im Protokoll des Benutzers:
    #
    #   {"werkzeug": "internet_suchen", "argumente": {"suchbegriff": "Iran"}
    #
    # Eine schliessende Klammer fehlt, und weil hier nur VOLLSTAENDIGE
    # Objekte eingesammelt wurden, kam der Aufruf nie bis zum Leser. Der
    # Rest wird mitgenommen und unten repariert; ist er unbrauchbar, faellt
    # er dort wieder heraus.
    if tiefe > 0 and start >= 0:
        rest = text[start:]
        if any(f'"{s}"' in rest for s in _AUFRUF_SCHLUESSEL):
            gefunden.append(rest)
    return gefunden


def _json_reparieren(text: str) -> dict[str, Any] | None:
    """Repariert die kleinen Schreibfehler, mit denen Modelle JSON verderben.

    Bewusst KONSERVATIV: Es wird nur behoben, was eindeutig ist - fehlende
    Kommas zwischen Feldern, fehlende schliessende Klammern, ein Komma zu
    viel am Ende, Python-Schreibweisen (True/False/None). Alles, was ein
    Raten waere, bleibt liegen; ein falsch geratener Aufruf ist schlimmer
    als ein nicht ausgefuehrter.

    Returns:
        Das gelesene Objekt oder ``None``, wenn es sich nicht sicher
        herstellen liess.
    """

    kandidat = text.strip()
    if not kandidat.startswith("{"):
        return None

    versuche: list[str] = []

    # 1. Python-Schreibweisen, die Modelle gern einstreuen.
    ersetzt = re.sub(r"\bTrue\b", "true", kandidat)
    ersetzt = re.sub(r"\bFalse\b", "false", ersetzt)
    ersetzt = re.sub(r"\bNone\b", "null", ersetzt)
    versuche.append(ersetzt)

    # 2. Fehlendes Komma zwischen zwei Feldern. Nur dort, wo ein Feldname
    #    folgt - sonst wuerde in Fliesstext eingegriffen.
    mit_komma = re.sub(r'("\s*)\n?(\s*")(?=[^"]*"\s*:)', r"\1,\2", ersetzt)
    mit_komma = re.sub(r'([}\]])(\s*")(?=[^"]*"\s*:)', r"\1,\2", mit_komma)
    versuche.append(mit_komma)

    # 3. Ein Komma zu viel vor der schliessenden Klammer.
    ohne_letztes = re.sub(r",(\s*[}\]])", r"\1", mit_komma)
    versuche.append(ohne_letztes)

    # 4. Fehlende schliessende Klammern anhaengen (abgeschnittene Antwort).
    for basis in (ohne_letztes, mit_komma, ersetzt):
        offen_geschweift = basis.count("{") - basis.count("}")
        offen_eckig = basis.count("[") - basis.count("]")
        if offen_geschweift > 0 or offen_eckig > 0:
            versuche.append(
                basis + ("]" * max(0, offen_eckig)) + ("}" * max(0, offen_geschweift))
            )

    for versuch in versuche:
        try:
            gelesen = json.loads(versuch)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(gelesen, dict):
            return gelesen
    return None


@dataclass
class ToolCall:
    """Ein vom Modell gewünschter Werkzeugaufruf."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def signature(self) -> str:
        """Kennung zum Erkennen von Wiederholungen."""

        return self.tool + "|" + json.dumps(self.arguments, sort_keys=True, default=str)


@dataclass
class ToolRun:
    """Was bei einem Aufruf geschehen ist – für die Transparenzansicht."""

    tool: str
    arguments: dict[str, Any]
    result: ToolResult
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": self.result.ok,
            "output": self.result.output[:500],
            "error": self.result.error,
            "seconds": round(self.seconds, 3),
        }


@dataclass
class ToolLoopResult:
    """Das Ergebnis der gesamten Werkzeugschleife."""

    answer: str = ""
    runs: list[ToolRun] = field(default_factory=list)
    rounds: int = 0
    stopped_because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "runs": [run.to_dict() for run in self.runs],
            "rounds": self.rounds,
            "stopped_because": self.stopped_because,
        }


def parse_tool_calls(text: str) -> list[ToolCall]:
    """Liest Werkzeugaufrufe aus einer Modellantwort.

    Fehlerhafte Blöcke werden übergangen statt zu einem Absturz zu führen –
    ein Modell, das ein Komma vergisst, soll die Antwort nicht zerstören.
    """

    calls: list[ToolCall] = []
    seen: set[str] = set()

    rohlinge: list[str] = []
    for pattern in (TOOL_CALL_PATTERN, BARE_CALL_PATTERN):
        rohlinge.extend(match.group(1).strip() for match in pattern.finditer(text))
    # Und zuletzt der ungezäunte Fall. Er läuft über den ganzen Text, also
    # auch über das, was schon gefunden wurde - doppelte Aufrufe fallen
    # unten über ihre Signatur wieder heraus.
    rohlinge.extend(_freie_objekte(text))

    for raw in rohlinge:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Erst reparieren, dann aufgeben.
            #
            # Vorher wurde hier nur gemeldet und weggeworfen - und im
            # Protokoll des Benutzers steht, was das kostet:
            #
            #   {"werkzeug": "rechnen" "argumente": {}}          (Komma fehlt)
            #   {"werkzeug": "internet_suchen", "argumente": {...   (Klammer fehlt)
            #
            # Beide Aufrufe waren inhaltlich vollstaendig und eindeutig; nur
            # ein Zeichen fehlte. Das Werkzeug wurde trotzdem nicht
            # ausgefuehrt, und von aussen sah das aus, als koenne der Orb
            # seine Werkzeuge nicht benutzen.
            payload = _json_reparieren(raw)
            if payload is None:
                if any(f'"{s}"' in raw for s in _AUFRUF_SCHLUESSEL):
                    logger.warning(
                        "Ein Werkzeugaufruf war kein gueltiges JSON und liess "
                        "sich auch nicht reparieren: %s", raw[:200]
                    )
                continue
            logger.info(
                "Ein fehlerhafter Werkzeugaufruf wurde repariert: %s", raw[:120]
            )

        if not _ist_aufruf(payload):
            continue

        name = str(payload.get("werkzeug") or payload.get("tool") or "")
        if not name:
            continue

        arguments = (
            payload.get("argumente")
            or payload.get("arguments")
            or payload.get("input")
            or {}
        )
        if not isinstance(arguments, dict):
            arguments = {}

        call = ToolCall(tool=name.strip(), arguments=arguments)
        if call.signature() in seen:
            continue
        seen.add(call.signature())
        calls.append(call)

    return calls


def strip_tool_calls(text: str) -> str:
    """Entfernt Werkzeugblöcke aus einem Text.

    Der Benutzer soll die Antwort lesen, nicht die Maschinerie dahinter.

    Entfernt wird jetzt gezielt und nicht mehr pauschal. Vorher wurde jeder
    Treffer der Zäunungsmuster gelöscht - das ging, solange nur
    ``werkzeug`` und ``tool`` als Beschriftung galten. Seit die
    Beschriftung beliebig sein darf, wäre dieselbe Zeile eine Katastrophe:
    Sie löschte JEDEN eingezäunten Block, also auch das Stück Python, um
    das der Benutzer gerade gebeten hat.

    Deshalb wird hier geprüft, ob im Block wirklich ein Aufruf steht.
    """

    def _weg(match: "re.Match[str]") -> str:
        inhalt = match.group(1).strip()
        try:
            payload = json.loads(inhalt)
        except json.JSONDecodeError:
            return match.group(0)
        return "" if _ist_aufruf(payload) else match.group(0)

    ohne_bloecke = TOOL_CALL_PATTERN.sub(_weg, text)
    ohne_praefix = BARE_CALL_PATTERN.sub(_weg, ohne_bloecke)

    # Und die ungezäunten Objekte.
    rest = ohne_praefix
    for stueck in _freie_objekte(rest):
        try:
            if _ist_aufruf(json.loads(stueck)):
                rest = rest.replace(stueck, "")
        except json.JSONDecodeError:
            continue

    return re.sub(r"\n{3,}", "\n\n", rest).strip()


#: Die Berechtigungen, bei denen ein Klang ertönt.
#:
#: Die Trennlinie verläuft zwischen Reden und Handeln, nicht zwischen
#: harmlos und gefährlich. Eine Datei zu lesen ist Teil der Antwort; ein
#: Programm zu starten, etwas zu installieren, einen Befehl abzusetzen oder
#: eine Datei zu schreiben verändert den Rechner. Nur Letzteres bekommt
#: einen Klang – sonst begleitete ein Ton jede zweite Antwort und wäre
#: nach einem Tag keine Auskunft mehr, sondern Geräusch.
HANDELNDE_RECHTE = frozenset(
    {
        "launch_application",
        "install_dependencies",
        "system_commands",
        "write_files",
        "modify_own_code",
    }
)


def _klang_zur_tat() -> None:
    """Spielt den Tat-Klang – und lässt nichts daran scheitern."""

    try:
        from backend.audio.sounds import klaenge

        klaenge().tat()
    except Exception:  # noqa: BLE001 - ein Signalton darf nie ein Werkzeug aufhalten.
        logger.debug("Der Tat-Klang ließ sich nicht abspielen.", exc_info=True)


#: Werkzeuge, deren Ergebnis ein GELESENER Text ist und nicht eine
#: Handlung. Nur deren Ausgabe wandert ins Gedaechtnis - ein "Datei
#: geloescht" oder "Fenster geoeffnet" waere dort nur Ballast.
_LESENDE_WERKZEUGE: frozenset[str] = frozenset({
    "datei_lesen", "dokument_lesen", "pdf_lesen", "webseite_lesen",
    "bildschirm_ansehen", "datei_zusammenfassen", "ordner_lesen",
})


class ToolEngine:
    """Führt die Werkzeugschleife aus."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        security: SecurityEngine,
        provider_manager: Any,
        event_bus: Any | None = None,
    ) -> None:
        """
        Args:
            registry: Die verfügbaren Werkzeuge.
            security: Für die Freigabe vor jeder Ausführung.
            provider_manager: Liefert die Modellantworten.
        """

        config = get_config()

        self._registry = registry
        self._security = security
        self._providers = provider_manager
        self._event_bus = event_bus

        self._enabled = bool(config.get("tools.enabled", True))
        self._max_rounds = int(config.get("tools.max_rounds", 4))
        self._max_output_characters = int(config.get("tools.max_output_characters", 4000))

        self._total_calls = 0
        self._failed_calls = 0

        #: Wohin gelesene Inhalte zum Behalten gehen.
        #:
        #: Gesetzt wird das von der Laufzeit (siehe runtime). Ohne diesen
        #: Anschluss war die Klage des Benutzers woertlich zutreffend: "Er
        #: speichert eingelesene Dokumente nicht in seinem Gedaechtnis ab."
        #: Was 'datei_lesen' oder 'webseite_lesen' holte, ging in den
        #: Kontext DIESER einen Antwort und war danach weg.
        self.gelesenes_behalten: Callable[[str, str], None] | None = None

    @property
    def enabled(self) -> bool:
        """Ob Werkzeuge benutzt werden dürfen."""

        return self._enabled and bool(self._registry.all())

    # --- Anweisung an das Modell ---------------------------------------------------

    def system_instructions(self) -> str:
        """Erklärt dem Modell, wie es Werkzeuge aufruft."""

        if not self.enabled:
            return ""

        return (
            "Dir stehen Werkzeuge zur Verfügung. Benutze sie immer dann, wenn "
            "du etwas nicht selbst wissen kannst – etwa Datum und Uhrzeit, den "
            "Inhalt einer Datei oder ein Rechenergebnis. Rate nicht.\n\n"
            "So rufst du ein Werkzeug auf – nichts anderes in diese Antwort "
            "schreiben:\n\n"
            "```werkzeug\n"
            '{"werkzeug": "name", "argumente": {"feld": "wert"}}\n'
            "```\n\n"
            "Du bekommst das Ergebnis und antwortest dann dem Benutzer in "
            "normaler Sprache. Erwähne die Werkzeuge dabei nicht – der "
            "Benutzer will die Antwort, nicht den Weg dorthin.\n\n"
            "Diese Werkzeuge gibt es:\n"
            + self._registry.describe_for_model()
            + "\n\n"
            + self.VERBINDLICHE_REGEL
        )

    #: Die Regel, die NACH der Werkzeugliste steht.
    #:
    #: Die Stellung ist der ganze Punkt. Vorher stand die Aufforderung
    #: "benutze Werkzeuge" ganz oben, gefolgt von vierzehntausend Zeichen
    #: alphabetischem Verzeichnis. Das Letzte, was das Modell vor der Frage
    #: des Benutzers las, war die Parameterbeschreibung des neununddreissigsten
    #: Werkzeugs - und nicht die Anweisung.
    #:
    #: Im Protokoll war genau das zu sehen: Auf "Suche ueberall nach
    #: aktuellen Informationen und fasse mir die News zusammen" antwortete
    #: der Orb 544 Zeichen aus dem Gedaechtnis, ohne einen einzigen Aufruf.
    #:
    #: Der zweite Punkt ist der Widerspruch zur Kuerze. Gesprochenen
    #: Antworten wird vorgegeben, sich auf zwei bis vier Saetze zu
    #: beschraenken. Ein Werkzeugaufruf sieht wie ein Verstoss dagegen aus -
    #: bis jemand dazusagt, dass er keine Antwort ist, sondern der Weg zu
    #: einer.
    VERBINDLICHE_REGEL = (
        "SO ENTSCHEIDEST DU - das ist verbindlich und geht allem anderen vor:\n\n"
        "Dein Wissen hat einen Stichtag. Alles, was sich seither geaendert "
        "haben koennte, weisst du nicht: Nachrichten, laufende Ereignisse und "
        "Kriege, Preise, Wetter, Spielstaende, wer gerade ein Amt innehat, "
        "was eine Firma diese Woche angekuendigt hat. Bei so etwas rufst du "
        "ZUERST 'internet_suchen' auf und antwortest ERST DANACH. Nicht "
        "raten, nicht aus dem Gedaechtnis zusammenfassen, nicht mit dem "
        "Wissensstand entschuldigen.\n\n"
        "Sagt der Benutzer 'such', 'schau nach', 'recherchiere' oder 'was "
        "gibt es Neues', ist das eine Anweisung und keine Gespraechsfloskel. "
        "Ihr folgst du.\n\n"
        "Nach der Suche liest du den brauchbarsten Treffer mit "
        "'webseite_lesen'. Eine Trefferliste ist keine Antwort.\n\n"
        "Verlangt der Benutzer eine PDF, lieferst du nicht bloss den Text "
        "oder eine Anleitung zum manuellen Drucken: Du erstellst den "
        "vollstaendigen Inhalt und rufst danach 'pdf_erstellen' auf. Erst "
        "wenn das Werkzeug den gespeicherten Pfad bestaetigt, ist der "
        "Auftrag erledigt.\n\n"
        "Du hast Zugang zum Netz. Sage nie, du koenntest nicht ins Internet "
        "oder habest keinen Zugriff auf ein Werkzeug - du hast ihn. Geht "
        "etwas schief, meldet dir das Werkzeug selbst, woran es lag.\n\n"
        "Eine Vorgabe zur Kuerze gilt fuer die ANTWORT an den Benutzer, "
        "nicht fuer den Weg dorthin. Ein Werkzeugaufruf ist keine Antwort, "
        "sondern ein Zwischenschritt - er zaehlt gegen keine Laengengrenze."
    )

    # --- Ausführung ------------------------------------------------------------------

    async def run(
        self,
        question: str,
        *,
        system_prompt: str = "",
        actor: str = "tools",
    ) -> ToolLoopResult:
        """Beantwortet eine Frage und benutzt dabei Werkzeuge.

        Args:
            question: Die Frage des Benutzers.
            system_prompt: Der Systemprompt der Unterhaltung.
            actor: Wer die Werkzeuge benutzt – für das Prüfprotokoll.

        Returns:
            Antwort und Protokoll der Aufrufe.
        """

        outcome = ToolLoopResult()

        if not self.enabled:
            outcome.answer = await self._ask_model(question, system_prompt)
            outcome.stopped_because = "Werkzeuge sind ausgeschaltet."
            return outcome

        combined_system = "\n\n".join(
            part for part in (system_prompt, self.system_instructions()) if part
        )

        transcript = question
        last_signature = ""

        for round_number in range(1, self._max_rounds + 1):
            outcome.rounds = round_number

            reply = await self._ask_model(transcript, combined_system)
            calls = parse_tool_calls(reply)

            if not calls:
                outcome.answer = strip_tool_calls(reply)
                outcome.stopped_because = "Das Modell hat ohne Werkzeug geantwortet."
                return outcome

            results: list[str] = []
            for call in calls:
                if call.signature() == last_signature:
                    outcome.stopped_because = (
                        "Das Modell hat denselben Aufruf wiederholt – abgebrochen."
                    )
                    outcome.answer = strip_tool_calls(reply) or (
                        "Ich komme hier nicht weiter, ohne mich im Kreis zu drehen."
                    )
                    return outcome
                last_signature = call.signature()

                run = await self._execute(call, actor)
                outcome.runs.append(run)

                if run.result.ok:
                    output = run.result.output[: self._max_output_characters]
                    results.append(f"Ergebnis von {call.tool}:\n{output}")
                else:
                    results.append(f"{call.tool} ist fehlgeschlagen: {run.result.error}")

            transcript = (
                f"{transcript}\n\n"
                + "\n\n".join(results)
                + "\n\nBeantworte damit jetzt die ursprüngliche Frage in normaler "
                "Sprache. Rufe nur dann noch ein Werkzeug auf, wenn dir wirklich "
                "etwas fehlt."
            )

        # Obergrenze erreicht: eine letzte Antwort ohne Werkzeuge erzwingen.
        outcome.stopped_because = (
            f"Nach {self._max_rounds} Runden abgebrochen, damit es nicht endlos wird."
        )
        final = await self._ask_model(
            transcript + "\n\nAntworte jetzt abschließend, ohne weiteres Werkzeug.",
            system_prompt,
        )
        outcome.answer = strip_tool_calls(final)
        return outcome

    async def direkt_ausfuehren(
        self, name: str, arguments: dict[str, Any], *, actor: str = "vorab"
    ) -> ToolRun:
        """Führt ein Werkzeug aus, ohne das Modell zu fragen.

        Gedacht für den Fall, in dem die Entscheidung schon feststeht und
        nur noch die Ausführung fehlt - etwa die Suche bei einer Frage
        nach etwas Aktuellem. Prüfung, Freigabe und Prüfprotokoll laufen
        genau wie sonst; es entfällt allein das Überreden.
        """

        return await self._execute(ToolCall(tool=name, arguments=arguments), actor)

    async def continue_with_tools(
        self,
        messages: list[Any],
        first_reply: str,
        *,
        actor: str = "gespraech",
        preexecuted: dict[str, str] | None = None,
    ) -> tuple[str, list[ToolRun]]:
        """Führt Werkzeugaufrufe aus einer bereits erhaltenen Antwort aus.

        Der Unterschied zu :meth:`run`: Hier bleibt der ganze
        Gesprächsverlauf erhalten. Der Orchestrator hat das Modell bereits
        mit Verlauf und Gedächtnis gefragt; enthält die Antwort
        Werkzeugaufrufe, werden sie hier ausgeführt und das Modell bekommt
        die Ergebnisse als Fortsetzung desselben Gesprächs – nicht als
        frische Einzelfrage, die den Zusammenhang verlöre.

        Args:
            messages: Die Nachrichten, mit denen das Modell gefragt wurde.
            first_reply: Die erste Antwort des Modells.
            actor: Wer die Werkzeuge benutzt – für das Prüfprotokoll.

        Returns:
            Die endgültige Antwort (ohne Werkzeug-Blöcke) und die Liste
            der ausgeführten Aufrufe.
        """

        text = first_reply
        runs: list[ToolRun] = []
        last_signature = ""
        history = list(messages)
        nachgehakt = False
        bereits = dict(preexecuted or {})

        for _round in range(self._max_rounds):
            calls = parse_tool_calls(text) if self.enabled else []
            if calls and bereits:
                doppelte = [call for call in calls if call.tool in bereits]
                calls = [call for call in calls if call.tool not in bereits]
                if doppelte:
                    logger.info(
                        "Bereits vorab ausgefuehrte Werkzeuge nicht wiederholt: %s",
                        ", ".join(sorted({call.tool for call in doppelte})),
                    )
                    # Besteht die Antwort nur aus dem wiederholten Aufruf,
                    # ist das vorab beschaffte Ergebnis selbst bereits die
                    # passende Antwort. Es erneut durch dasselbe Werkzeug und
                    # danach noch einmal durchs Modell zu schicken, verdoppelt
                    # nur die Wartezeit und kann den Befund sogar veraendern.
                    if not calls:
                        normaler_text = strip_tool_calls(text).strip()
                        if len(normaler_text) >= 40:
                            return normaler_text, runs
                        antworten = [
                            bereits[call.tool].strip()
                            for call in doppelte
                            if bereits.get(call.tool, "").strip()
                        ]
                        if antworten:
                            return "\n\n".join(dict.fromkeys(antworten)), runs
            if not calls:
                # Auch das Ausbleiben gehoert ins Protokoll.
                #
                # Ohne diese Zeile sieht "das Modell wollte kein Werkzeug"
                # genauso aus wie "wir haben seinen Aufruf nicht gelesen" -
                # naemlich wie gar nichts. Die beiden auseinanderzuhalten
                # war der halbe Weg zur Behebung, und beim naechsten Mal
                # soll er nicht wieder bei null anfangen.
                if not runs:
                    # Mit Anfang der Antwort, nicht nur mit ihrer Laenge.
                    #
                    # Die blosse Zahl beantwortet die entscheidende Frage
                    # nicht: Hat das Modell die Frage aus dem Gedaechtnis
                    # beantwortet - oder hat es gesagt, es KOENNE nicht
                    # suchen? Das sind zwei verschiedene Fehler mit zwei
                    # verschiedenen Ursachen, und ohne den Wortlaut sind
                    # sie nicht zu unterscheiden.
                    logger.info(
                        "Das Modell hat kein Werkzeug aufgerufen (%d Zeichen): %s",
                        len(text),
                        text[:220].replace("\n", " | "),
                    )
                    # Zweites, haeufigeres Signal: Das Modell NENNT ein
                    # Werkzeug beim Namen ("ich koennte 'bildschirm_ansehen'
                    # nutzen"), ruft es aber nicht auf. Genau das stand im
                    # Protokoll des Benutzers - der Orb "kennt" seine Werkzeuge,
                    # redet darueber, und benutzt sie doch nicht. Wer ein
                    # Werkzeug beim Namen nennt, haette es rufen sollen.
                    nennt_werkzeug = any(
                        name and name in text for name in self._registry.names()
                    )
                    verlangt = _ausdruecklich_verlangtes_werkzeug(
                        history, self._registry.names()
                    )
                    if (
                        _klingt_nach_ausrede(text) or nennt_werkzeug or verlangt
                    ) and not nachgehakt:
                        # EINMAL nachhaken, statt die Ausrede weiterzureichen.
                        #
                        # Das war die wiederkehrende Klage "die Werkzeuge gehen
                        # nicht": Sie gingen (Suche und Browser liefen im selben
                        # Protokoll) - das Modell griff nur nicht danach, sondern
                        # sagte, es koenne nicht, oder es sprach ueber das
                        # Werkzeug, ohne es zu rufen. Genau hier wird es einmal
                        # bestimmt aufgefordert, das passende Werkzeug wirklich
                        # zu rufen. Nur einmal (``nachgehakt``), damit daraus
                        # keine Schleife wird.
                        nachgehakt = True
                        logger.warning(
                            "Das Modell hat ein Werkzeug nicht benutzt, obwohl "
                            "es angebracht war (Ausrede oder nur benannt). Ich "
                            "hake einmal nach."
                        )
                        from backend.orchestrator.providers.base_provider import (
                            ChatMessage,
                        )

                        history = history + [
                            ChatMessage(role="assistant", content=text),
                            ChatMessage(
                                role="user",
                                content=(
                                    "Doch - du HAST Werkzeuge, sie stehen oben im "
                                    "Systemprompt (unter anderem bildschirm_ansehen, "
                                    "bildschirm_lesen, internet_suchen, "
                                    "webseite_lesen, pdf_erstellen, "
                                    "browser_bedienen). Braucht die "
                                    "Aufgabe eines davon, dann RUFE es im "
                                    "vorgesehenen Format auf, statt zu sagen, du "
                                    "koennest nicht. Willst du sehen, was gerade auf "
                                    "dem Bildschirm oder in einem Video zu sehen ist, "
                                    "nimm bildschirm_ansehen (es macht ein Standbild "
                                    "und wertet es aus). Nur wenn wirklich kein "
                                    "Werkzeug passt, antworte ohne eines. "
                                    + (
                                        f"Der Benutzer hat ausdrücklich '{verlangt}' "
                                        "verlangt; ignoriere das nicht."
                                        if verlangt else ""
                                    )
                                ),
                            ),
                        ]
                        try:
                            response = await self._providers.chat(history)
                            text = getattr(response, "text", str(response))
                            continue
                        except Exception:  # noqa: BLE001 - Nachhaken darf nicht reissen.
                            logger.exception("Das Nachhaken beim Modell ist fehlgeschlagen.")
                    if _klingt_nach_ausrede(text):
                        logger.warning(
                            "Die Antwort behauptet weiterhin, kein Werkzeug "
                            "benutzen zu koennen - die Werkzeuge sind aber "
                            "angemeldet und stehen im Systemprompt. Das ist ein "
                            "Fehler des Modells, nicht der Anbindung."
                        )
                return strip_tool_calls(text), runs

            results: list[str] = []
            for call in calls:
                if call.signature() == last_signature:
                    # Derselbe Aufruf zweimal hintereinander führt nirgendwohin.
                    answer = strip_tool_calls(text) or (
                        "Ich komme hier nicht weiter, ohne mich im Kreis zu drehen."
                    )
                    return answer, runs
                last_signature = call.signature()

                run = await self._execute(call, actor)
                runs.append(run)

                if run.result.ok:
                    output = run.result.output[: self._max_output_characters]
                    results.append(f"Ergebnis von {call.tool}:\n{output}")
                else:
                    results.append(f"{call.tool} ist fehlgeschlagen: {run.result.error}")

            # Dieselbe Nachrichtenform wie der übrige Verlauf – die
            # Provider erwarten ChatMessage-Objekte, keine Wörterbücher.
            from backend.orchestrator.providers.base_provider import ChatMessage

            history = history + [
                ChatMessage(role="assistant", content=text),
                ChatMessage(
                    role="user",
                    content=(
                        "\n\n".join(results)
                        + "\n\nBeantworte damit jetzt die ursprüngliche Frage in "
                        "normaler Sprache, ohne die Werkzeuge zu erwähnen. Rufe "
                        "nur dann noch ein Werkzeug auf, wenn dir wirklich etwas "
                        "fehlt."
                    ),
                ),
            ]

            try:
                response = await self._providers.chat(history)
            except Exception as error:  # noqa: BLE001 - lieber Teilergebnis als Absturz.
                logger.exception("Das Sprachmodell hat in der Werkzeugschleife nicht geantwortet.")
                return (
                    "Ich habe die Ergebnisse beschafft, aber die Antwort darauf "
                    f"ist fehlgeschlagen: {error}"
                ), runs
            text = getattr(response, "text", str(response))

        return strip_tool_calls(text), runs

    async def _execute(self, call: ToolCall, actor: str) -> ToolRun:
        """Führt einen einzelnen Aufruf aus – nach Prüfung und Freigabe."""

        started = time.perf_counter()
        self._total_calls += 1

        tool = self._registry.get(call.tool)
        if tool is None:
            self._failed_calls += 1
            return ToolRun(
                call.tool,
                call.arguments,
                ToolResult.failure(
                    f"Das Werkzeug '{call.tool}' gibt es nicht. Verfügbar sind: "
                    + ", ".join(self._registry.names())
                ),
                time.perf_counter() - started,
            )

        valid, problem, cleaned = tool.validate(call.arguments)
        if not valid:
            self._failed_calls += 1
            return ToolRun(
                tool.name,
                call.arguments,
                ToolResult.failure(problem),
                time.perf_counter() - started,
            )

        decision = await self._security.require(
            actor,
            tool.permission,
            self._describe_intent(tool, cleaned),
            context={"tool": tool.name, "arguments": cleaned},
        )

        if not decision.allowed:
            self._failed_calls += 1
            return ToolRun(
                tool.name,
                cleaned,
                ToolResult.failure(f"Nicht ausgeführt: {decision.reason}"),
                time.perf_counter() - started,
            )

        # Was den Rechner verändert, soll man hören.
        #
        # Nicht jedes Werkzeug: Die Uhrzeit abzulesen oder zu rechnen sind
        # Teile des Gesprächs, und ein Klang dafür wäre bald nur noch
        # Lärm. Ein Programm zu starten oder eine Seite zu öffnen ist etwas
        # anderes – da geschieht etwas auf dem Bildschirm, und wer gerade
        # wegsieht, soll trotzdem mitbekommen, dass es der Orb war.
        if tool.permission in HANDELNDE_RECHTE:
            _klang_zur_tat()

        # Keine Argumente in Ereigniskennungen: Darin könnten Dateinamen,
        # Suchtexte oder andere private Inhalte stehen. Eine lokale laufende
        # Nummer genügt, um Start und Ende zuzuordnen.
        task_id = f"tool-{self._total_calls}"
        if self._event_bus is not None:
            await self._event_bus.publish(
                "task.started", {"id": task_id, "label": tool.name, "progress": 0.0}
            )
        try:
            result = await tool.execute(cleaned)
        except Exception as error:  # noqa: BLE001 - ein Werkzeug darf nichts abbrechen.
            logger.exception("Das Werkzeug '%s' ist abgestürzt.", tool.name)
            result = ToolResult.failure(f"Das Werkzeug ist abgestürzt: {error}")

        if not result.ok:
            self._failed_calls += 1

        if self._event_bus is not None:
            await self._event_bus.publish(
                "task.finished",
                {
                    "id": task_id,
                    "label": tool.name,
                    "progress": 1.0,
                    "ok": result.ok,
                },
            )

        # Jeder Werkzeugeinsatz ins Protokoll, und zwar sichtbar.
        #
        # Bisher stand davon nichts drin - nur ein DEBUG-Eintrag, wenn ein
        # Werkzeugblock kein gueltiges JSON war. Damit war die wichtigste
        # Frage bei jeder Stoerung nicht zu beantworten: Hat der Orb das
        # Werkzeug ueberhaupt benutzt?
        #
        # Genau daran ist die Suche nach "der Orb kann nicht mehr aufs
        # Internet" haengengeblieben. Im Protokoll stand, welche Strategie
        # gewaehlt wurde und dass eine Antwort kam - ob dazwischen gesucht
        # wurde, ob die Suche scheiterte oder ob sie nie versucht wurde,
        # war nicht zu sehen. Drei sehr verschiedene Fehler, ein einziges
        # Bild.
        dauer = time.perf_counter() - started
        if result.ok and tool.name in _LESENDE_WERKZEUGE and self.gelesenes_behalten:
            # Was gelesen wurde, soll der Orb morgen noch wissen.
            with contextlib.suppress(Exception):
                self.gelesenes_behalten(
                    str(result.output or ""),
                    self._quelle_nennen(tool.name, cleaned),
                )
        if result.ok:
            logger.info(
                "Werkzeug '%s' ausgefuehrt (%.1f s): %s",
                tool.name,
                dauer,
                str(result.output)[:160].replace("\n", " | "),
            )
        else:
            logger.warning(
                "Werkzeug '%s' fehlgeschlagen (%.1f s): %s",
                tool.name,
                dauer,
                result.error or "ohne Angabe",
            )

        self._security.record_action(
            actor,
            tool.permission,
            self._describe_intent(tool, cleaned),
            succeeded=result.ok,
            context={"tool": tool.name},
        )

        return ToolRun(tool.name, cleaned, result, time.perf_counter() - started)

    @staticmethod
    def _quelle_nennen(werkzeug: str, argumente: dict[str, Any]) -> str:
        """Woher der gelesene Text stammt - fuer den Nachweis im Gedaechtnis.

        Ohne Quelle ist ein Auszug im Gedaechtnis wertlos: Man weiss dann,
        DASS etwas dastand, aber nicht, wo man es nachlesen kann. Und
        Seiten aendern sich - der Verweis ist oft mehr wert als der Text.
        """

        for schluessel in ("url", "pfad", "datei", "adresse", "dateiname"):
            wert = argumente.get(schluessel)
            if wert:
                return str(wert)
        return werkzeug

    @staticmethod
    def _describe_intent(tool: Tool, arguments: dict[str, Any]) -> str:
        """Beschreibt im Klartext, was geschehen soll.

        Diese Zeile bekommt der Benutzer im Zustimmungsdialog zu sehen. Sie
        muss ohne Fachwissen verständlich sein.
        """

        if not arguments:
            return tool.description

        details = ", ".join(f"{key}: {value}" for key, value in arguments.items())
        return f"{tool.description} ({details})"

    async def _ask_model(self, prompt: str, system_prompt: str) -> str:
        """Stellt eine Frage an das Sprachmodell."""

        try:
            response = await self._providers.complete(prompt, system_prompt=system_prompt)
        except Exception as error:  # noqa: BLE001
            logger.exception("Das Sprachmodell hat nicht geantwortet.")
            return f"Das Sprachmodell hat nicht geantwortet: {error}"

        if isinstance(response, str):
            return response
        for attribute in ("text", "content", "answer"):
            value = getattr(response, attribute, None)
            if isinstance(value, str):
                return value
        if isinstance(response, dict):
            for key in ("text", "content", "answer"):
                value = response.get(key)
                if isinstance(value, str):
                    return value
        return str(response)

    # --- Auskunft ---------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "enabled": self.enabled,
            "configured": self._enabled,
            "tools": self._registry.names(),
            "max_rounds": self._max_rounds,
            "total_calls": self._total_calls,
            "failed_calls": self._failed_calls,
        }
