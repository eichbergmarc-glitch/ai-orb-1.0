"""Planner – zerlegt komplexe Aufgaben in nachvollziehbare Schritte.

Beispiel: "Schreibe eine Hausarbeit" wird zu Literatur sammeln →
Fragestellung entwickeln → Gliederung → Recherche → Schreiben →
Überarbeiten → Zitation prüfen.

Der Orb unterstützt jeden dieser Schritte, ersetzt aber ausdrücklich nicht
die wissenschaftliche Eigenleistung des Benutzers: Er liefert Struktur,
Material und Rückmeldung, schreibt aber keine Arbeit, die als eigene
Leistung ausgegeben werden soll.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class PlanStep:
    """Ein einzelner Schritt eines Plans."""

    index: int
    title: str
    description: str = ""
    module: str = "conversation"
    status: str = "offen"
    result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "description": self.description,
            "module": self.module,
            "status": self.status,
            "result": self.result,
        }


@dataclass
class Plan:
    """Ein vollständiger Lösungsplan."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    kind: str = "allgemein"
    note: str = ""

    @property
    def is_complete(self) -> bool:
        """Ob alle Schritte abgeschlossen sind."""

        return all(step.status == "erledigt" for step in self.steps)

    def current_step(self) -> PlanStep | None:
        """Der erste noch nicht erledigte Schritt."""

        for step in self.steps:
            if step.status != "erledigt":
                return step
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "kind": self.kind,
            "note": self.note,
            "created_at": self.created_at,
            "complete": self.is_complete,
            "steps": [step.to_dict() for step in self.steps],
        }

    def as_text(self) -> str:
        """Formuliert den Plan als lesbare Schrittfolge."""

        lines = [f"Plan für: {self.goal}"]
        for step in self.steps:
            marker = "✓" if step.status == "erledigt" else "•"
            lines.append(f"  {marker} {step.index}. {step.title}")
        if self.note:
            lines.append(self.note)
        return "\n".join(lines)


#: Vorlagen für wiederkehrende Aufgabenarten. Jeder Eintrag ordnet einem
#: Schritt zugleich das zuständige Modul zu.
_TEMPLATES: dict[str, tuple[tuple[str, ...], list[tuple[str, str]], str]] = {
    "hausarbeit": (
        ("hausarbeit", "seminararbeit", "essay", "aufsatz", "bachelorarbeit", "masterarbeit"),
        [
            ("Thema analysieren", "history"),
            ("Literatur sammeln", "research"),
            ("Fragestellung entwickeln", "history"),
            ("Gliederung erstellen", "conversation"),
            ("Recherche durchführen", "research"),
            ("Schreiben", "conversation"),
            ("Überarbeiten", "conversation"),
            ("Zitation prüfen", "research"),
        ],
        "Ich unterstütze dich bei jedem Schritt, ersetze aber nicht deine "
        "wissenschaftliche Eigenleistung.",
    ),
    "frage": (
        ("erkläre", "was ist", "wie funktioniert", "warum", "bedeutet"),
        [
            ("Informationen sammeln", "memory"),
            ("Antwort strukturieren", "conversation"),
            ("Unsicherheiten prüfen", "verification"),
            ("Antwort erzeugen", "conversation"),
        ],
        "",
    ),
    "desktop": (
        ("öffne", "starte", "schließe", "beende", "führe aus"),
        [
            ("Befehl verstehen", "conversation"),
            ("Programm finden", "desktop"),
            ("Aktion ausführen", "desktop"),
            ("Erfolg prüfen", "desktop"),
        ],
        "",
    ),
    "code": (
        ("programmiere", "schreibe code", "implementiere", "refactor", "bug", "fehler im code"),
        [
            ("Problem analysieren", "coding"),
            ("Architektur überlegen", "coding"),
            ("Plan entwickeln", "coding"),
            ("Code erzeugen", "coding"),
            ("Code prüfen", "coding"),
            ("Fehler suchen", "coding"),
            ("Verbesserungen vorschlagen", "coding"),
        ],
        "",
    ),
    "recherche": (
        ("recherchiere", "recherche", "quellen suchen", "literatur suchen"),
        [
            ("Suchbegriffe festlegen", "research"),
            ("Quellen suchen", "research"),
            ("Quellen vergleichen", "verification"),
            ("Ergebnisse zusammenfassen", "conversation"),
            ("Quellen dokumentieren", "research"),
        ],
        "Ich dokumentiere alle verwendeten Quellen nachvollziehbar.",
    ),
}


class Planner:
    """Erzeugt Lösungspläne für Aufgaben."""

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}

    def create_plan(self, goal: str, *, complexity: str = "mittel") -> Plan:
        """Erstellt einen Plan für ein Ziel.

        Args:
            goal: Beschreibung der Aufgabe.
            complexity: ``einfach``, ``mittel`` oder ``komplex``. Einfache
                Aufgaben erhalten bewusst einen minimalen Plan, damit sie
                nicht unnötig verkompliziert werden.

        Returns:
            Der erzeugte Plan.
        """

        lowered = goal.lower()

        if complexity == "einfach":
            plan = Plan(goal=goal, kind="direkt")
            plan.steps = [PlanStep(index=1, title="Direkt beantworten", module="conversation")]
            self._plans[plan.id] = plan
            return plan

        for kind, (keywords, steps, note) in _TEMPLATES.items():
            if any(keyword in lowered for keyword in keywords):
                plan = Plan(goal=goal, kind=kind, note=note)
                plan.steps = [
                    PlanStep(index=position, title=title, module=module)
                    for position, (title, module) in enumerate(steps, start=1)
                ]
                self._plans[plan.id] = plan
                logger.info("Plan '%s' mit %d Schritten erstellt.", kind, len(plan.steps))
                return plan

        # Allgemeiner Standardplan.
        plan = Plan(goal=goal, kind="allgemein")
        plan.steps = [
            PlanStep(index=1, title="Aufgabe analysieren", module="reasoning"),
            PlanStep(index=2, title="Benötigte Informationen sammeln", module="memory"),
            PlanStep(index=3, title="Lösung erarbeiten", module="conversation"),
            PlanStep(index=4, title="Ergebnis prüfen", module="verification"),
        ]
        self._plans[plan.id] = plan
        return plan

    def get(self, plan_id: str) -> Plan | None:
        """Liest einen Plan."""

        return self._plans.get(plan_id)

    def complete_step(self, plan_id: str, step_index: int, result: str = "") -> bool:
        """Markiert einen Planschritt als erledigt."""

        plan = self._plans.get(plan_id)
        if plan is None:
            return False
        for step in plan.steps:
            if step.index == step_index:
                step.status = "erledigt"
                step.result = result
                return True
        return False

    def active_plans(self) -> list[Plan]:
        """Alle noch nicht abgeschlossenen Pläne."""

        return [plan for plan in self._plans.values() if not plan.is_complete]
