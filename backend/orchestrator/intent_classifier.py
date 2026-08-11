"""Intent-Klassifikation für eingehende Benutzeranfragen.

Die Klassifikation arbeitet vollständig lokal und ohne Sprachmodell: Sie
basiert auf gewichteten Schlüsselwort- und Mustervergleichen. Dadurch kann
der Orchestrator bereits vor jeder Modellanfrage entscheiden, ob überhaupt
ein LLM benötigt wird (z. B. "Öffne Firefox" braucht keines).

Neue Intents lassen sich über :meth:`IntentClassifier.register_intent`
ergänzen, ohne den Kern zu verändern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.utils.text import tokenize

#: Alle Basis-Intents gemäß Architekturvorgabe.
CHAT = "chat"
QUESTION = "frage_beantworten"
FILE_SEARCH = "datei_suchen"
APP_START = "programm_starten"
APP_CLOSE = "programm_schliessen"
TERMINAL = "terminal"
CALENDAR = "kalender"
REMINDER = "erinnerung"
BROWSER = "browser"
MUSIC = "musik"
SETTINGS = "einstellungen"
DESKTOP_CONTROL = "desktopsteuerung"
PLUGIN = "plugin"
SYSTEM_STATUS = "systemstatus"
SMALL_TALK = "small_talk"
RESEARCH = "recherche"
CODING = "programmierung"
HISTORY = "geschichtswissenschaft"
PROJECT = "projekt"
TASK = "aufgabe"
TRANSPARENCY = "transparenz"
DOCUMENT = "dokument"
UNKNOWN = "unbekannt"


@dataclass
class IntentDefinition:
    """Definition eines Intents.

    Attributes:
        name: Eindeutiger Name des Intents.
        keywords: Schlüsselwörter, die für diesen Intent sprechen.
        patterns: Reguläre Ausdrücke für typische Formulierungen.
        requires_llm: Ob dieser Intent grundsätzlich ein Sprachmodell
            benötigt. Entscheidend für die Frage "braucht diese Aufgabe
            überhaupt ein LLM?".
        weight: Grundgewicht des Intents bei Gleichstand.
    """

    name: str
    keywords: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    requires_llm: bool = True
    weight: float = 1.0


@dataclass
class IntentResult:
    """Ergebnis der Intent-Klassifikation."""

    intent: str
    confidence: str
    score: float
    requires_llm: bool
    matched_keywords: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "score": round(self.score, 3),
            "requires_llm": self.requires_llm,
            "matched_keywords": self.matched_keywords,
            "entities": self.entities,
        }


_DEFAULT_INTENTS: list[IntentDefinition] = [
    IntentDefinition(
        APP_START,
        keywords=["öffne", "starte", "start", "öffnen", "starten", "führe aus", "run"],
        patterns=[r"\b(öffne|starte|start)\s+\w+"],
        requires_llm=False,
        weight=1.3,
    ),
    IntentDefinition(
        APP_CLOSE,
        keywords=["schließe", "beende", "schliessen", "beenden", "kill", "stoppe"],
        patterns=[r"\b(schließe|beende|stoppe)\s+\w+"],
        requires_llm=False,
        weight=1.3,
    ),
    IntentDefinition(
        FILE_SEARCH,
        keywords=["finde", "suche datei", "wo ist", "dateiname", "ordner", "verzeichnis"],
        patterns=[r"\b(finde|suche)\b.*\.(pdf|docx?|txt|py|md|xlsx?|png|jpe?g)\b"],
        requires_llm=False,
        weight=1.2,
    ),
    IntentDefinition(
        TERMINAL,
        keywords=["terminal", "konsole", "powershell", "eingabeaufforderung", "cmd", "shell"],
        requires_llm=False,
    ),
    IntentDefinition(
        BROWSER,
        keywords=["browser", "firefox", "chrome", "edge", "webseite", "website", "url"],
        requires_llm=False,
    ),
    IntentDefinition(
        MUSIC,
        keywords=["musik", "spiele ab", "abspielen", "lautstärke", "pausiere", "song", "playlist"],
        requires_llm=False,
    ),
    IntentDefinition(
        CALENDAR,
        keywords=["kalender", "termin", "meeting", "besprechung", "kalendereintrag"],
        requires_llm=False,
    ),
    IntentDefinition(
        REMINDER,
        keywords=["erinnere", "erinnerung", "erinner mich", "vergiss nicht", "wecke"],
        requires_llm=False,
    ),
    IntentDefinition(
        SETTINGS,
        keywords=["einstellung", "einstellungen", "konfiguration", "theme", "farbe ändern", "config"],
        requires_llm=False,
    ),
    IntentDefinition(
        SYSTEM_STATUS,
        keywords=[
            "systemstatus",
            "auslastung",
            "arbeitsspeicher",
            "festplatte",
            "cpu",
            "speicherplatz",
            "systeminfo",
        ],
        requires_llm=False,
        weight=1.6,
    ),
    IntentDefinition(
        DESKTOP_CONTROL,
        keywords=["fenster", "minimiere", "maximiere", "bildschirm", "monitor", "desktop"],
        requires_llm=False,
    ),
    IntentDefinition(
        PLUGIN,
        keywords=["skill", "plugin", "erweiterung", "installiere skill", "fähigkeit"],
        requires_llm=False,
    ),
    IntentDefinition(
        TRANSPARENCY,
        keywords=[
            "warum hast du",
            "welche agenten",
            "welcher kontext",
            "welches modell",
            "woran arbeite ich",
            "welche ziele",
            "welche strategie",
            "wie bist du",
        ],
        patterns=[r"\bwarum\s+hast\s+du\b", r"\bwelche[nrs]?\s+(agenten|kontext|modell|strategie|ziele)\b"],
        requires_llm=False,
        weight=1.5,
    ),
    IntentDefinition(
        PROJECT,
        keywords=["projekt", "hausarbeit", "workspace", "repository", "arbeitsstand"],
        requires_llm=False,
        weight=1.1,
    ),
    IntentDefinition(
        TASK,
        keywords=[
            "aufgabe",
            "aufgaben",
            "todo",
            "to-do",
            "erledigt",
            "offene punkte",
            "offene aufgaben",
            "nächster schritt",
        ],
        patterns=[r"\baufgaben?\b.*\boffen\b", r"\boffen\w*\b.*\baufgaben?\b"],
        requires_llm=False,
        weight=1.4,
    ),
    IntentDefinition(
        RESEARCH,
        keywords=["recherchiere", "recherche", "quellen", "literatur", "finde heraus", "aktuell"],
        weight=1.2,
    ),
    IntentDefinition(
        CODING,
        keywords=[
            "code",
            "programmiere",
            "funktion",
            "klasse",
            "bug",
            "fehler im code",
            "refactor",
            "python",
            "javascript",
            "rust",
            "typescript",
            "kompiliere",
            "unittest",
        ],
        weight=1.2,
    ),
    IntentDefinition(
        HISTORY,
        keywords=[
            "geschichte",
            "historisch",
            "mittelalter",
            "quellenkritik",
            "investiturstreit",
            "epoche",
            "jahrhundert",
            "antike",
            "neuzeit",
        ],
        weight=1.2,
    ),
    IntentDefinition(
        DOCUMENT,
        keywords=[
            "fasse zusammen",
            "zusammenfassen",
            "zusammenfassung",
            "dokument",
            "text kürzen",
            "exzerpt",
            "gliederung",
        ],
        patterns=[r"\bfasse\b.*\bzusammen\b"],
        weight=1.4,
    ),
    IntentDefinition(
        QUESTION,
        keywords=["erkläre", "bedeutet", "unterschied", "definition", "funktioniert"],
        patterns=[r"\?\s*$"],
        weight=0.7,
    ),
    IntentDefinition(
        SMALL_TALK,
        keywords=["hallo", "hi", "guten morgen", "guten abend", "danke", "tschüss", "wie geht"],
        requires_llm=False,
        weight=1.6,
    ),
]


class IntentClassifier:
    """Ordnet eine Benutzereingabe einem Intent zu."""

    def __init__(self, intents: list[IntentDefinition] | None = None) -> None:
        self._intents: dict[str, IntentDefinition] = {}
        for definition in intents if intents is not None else _DEFAULT_INTENTS:
            self._intents[definition.name] = definition

    def register_intent(self, definition: IntentDefinition) -> None:
        """Ergänzt einen neuen Intent zur Laufzeit.

        Ermöglicht es Skills und Plugins, eigene Intents beizusteuern, ohne
        den Kern zu verändern.
        """

        self._intents[definition.name] = definition

    @property
    def intents(self) -> list[str]:
        """Namen aller bekannten Intents."""

        return sorted(self._intents)

    def classify(self, text: str) -> IntentResult:
        """Klassifiziert eine Benutzereingabe.

        Args:
            text: Die Eingabe des Benutzers.

        Returns:
            Das Klassifikationsergebnis inklusive Sicherheitskategorie
            (``hoch``, ``mittel``, ``niedrig``) und der Angabe, ob ein
            Sprachmodell benötigt wird.
        """

        lowered = text.lower().strip()
        tokens = set(tokenize(text))

        best_name = UNKNOWN
        best_score = 0.0
        best_matches: list[str] = []

        for definition in self._intents.values():
            score = 0.0
            matches: list[str] = []

            for keyword in definition.keywords:
                if " " in keyword:
                    if keyword in lowered:
                        score += 2.0
                        matches.append(keyword)
                else:
                    stem_tokens = set(tokenize(keyword))
                    if stem_tokens and stem_tokens <= tokens:
                        score += 1.0
                        matches.append(keyword)

            for pattern in definition.patterns:
                if re.search(pattern, lowered, flags=re.IGNORECASE):
                    score += 2.0
                    matches.append(f"muster:{pattern}")

            score *= definition.weight

            if score > best_score:
                best_score = score
                best_name = definition.name
                best_matches = matches

        if best_score == 0.0:
            # Ohne jeden Treffer: Fragezeichen deutet auf eine Frage hin,
            # sonst allgemeiner Chat.
            best_name = QUESTION if lowered.endswith("?") else CHAT
            best_score = 0.5

        definition = self._intents.get(best_name)
        requires_llm = definition.requires_llm if definition else True

        if best_score >= 3.0:
            confidence = "hoch"
        elif best_score >= 1.5:
            confidence = "mittel"
        else:
            confidence = "niedrig"

        # Bei niedriger Sicherheit ist eine reine Regelentscheidung riskant;
        # dann wird das Sprachmodell hinzugezogen.
        if confidence == "niedrig":
            requires_llm = True

        return IntentResult(
            intent=best_name,
            confidence=confidence,
            score=best_score,
            requires_llm=requires_llm,
            matched_keywords=best_matches,
            entities=self.extract_entities(text),
        )

    @staticmethod
    def extract_entities(text: str) -> dict[str, Any]:
        """Extrahiert einfache Entitäten (Dateinamen, Programme, URLs, Zeiten)."""

        entities: dict[str, Any] = {}

        files = re.findall(
            r"\b[\w\-.]+\.(?:pdf|docx?|txt|py|md|xlsx?|png|jpe?g|ts|json|yaml)\b",
            text,
            re.IGNORECASE,
        )
        if files:
            entities["files"] = [name.strip() for name in files]

        urls = re.findall(r"https?://\S+", text)
        if urls:
            entities["urls"] = urls

        times = re.findall(r"\b\d{1,2}[:.]\d{2}\b", text)
        if times:
            entities["times"] = times

        apps = re.findall(
            r"\b(firefox|chrome|edge|vs\s?code|visual studio code|explorer|terminal|"
            r"powershell|cmd|notepad|word|excel|outlook|spotify|blender|gimp|zotero|docker)\b",
            text,
            re.IGNORECASE,
        )
        if apps:
            entities["applications"] = sorted({app.lower() for app in apps})

        return entities
