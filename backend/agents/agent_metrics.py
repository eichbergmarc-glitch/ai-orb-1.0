"""Agent Metrics – interne Kennzahlen der Agenten.

Erfasst Bearbeitungszeit, Fehlerraten, Erfolgsquote und Nutzungshäufigkeit.
Diese Daten dienen ausschließlich der Optimierung und werden transparent
dokumentiert: Der Benutzer kann sie jederzeit einsehen und löschen.

Es werden keine Inhalte gespeichert, nur Kennzahlen.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from backend.utils.store import JsonStore


@dataclass
class AgentStats:
    """Kennzahlen eines einzelnen Agenten."""

    name: str
    invocations: int = 0
    successes: int = 0
    failures: int = 0
    total_duration: float = 0.0
    last_used_at: float = 0.0
    durations: list[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Erfolgsquote (0.0 bis 1.0)."""

        if self.invocations == 0:
            return 0.0
        return self.successes / self.invocations

    @property
    def error_rate(self) -> float:
        """Fehlerrate (0.0 bis 1.0)."""

        if self.invocations == 0:
            return 0.0
        return self.failures / self.invocations

    @property
    def average_duration(self) -> float:
        """Durchschnittliche Bearbeitungszeit in Sekunden."""

        if not self.durations:
            return 0.0
        return sum(self.durations) / len(self.durations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "invocations": self.invocations,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 3),
            "error_rate": round(self.error_rate, 3),
            "average_duration": round(self.average_duration, 3),
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentStats":
        stats = cls(name=str(data.get("name", "")))
        stats.invocations = int(data.get("invocations", 0))
        stats.successes = int(data.get("successes", 0))
        stats.failures = int(data.get("failures", 0))
        stats.last_used_at = float(data.get("last_used_at", 0.0))
        stats.durations = [float(data.get("average_duration", 0.0))] if data.get("average_duration") else []
        return stats


class AgentMetrics:
    """Sammelt und speichert Agenten-Kennzahlen."""

    def __init__(self, filename: str = "agent_metrics.json") -> None:
        self._store = JsonStore(filename, default={"agents": {}})
        self._lock = threading.RLock()
        self._stats: dict[str, AgentStats] = {}
        for name, data in (self._store.get("agents", {}) or {}).items():
            self._stats[name] = AgentStats.from_dict({**data, "name": name})

    def record(self, name: str, *, success: bool, duration: float) -> None:
        """Erfasst einen Agentenaufruf."""

        with self._lock:
            stats = self._stats.setdefault(name, AgentStats(name=name))
            stats.invocations += 1
            if success:
                stats.successes += 1
            else:
                stats.failures += 1
            stats.total_duration += duration
            stats.durations.append(duration)
            if len(stats.durations) > 100:
                stats.durations.pop(0)
            stats.last_used_at = time.time()
        self._persist()

    def _persist(self) -> None:
        with self._lock:
            payload = {name: stats.to_dict() for name, stats in self._stats.items()}
        self._store.set("agents", payload)

    def get(self, name: str) -> AgentStats | None:
        """Kennzahlen eines Agenten."""

        with self._lock:
            return self._stats.get(name)

    def snapshot(self) -> dict[str, Any]:
        """Alle Kennzahlen (Transparenzansicht)."""

        with self._lock:
            return {name: stats.to_dict() for name, stats in self._stats.items()}

    def most_used(self, limit: int = 5) -> list[tuple[str, int]]:
        """Die am häufigsten genutzten Agenten."""

        with self._lock:
            ranked = sorted(
                ((name, stats.invocations) for name, stats in self._stats.items()),
                key=lambda item: item[1],
                reverse=True,
            )
        return ranked[:limit]

    def reset(self) -> None:
        """Löscht alle erfassten Kennzahlen."""

        with self._lock:
            self._stats.clear()
        self._store.clear()
