"""Decision Engine – die Entscheidung vor jeder Antwort.

Vor jeder Antwort klärt der Orb:

* Welche Module werden benötigt?
* Welche Daten sind relevant?
* Ist Internet notwendig?
* Kann lokal gearbeitet werden?
* Ist eine Rückfrage nötig?
* Soll eine Aktion vorgeschlagen werden?

Jede Entscheidung ist nachvollziehbar: Sie enthält die Gründe, die zu ihr
geführt haben, ohne interne Gedankengänge offenzulegen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.orchestrator.intent_classifier import IntentResult
from backend.orchestrator import intent_classifier as intents

#: Intents, die ohne jede Netzverbindung bearbeitet werden können.
_LOCAL_ONLY_INTENTS: frozenset[str] = frozenset(
    {
        intents.APP_START,
        intents.APP_CLOSE,
        intents.FILE_SEARCH,
        intents.TERMINAL,
        intents.BROWSER,
        intents.MUSIC,
        intents.SETTINGS,
        intents.SYSTEM_STATUS,
        intents.DESKTOP_CONTROL,
        intents.TRANSPARENCY,
        intents.TASK,
        intents.PROJECT,
        intents.PLUGIN,
    }
)

#: Intents, die typischerweise aktuelle externe Informationen benötigen.
_NEEDS_INTERNET_INTENTS: frozenset[str] = frozenset({intents.RESEARCH})

#: Begriffe, die auf einen Bedarf an aktuellen Informationen hindeuten.
_FRESHNESS_MARKERS: tuple[str, ...] = (
    "aktuell",
    "neueste",
    "heute",
    "gerade eben",
    "news",
    "nachrichten",
    "kurs",
    "preis",
    "wetter",
    "dieses jahr",
)

#: Intents, deren Ausführung reale Auswirkungen hat und daher als riskant gilt.
_RISKY_INTENTS: frozenset[str] = frozenset({intents.APP_CLOSE})


@dataclass
class Decision:
    """Das Ergebnis der Entscheidungsfindung."""

    modules: list[str] = field(default_factory=list)
    needs_llm: bool = True
    needs_internet: bool = False
    can_work_offline: bool = True
    needs_clarification: bool = False
    clarification_question: str = ""
    suggest_action: bool = False
    risk_level: str = "gering"
    requires_confirmation: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modules": self.modules,
            "needs_llm": self.needs_llm,
            "needs_internet": self.needs_internet,
            "can_work_offline": self.can_work_offline,
            "needs_clarification": self.needs_clarification,
            "clarification_question": self.clarification_question,
            "suggest_action": self.suggest_action,
            "risk_level": self.risk_level,
            "requires_confirmation": self.requires_confirmation,
            "reasons": self.reasons,
        }

    def explain(self) -> str:
        """Formuliert die Entscheidung verständlich für den Benutzer."""

        if not self.reasons:
            return "Es lag keine besondere Entscheidung vor."
        return " ".join(self.reasons)


class DecisionEngine:
    """Trifft die Vorentscheidung für jede Anfrage."""

    def decide(
        self,
        text: str,
        intent: IntentResult,
        *,
        has_context: bool = False,
        provider_available: bool = True,
    ) -> Decision:
        """Trifft eine nachvollziehbare Entscheidung über das weitere Vorgehen.

        Args:
            text: Die Benutzereingabe.
            intent: Das Ergebnis der Intent-Klassifikation.
            has_context: Ob bereits Kontext (Projekt, Gedächtnis) vorliegt.
            provider_available: Ob überhaupt ein Sprachmodell erreichbar ist.

        Returns:
            Die getroffene Entscheidung mit Begründungen.
        """

        decision = Decision()
        lowered = text.lower()

        # --- Benötigte Module ------------------------------------------------
        module_map = {
            intents.APP_START: "desktop",
            intents.APP_CLOSE: "desktop",
            intents.TERMINAL: "desktop",
            intents.BROWSER: "desktop",
            intents.DESKTOP_CONTROL: "desktop",
            intents.FILE_SEARCH: "dateien",
            intents.RESEARCH: "research",
            intents.CODING: "coding",
            intents.HISTORY: "history",
            intents.PROJECT: "projects",
            intents.TASK: "tasks",
            intents.TRANSPARENCY: "transparenz",
            intents.DOCUMENT: "dokumente",
            intents.PLUGIN: "skills",
            intents.SYSTEM_STATUS: "system",
        }
        primary_module = module_map.get(intent.intent, "conversation")
        decision.modules.append(primary_module)
        if primary_module not in ("desktop", "system", "transparenz"):
            decision.modules.append("memory")

        # --- Sprachmodell nötig? ----------------------------------------------
        decision.needs_llm = intent.requires_llm
        if intent.intent in _LOCAL_ONLY_INTENTS and intent.confidence != "niedrig":
            decision.needs_llm = False
            decision.reasons.append(
                f"Die Anfrage konnte als „{intent.intent}“ erkannt werden und lässt "
                "sich lokal ohne Sprachmodell bearbeiten."
            )
        else:
            decision.reasons.append(
                "Für diese Anfrage wird ein Sprachmodell benötigt, da sie "
                "inhaltlich beantwortet werden muss."
            )

        # --- Internet nötig? --------------------------------------------------
        needs_fresh = any(marker in lowered for marker in _FRESHNESS_MARKERS)
        decision.needs_internet = intent.intent in _NEEDS_INTERNET_INTENTS or needs_fresh
        if decision.needs_internet:
            decision.reasons.append(
                "Es werden möglicherweise aktuelle Informationen benötigt, "
                "die nur online verfügbar sind."
            )

        decision.can_work_offline = not decision.needs_internet and (
            not decision.needs_llm or provider_available
        )

        # --- Rückfrage nötig? --------------------------------------------------
        if intent.confidence == "niedrig" and len(text.split()) <= 3 and not has_context:
            decision.needs_clarification = True
            decision.clarification_question = (
                "Ich bin mir nicht sicher, was du genau möchtest. "
                "Kannst du das etwas genauer beschreiben?"
            )
            decision.reasons.append(
                "Die Anfrage war zu kurz und mehrdeutig, um sie zuverlässig "
                "einzuordnen."
            )

        # Frueher wurde hier zurueckgefragt, sobald die Absichtserkennung
        # kein Programm als Entitaet gefunden hatte: „Welches Programm
        # meinst du genau?" – und der Vorgang endete.
        #
        # Das war die stille Sackgasse hinter „er kann keine Programme
        # oeffnen": Die Entitaetserkennung kennt nur eine Handvoll Namen,
        # bei „mach mir Spotify auf" fand sie nichts, und es wurde
        # zurueckgefragt, statt zu handeln. Dabei stehen dahinter zwei
        # Instanzen, die es muehelos aufloesen: der Verteiler mit seiner
        # Aliasliste und das Sprachmodell mit dem Werkzeug
        # 'programm_starten'.
        #
        # Nachgefragt wird deshalb nur noch, wenn im Satz ausser dem
        # Oeffnen-Wort wirklich NICHTS steht – bei einem blossen „oeffne"
        # ist die Rueckfrage berechtigt.
        if intent.intent in (intents.APP_START, intents.APP_CLOSE):
            hat_entitaet = bool(intent.entities.get("applications"))
            uebrig = [
                wort
                for wort in text.lower().split()
                if wort.strip(".,!?") not in {
                    "öffne", "oeffne", "öffnen", "starte", "starten", "schließe",
                    "schliesse", "beende", "mach", "mache", "auf", "zu", "bitte",
                    "mal", "mir", "den", "die", "das", "ein", "eine", "einen",
                    "doch", "jetzt",
                }
            ]
            if not hat_entitaet and not uebrig:
                decision.needs_clarification = True
                decision.clarification_question = "Welches Programm meinst du genau?"
            decision.reasons.append("Es war kein eindeutiges Programm erkennbar.")

        # --- Risiko und Bestätigung ---------------------------------------------
        if intent.intent in _RISKY_INTENTS:
            decision.risk_level = "hoch"
            decision.requires_confirmation = True
            decision.reasons.append(
                "Die Aktion kann laufende Arbeit beeinträchtigen und wird daher "
                "erst nach deiner Bestätigung ausgeführt."
            )
        elif intent.intent in (intents.APP_START, intents.DESKTOP_CONTROL):
            decision.risk_level = "mittel"

        # --- Aktionsvorschlag ---------------------------------------------------
        decision.suggest_action = intent.intent in (
            intents.PROJECT,
            intents.TASK,
            intents.DOCUMENT,
        )

        return decision
