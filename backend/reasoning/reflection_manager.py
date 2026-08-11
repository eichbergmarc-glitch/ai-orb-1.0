"""Reflection Manager – Nachbetrachtung im Reasoning-Kreislauf.

Der Manager kapselt die :class:`~backend.cognitive.reflection_engine.ReflectionEngine`
für den Reasoning-Ablauf: Er beobachtet die Bearbeitung einer Aufgabe von
Anfang bis Ende, sammelt Fehler und Kennzahlen und führt die
Nachbetrachtung durch.

Gespeichert werden ausschließlich nachvollziehbare, aufgabenbezogene
Erkenntnisse und nur mit transparenter Speicherung.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.cognitive.reflection_engine import Reflection, ReflectionEngine
from backend.reasoning.strategy_selector import StrategySelection
from backend.reasoning.task_analyzer import TaskProfile
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ExecutionTrace:
    """Protokoll der Bearbeitung einer Aufgabe."""

    task: str
    strategy: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    modules: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    successful: bool = True

    @property
    def duration(self) -> float:
        """Bearbeitungsdauer in Sekunden."""

        return (self.finished_at or time.time()) - self.started_at

    def note_module(self, module: str) -> None:
        """Vermerkt ein beteiligtes Modul."""

        if module not in self.modules:
            self.modules.append(module)

    def note_error(self, message: str) -> None:
        """Vermerkt einen Fehler; die Aufgabe gilt danach als nicht erfolgreich."""

        self.errors.append(message)
        self.successful = False

    def finish(self, *, successful: bool | None = None) -> None:
        """Schließt das Protokoll ab."""

        self.finished_at = time.time()
        if successful is not None:
            self.successful = successful

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "strategy": self.strategy,
            "duration": round(self.duration, 3),
            "modules": self.modules,
            "errors": self.errors,
            "successful": self.successful,
        }


class ReflectionManager:
    """Begleitet Aufgaben und führt anschließend die Nachbetrachtung durch."""

    #: Ab dieser Dauer gilt eine Aufgabe als "größere Aufgabe", die
    #: reflektiert wird. Kurze Aufgaben werden nicht unnötig nachbereitet.
    MIN_DURATION_FOR_REFLECTION = 2.0

    def __init__(self, engine: ReflectionEngine) -> None:
        self._engine = engine
        self._traces: dict[str, ExecutionTrace] = {}

    def begin(self, task_id: str, profile: TaskProfile, strategy: StrategySelection) -> ExecutionTrace:
        """Beginnt die Beobachtung einer Aufgabe."""

        trace = ExecutionTrace(task=profile.text, strategy=strategy.primary)
        for module in profile.required_modules:
            trace.note_module(module)
        self._traces[task_id] = trace
        return trace

    def trace(self, task_id: str) -> ExecutionTrace | None:
        """Gibt das Protokoll einer laufenden Aufgabe zurück."""

        return self._traces.get(task_id)

    def finish(
        self,
        task_id: str,
        *,
        successful: bool | None = None,
        profile: TaskProfile | None = None,
    ) -> Reflection | None:
        """Schließt eine Aufgabe ab und führt die Nachbetrachtung durch.

        Returns:
            Die Nachbetrachtung, oder ``None``, wenn die Aufgabe zu klein
            war, um reflektiert zu werden.
        """

        trace = self._traces.pop(task_id, None)
        if trace is None:
            return None

        trace.finish(successful=successful)

        is_major = (
            trace.duration >= self.MIN_DURATION_FOR_REFLECTION
            or not trace.successful
            or (profile is not None and profile.complexity != "einfach")
        )
        if not is_major:
            return None

        reflection = self._engine.reflect(
            trace.task,
            successful=trace.successful,
            strategy=trace.strategy,
            duration_seconds=trace.duration,
            errors=trace.errors,
            used_modules=trace.modules,
        )
        logger.info(
            "Nachbetrachtung abgeschlossen (%s, erfolgreich=%s).",
            trace.task[:40],
            trace.successful,
        )
        return reflection

    def learned_summary(self) -> dict[str, Any]:
        """Fasst zusammen, was der Orb aus bisherigen Abläufen gelernt hat.

        Beantwortet die Transparenzfrage, welche Strategien sich bewährt
        haben – ohne personenbezogene Bewertungen.
        """

        best = self._engine.best_strategies()
        return {
            "bewährte_strategien": [
                {"strategie": name, "erfolgsquote": round(rate, 2)} for name, rate in best
            ],
            "letzte_nachbetrachtungen": [
                {
                    "aufgabe": entry.get("task", "")[:80],
                    "erfolgreich": entry.get("successful"),
                    "verbesserungen": entry.get("improvements", []),
                }
                for entry in self._engine.recent(limit=5)
            ],
        }
