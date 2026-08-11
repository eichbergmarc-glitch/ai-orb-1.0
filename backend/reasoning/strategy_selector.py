"""Strategy Selector – wählt die beste Bearbeitungsstrategie.

Mögliche Strategien sind unter anderem direkte Antwort, Recherche, Vision,
Desktopsteuerung, Coding, History Mentor und Research Engine. Mehrere
Strategien können kombiniert werden, wenn dies erforderlich ist.

Der Selector lernt aus der Reflexion: Strategien, die für eine Aufgabenart
wiederholt erfolgreich waren, werden bevorzugt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.cognitive.reflection_engine import ReflectionEngine
from backend.orchestrator import intent_classifier as intents
from backend.reasoning.task_analyzer import TaskProfile
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Alle verfügbaren Strategien.
DIRECT_ANSWER = "direkte_antwort"
RESEARCH = "recherche"
VISION = "vision"
DESKTOP = "desktopsteuerung"
CODING = "coding"
HISTORY_MENTOR = "history_mentor"
RESEARCH_ENGINE = "research_engine"
PROJECT_CONTEXT = "projektkontext"
MEMORY_LOOKUP = "gedächtnisabfrage"

STRATEGIES: tuple[str, ...] = (
    DIRECT_ANSWER,
    RESEARCH,
    VISION,
    DESKTOP,
    CODING,
    HISTORY_MENTOR,
    RESEARCH_ENGINE,
    PROJECT_CONTEXT,
    MEMORY_LOOKUP,
)

#: Grundzuordnung von Intent zu Strategien.
_BASE_STRATEGIES: dict[str, list[str]] = {
    intents.HISTORY: [HISTORY_MENTOR, MEMORY_LOOKUP],
    intents.RESEARCH: [RESEARCH_ENGINE, RESEARCH],
    intents.CODING: [CODING],
    intents.APP_START: [DESKTOP],
    intents.APP_CLOSE: [DESKTOP],
    intents.TERMINAL: [DESKTOP],
    intents.BROWSER: [DESKTOP],
    intents.DESKTOP_CONTROL: [DESKTOP],
    intents.FILE_SEARCH: [DESKTOP],
    intents.SYSTEM_STATUS: [DESKTOP],
    intents.PROJECT: [PROJECT_CONTEXT, MEMORY_LOOKUP],
    intents.TASK: [PROJECT_CONTEXT, MEMORY_LOOKUP],
    intents.DOCUMENT: [MEMORY_LOOKUP, DIRECT_ANSWER],
    intents.QUESTION: [MEMORY_LOOKUP, DIRECT_ANSWER],
    intents.CHAT: [DIRECT_ANSWER],
    intents.SMALL_TALK: [DIRECT_ANSWER],
    intents.TRANSPARENCY: [DIRECT_ANSWER],
}


@dataclass
class StrategySelection:
    """Die gewählte Strategie (oder Strategiekombination)."""

    primary: str = DIRECT_ANSWER
    additional: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def all(self) -> list[str]:
        """Alle beteiligten Strategien in Reihenfolge."""

        return [self.primary, *self.additional]

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "additional": self.additional,
            "all": self.all,
            "reason": self.reason,
        }


class StrategySelector:
    """Wählt die passende Strategie für eine Aufgabe."""

    def __init__(self, reflection: ReflectionEngine | None = None) -> None:
        self._reflection = reflection

    def select(
        self,
        profile: TaskProfile,
        *,
        has_project: bool = False,
        has_image: bool = False,
        internet_available: bool = True,
    ) -> StrategySelection:
        """Wählt die Strategie für eine Aufgabe.

        Args:
            profile: Das Task Profile.
            has_project: Ob ein Projekt aktiv ist.
            has_image: Ob ein Bild oder Bildschirminhalt vorliegt.
            internet_available: Ob eine Online-Recherche möglich ist.

        Returns:
            Die gewählte Strategie mit Begründung.
        """

        candidates = list(_BASE_STRATEGIES.get(profile.kind, [DIRECT_ANSWER]))

        if has_image and VISION not in candidates:
            candidates.insert(0, VISION)
        if has_project and PROJECT_CONTEXT not in candidates:
            candidates.append(PROJECT_CONTEXT)
        if profile.complexity == "komplex" and MEMORY_LOOKUP not in candidates:
            candidates.append(MEMORY_LOOKUP)

        if not internet_available:
            candidates = [
                strategy for strategy in candidates if strategy not in (RESEARCH, RESEARCH_ENGINE)
            ] or [DIRECT_ANSWER]

        # Erfolgsquoten aus der Reflexion berücksichtigen.
        if self._reflection is not None and len(candidates) > 1:
            candidates.sort(
                key=lambda strategy: self._reflection.strategy_success_rate(strategy),
                reverse=True,
            )

        primary = candidates[0]
        additional = candidates[1:]

        reason = self._explain(profile, primary, additional, internet_available)
        logger.info(
            "Strategie gewählt: %s%s",
            primary,
            f" (+ {', '.join(additional)})" if additional else "",
        )
        return StrategySelection(primary=primary, additional=additional, reason=reason)

    @staticmethod
    def _explain(
        profile: TaskProfile, primary: str, additional: list[str], internet_available: bool
    ) -> str:
        """Formuliert die Strategiewahl verständlich."""

        descriptions = {
            DIRECT_ANSWER: "direkt zu antworten",
            RESEARCH: "zu recherchieren",
            RESEARCH_ENGINE: "gezielt nach Quellen zu suchen",
            VISION: "den Bildschirminhalt auszuwerten",
            DESKTOP: "eine Desktop-Aktion auszuführen",
            CODING: "das Problem als Programmieraufgabe zu bearbeiten",
            HISTORY_MENTOR: "geschichtswissenschaftlich vorzugehen",
            PROJECT_CONTEXT: "den Projektzusammenhang einzubeziehen",
            MEMORY_LOOKUP: "im Gedächtnis nachzusehen",
        }

        complexity_label = {
            "einfach": "einfacher",
            "mittel": "mittlerer",
            "komplex": "hoher",
        }.get(profile.complexity, profile.complexity)

        parts = [
            f"Ich habe mich entschieden, {descriptions.get(primary, primary)}, "
            f"weil die Aufgabe als „{profile.kind}“ mit {complexity_label} "
            "Komplexität eingeordnet wurde."
        ]
        if additional:
            names = ", ".join(descriptions.get(item, item) for item in additional)
            parts.append(f"Ergänzend ziehe ich in Betracht: {names}.")
        if not internet_available:
            parts.append("Da keine Internetverbindung besteht, arbeite ich rein lokal.")
        return " ".join(parts)
