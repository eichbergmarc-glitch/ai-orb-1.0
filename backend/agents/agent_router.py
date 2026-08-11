"""Agent Router – entscheidet, welche Agenten eine Aufgabe bearbeiten.

Vor jeder Aufgabe wird bestimmt:

* Welche Agenten werden benötigt?
* Welche Reihenfolge ist sinnvoll?
* Welche Agenten können parallel arbeiten?

Es werden ausschließlich die tatsächlich notwendigen Agenten aktiviert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.agents.capability_registry import CapabilityRegistry
from backend.cognitive.orchestrator import Distribution
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Agenten, die den Systemzustand verändern und daher nicht parallel
#: ausgeführt werden dürfen.
_SEQUENTIAL_AGENTS: frozenset[str] = frozenset({"desktop", "evolution"})

#: Agenten, deren Ergebnis andere Agenten benötigen; sie laufen zuerst.
_PREPARATORY_AGENTS: tuple[str, ...] = ("memory", "vision")


@dataclass
class RoutingPlan:
    """Der Ausführungsplan für eine Aufgabe."""

    #: Reihenfolge von Gruppen; Agenten innerhalb einer Gruppe laufen parallel.
    stages: list[list[str]] = field(default_factory=list)
    reason: str = ""

    @property
    def agents(self) -> list[str]:
        """Alle beteiligten Agenten in Ausführungsreihenfolge."""

        return [agent for stage in self.stages for agent in stage]

    @property
    def has_parallel(self) -> bool:
        """Ob mindestens eine Stufe parallel ausgeführt wird."""

        return any(len(stage) > 1 for stage in self.stages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": self.stages,
            "agents": self.agents,
            "parallel": self.has_parallel,
            "reason": self.reason,
        }


class AgentRouter:
    """Bestimmt Auswahl, Reihenfolge und Parallelität der Agenten."""

    def __init__(self, capabilities: CapabilityRegistry) -> None:
        self._capabilities = capabilities

    def plan(
        self,
        distribution: Distribution,
        *,
        available_agents: list[str],
        max_parallel: int = 4,
    ) -> RoutingPlan:
        """Erstellt den Ausführungsplan für eine verteilte Aufgabe.

        Args:
            distribution: Die vom Cognitive Core erzeugte Aufgabenverteilung.
            available_agents: Namen aller registrierten Agenten.
            max_parallel: Höchstzahl gleichzeitig arbeitender Agenten.

        Returns:
            Der Ausführungsplan.
        """

        requested: list[str] = []
        for engine in distribution.engines:
            if engine in available_agents and engine not in requested:
                requested.append(engine)

        if not requested:
            requested = ["conversation"] if "conversation" in available_agents else available_agents[:1]

        preparatory = [agent for agent in _PREPARATORY_AGENTS if agent in requested]
        sequential = [agent for agent in requested if agent in _SEQUENTIAL_AGENTS]
        parallel = [
            agent
            for agent in requested
            if agent not in preparatory and agent not in sequential
        ]

        stages: list[list[str]] = []
        if preparatory:
            stages.append(preparatory)
        for index in range(0, len(parallel), max_parallel):
            chunk = parallel[index : index + max_parallel]
            if chunk:
                stages.append(chunk)
        for agent in sequential:
            stages.append([agent])

        if not stages:
            stages = [requested]

        reason = self._explain(stages, preparatory, sequential)
        logger.info("Agenten-Plan: %s", " → ".join("+".join(stage) for stage in stages))
        return RoutingPlan(stages=stages, reason=reason)

    @staticmethod
    def _explain(
        stages: list[list[str]], preparatory: list[str], sequential: list[str]
    ) -> str:
        """Formuliert die Routing-Entscheidung verständlich."""

        parts: list[str] = []
        if preparatory:
            parts.append(
                f"Zuerst {', '.join(preparatory)}, weil deren Ergebnisse von den "
                "übrigen Bereichen benötigt werden."
            )
        parallel_stages = [stage for stage in stages if len(stage) > 1]
        if parallel_stages:
            parts.append(
                "Parallel arbeiten: "
                + "; ".join(", ".join(stage) for stage in parallel_stages)
                + ", da sich diese Bereiche nicht gegenseitig beeinflussen."
            )
        if sequential:
            parts.append(
                f"{', '.join(sequential)} läuft zuletzt und allein, weil dabei der "
                "Systemzustand verändert wird."
            )
        return " ".join(parts) or "Es war nur ein Bereich zuständig."

    def can_handle(self, capability: str) -> list[str]:
        """Alle Agenten, die eine bestimmte Fähigkeit anbieten."""

        return self._capabilities.providers_for(capability)
