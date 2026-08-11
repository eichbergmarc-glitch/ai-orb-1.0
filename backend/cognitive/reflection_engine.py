"""Reflection Engine – Nachbetrachtung abgeschlossener Aufgaben.

Nach jeder größeren Aufgabe analysiert der Orb:

* War die Lösung erfolgreich?
* Gab es Probleme?
* Kann der Ablauf verbessert werden?
* Welche Erkenntnisse sind langfristig relevant?

Wichtig: Es werden **keine personenbezogenen Schlussfolgerungen** über den
Benutzer gespeichert. Gespeichert werden ausschließlich aufgabenbezogene,
sachliche Erkenntnisse – und auch diese nur, wenn der Benutzer das
Speichern nicht deaktiviert hat.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.memory.memory_engine import MemoryEngine
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)


@dataclass
class Reflection:
    """Das Ergebnis einer Nachbetrachtung."""

    task: str
    successful: bool
    problems: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    strategy: str = ""
    duration_seconds: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "successful": self.successful,
            "problems": self.problems,
            "improvements": self.improvements,
            "insights": self.insights,
            "strategy": self.strategy,
            "duration_seconds": round(self.duration_seconds, 3),
            "created_at": self.created_at,
        }

    def as_text(self) -> str:
        """Formuliert die Nachbetrachtung verständlich."""

        lines = [
            f"Aufgabe: {self.task}",
            f"Ergebnis: {'erfolgreich' if self.successful else 'nicht erfolgreich'}",
        ]
        if self.problems:
            lines.append("Aufgetretene Probleme: " + "; ".join(self.problems))
        if self.improvements:
            lines.append("Verbesserungsmöglichkeiten: " + "; ".join(self.improvements))
        if self.insights:
            lines.append("Erkenntnisse: " + "; ".join(self.insights))
        return "\n".join(lines)


class ReflectionEngine:
    """Führt Nachbetrachtungen durch und lernt aus dem Verlauf."""

    def __init__(self, memory: MemoryEngine, filename: str = "reflections.json") -> None:
        config = get_config()
        reflection_config = config.section("reflection")

        self._memory = memory
        self._store = JsonStore(filename, default={"reflections": [], "strategies": {}})
        self._store_insights = bool(reflection_config.get("store_insights", True))
        self._max_history = int(reflection_config.get("max_history", 200))

    def reflect(
        self,
        task: str,
        *,
        successful: bool,
        strategy: str = "",
        duration_seconds: float = 0.0,
        errors: list[str] | None = None,
        used_modules: list[str] | None = None,
    ) -> Reflection:
        """Führt eine Nachbetrachtung durch.

        Args:
            task: Beschreibung der abgeschlossenen Aufgabe.
            successful: Ob die Aufgabe erfolgreich abgeschlossen wurde.
            strategy: Die gewählte Strategie (für das Lernen aus
                Erfolgsquoten).
            duration_seconds: Bearbeitungsdauer.
            errors: Aufgetretene Fehlermeldungen.
            used_modules: Beteiligte Module.

        Returns:
            Die erzeugte Nachbetrachtung.
        """

        problems = list(errors or [])
        improvements: list[str] = []
        insights: list[str] = []

        if not successful:
            improvements.append(
                "Alternative Strategie prüfen, da der bisherige Ablauf nicht zum Ziel führte."
            )
        if duration_seconds > 30.0:
            improvements.append(
                "Bearbeitungsdauer war hoch – Teilschritte könnten parallel laufen."
            )
        if problems:
            improvements.append("Fehlerursachen vor dem nächsten Versuch beheben.")

        if successful and strategy:
            insights.append(f"Strategie „{strategy}“ hat für diese Aufgabenart funktioniert.")

        reflection = Reflection(
            task=task,
            successful=successful,
            problems=problems,
            improvements=improvements,
            insights=insights,
            strategy=strategy,
            duration_seconds=duration_seconds,
        )

        self._record(reflection, used_modules or [])
        return reflection

    def _record(self, reflection: Reflection, used_modules: list[str]) -> None:
        """Legt die Nachbetrachtung ab und aktualisiert die Strategiestatistik."""

        entries = list(self._store.get("reflections", []) or [])
        entries.append({**reflection.to_dict(), "modules": used_modules})
        if len(entries) > self._max_history:
            entries = entries[-self._max_history :]

        strategies = dict(self._store.get("strategies", {}) or {})
        if reflection.strategy:
            record = dict(
                strategies.get(reflection.strategy, {"attempts": 0, "successes": 0})
            )
            record["attempts"] = int(record.get("attempts", 0)) + 1
            if reflection.successful:
                record["successes"] = int(record.get("successes", 0)) + 1
            strategies[reflection.strategy] = record

        self._store.update({"reflections": entries, "strategies": strategies})

        # Nur sachliche, aufgabenbezogene Erkenntnisse langfristig sichern.
        if self._store_insights:
            for insight in reflection.insights:
                self._memory.remember(
                    insight,
                    kind="knowledge",
                    tags=["erkenntnis", "ablauf"],
                    source="reflexion",
                    certainty="annahme",
                    force=True,
                )

    def strategy_success_rate(self, strategy: str) -> float:
        """Erfolgsquote einer Strategie (0.0 bis 1.0)."""

        record = (self._store.get("strategies", {}) or {}).get(strategy)
        if not record:
            return 0.5  # Keine Daten: neutrale Annahme.
        attempts = int(record.get("attempts", 0))
        if attempts == 0:
            return 0.5
        return int(record.get("successes", 0)) / attempts

    def best_strategies(self, limit: int = 5) -> list[tuple[str, float]]:
        """Die Strategien mit der höchsten Erfolgsquote."""

        strategies = self._store.get("strategies", {}) or {}
        rated = [
            (name, self.strategy_success_rate(name))
            for name, record in strategies.items()
            if int(record.get("attempts", 0)) >= 2
        ]
        rated.sort(key=lambda item: item[1], reverse=True)
        return rated[:limit]

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Die zuletzt durchgeführten Nachbetrachtungen."""

        return list(self._store.get("reflections", []) or [])[-limit:]

    def clear(self) -> None:
        """Löscht alle gespeicherten Nachbetrachtungen (Transparenzanforderung)."""

        self._store.clear()
