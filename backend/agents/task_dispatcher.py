"""Task Dispatcher – zerlegt Aufgaben und verteilt sie an Agenten.

Beispiel: "Analysiere diese Hausarbeit und öffne die Quellen."

    → History Agent, Research Agent, Desktop Agent
    → Ergebnisse sammeln
    → zusammenführen
    → der Orb antwortet mit einer Stimme.

Der Dispatcher ist die Klammer um Router, Scheduler und Result Merger.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.agents.agent_metrics import AgentMetrics
from backend.agents.agent_registry import AgentRegistry
from backend.agents.agent_router import AgentRouter, RoutingPlan
from backend.agents.agent_scheduler import AgentScheduler
from backend.agents.base_agent import AgentResult, AgentTask
from backend.agents.result_merger import MergedAnswer, ResultMerger
from backend.cognitive.orchestrator import Distribution
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class DispatchResult:
    """Das Ergebnis einer verteilten Bearbeitung."""

    answer: MergedAnswer
    plan: RoutingPlan
    results: list[AgentResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer.to_dict(),
            "plan": self.plan.to_dict(),
            "results": [result.to_dict() for result in self.results],
            "duration_seconds": round(self.duration_seconds, 3),
        }


class TaskDispatcher:
    """Verteilt Aufgaben an Agenten und führt die Ergebnisse zusammen."""

    def __init__(
        self,
        registry: AgentRegistry,
        router: AgentRouter,
        scheduler: AgentScheduler,
        merger: ResultMerger,
        metrics: AgentMetrics,
        *,
        max_parallel: int = 4,
    ) -> None:
        self._registry = registry
        self._router = router
        self._scheduler = scheduler
        self._merger = merger
        self._metrics = metrics
        self._max_parallel = max_parallel
        self._last_plan: RoutingPlan | None = None

    async def dispatch(
        self,
        distribution: Distribution,
        *,
        text: str,
        context: str = "",
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DispatchResult:
        """Verteilt eine Aufgabe an die zuständigen Agenten.

        Args:
            distribution: Die Aufgabenverteilung des Cognitive Core.
            text: Die ursprüngliche Benutzereingabe.
            context: Zusätzlicher Kontext für alle Agenten.
            project_id: Aktives Projekt.
            metadata: Zusatzdaten (z. B. Desktop-Aktion und Ziel).

        Returns:
            Das zusammengeführte Ergebnis samt Ausführungsplan.
        """

        started = time.perf_counter()

        plan = self._router.plan(
            distribution,
            available_agents=self._registry.names(),
            max_parallel=self._max_parallel,
        )
        self._last_plan = plan

        task = AgentTask(
            text=text,
            context=context,
            project_id=project_id,
            metadata=dict(metadata or {}),
        )

        results = await self._scheduler.execute(plan, task)
        answer = self._merger.merge(results)

        duration = time.perf_counter() - started
        logger.info(
            "Aufgabe von %d Agent(en) bearbeitet in %.2f s.", len(results), duration
        )

        return DispatchResult(
            answer=answer, plan=plan, results=results, duration_seconds=duration
        )

    def explain_last(self) -> dict[str, Any]:
        """Erklärt die letzte Agentenverteilung.

        Beantwortet die Transparenzfragen "Welche Agenten hast du genutzt?",
        "Warum?" und "Welche Aufgabe hatte jeder Agent?" – verständlich und
        nicht technisch überladen.
        """

        if self._last_plan is None:
            return {"available": False, "message": "Es wurde noch keine Aufgabe verteilt."}

        descriptions: dict[str, str] = {}
        for name in self._last_plan.agents:
            agent = self._registry.get(name)
            if agent is not None:
                descriptions[name] = agent.description

        return {
            "available": True,
            "beteiligte_bereiche": self._last_plan.agents,
            "aufgaben": descriptions,
            "begründung": self._last_plan.reason,
            "parallel_gearbeitet": self._last_plan.has_parallel,
        }
