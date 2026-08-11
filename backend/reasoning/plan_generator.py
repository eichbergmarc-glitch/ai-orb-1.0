"""Plan Generator – erzeugt Lösungspläne aus einem Task Profile.

Der Generator baut auf dem :class:`~backend.cognitive.planner.Planner` des
Cognitive Core auf und ergänzt ihn um die Berücksichtigung des Task
Profiles: Einfache Aufgaben erhalten keinen aufwendigen Plan, komplexe
Aufgaben werden vollständig zerlegt.
"""

from __future__ import annotations

from typing import Any

from backend.cognitive.planner import Plan, PlanStep, Planner
from backend.config import get_config
from backend.reasoning.strategy_selector import StrategySelection
from backend.reasoning.task_analyzer import TaskProfile
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Reihenfolge der Komplexitätsstufen für den Vergleich.
_COMPLEXITY_ORDER: dict[str, int] = {"einfach": 0, "mittel": 1, "komplex": 2}


class PlanGenerator:
    """Erzeugt Pläne unter Berücksichtigung von Profil und Strategie."""

    def __init__(self, planner: Planner | None = None) -> None:
        config = get_config()
        reasoning_config = config.section("reasoning")

        self._planner = planner or Planner()
        self._threshold = str(reasoning_config.get("plan_from_complexity", "mittel"))

    def should_plan(self, profile: TaskProfile) -> bool:
        """Entscheidet, ob überhaupt ein Plan erstellt wird.

        Einfache Aufgaben werden bewusst nicht verkompliziert
        (Performance-Anforderung).
        """

        required = _COMPLEXITY_ORDER.get(self._threshold, 1)
        actual = _COMPLEXITY_ORDER.get(profile.complexity, 0)
        return actual >= required

    def generate(self, profile: TaskProfile, strategy: StrategySelection) -> Plan:
        """Erzeugt einen Plan für eine Aufgabe.

        Args:
            profile: Das Task Profile.
            strategy: Die gewählte Strategie; bestimmt die Modulzuordnung
                der Schritte.

        Returns:
            Der erzeugte Plan.
        """

        complexity = profile.complexity if self.should_plan(profile) else "einfach"
        plan = self._planner.create_plan(profile.text, complexity=complexity)

        # Strategiespezifische Schritte ergänzen, sofern noch nicht enthalten.
        additions = self._strategy_steps(strategy, profile)
        if additions:
            next_index = len(plan.steps) + 1
            existing = {step.title.lower() for step in plan.steps}
            for title, module in additions:
                if title.lower() in existing:
                    continue
                plan.steps.append(PlanStep(index=next_index, title=title, module=module))
                next_index += 1

        if profile.risk == "hoch":
            plan.steps.append(
                PlanStep(
                    index=len(plan.steps) + 1,
                    title="Bestätigung des Benutzers einholen",
                    module="conversation",
                )
            )

        logger.info(
            "Plan erzeugt für '%s' (%d Schritte, Komplexität %s).",
            profile.text[:50],
            len(plan.steps),
            complexity,
        )
        return plan

    @staticmethod
    def _strategy_steps(
        strategy: StrategySelection, profile: TaskProfile
    ) -> list[tuple[str, str]]:
        """Liefert zusätzliche Schritte, die sich aus der Strategie ergeben."""

        from backend.reasoning import strategy_selector as strategies

        additions: list[tuple[str, str]] = []
        for name in strategy.all:
            if name == strategies.RESEARCH_ENGINE:
                additions.append(("Quellen dokumentieren", "research"))
            elif name == strategies.VISION:
                additions.append(("Bildschirminhalt auswerten", "vision"))
            elif name == strategies.PROJECT_CONTEXT:
                additions.append(("Projektkontext einbeziehen", "projects"))
            elif name == strategies.MEMORY_LOOKUP:
                additions.append(("Gedächtnis durchsuchen", "memory"))

        if profile.complexity == "komplex":
            additions.append(("Ergebnis auf Konsistenz prüfen", "verification"))

        return additions

    def get(self, plan_id: str) -> Plan | None:
        """Liest einen erzeugten Plan."""

        return self._planner.get(plan_id)

    def complete_step(self, plan_id: str, step_index: int, result: str = "") -> bool:
        """Markiert einen Planschritt als erledigt."""

        return self._planner.complete_step(plan_id, step_index, result)

    def active_plans(self) -> list[dict[str, Any]]:
        """Alle laufenden Pläne (für die Transparenzansicht)."""

        return [plan.to_dict() for plan in self._planner.active_plans()]
