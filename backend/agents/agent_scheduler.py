"""Agent Scheduler – führt Agenten gemäß Routing-Plan aus.

Agenten werden nur bei Bedarf gestartet. Parallele Verarbeitung wird
genutzt, wenn sie die Antwortzeit verbessert; nicht benötigte Agenten
werden gar nicht erst geladen.

Fällt ein Agent aus, wird eine Alternative geprüft, der Benutzer informiert
und – wenn sinnvoll – eine Teilantwort geliefert. Stille Fehler gibt es
nicht.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.agents.agent_metrics import AgentMetrics
from backend.agents.agent_registry import AgentRegistry
from backend.agents.agent_router import RoutingPlan
from backend.agents.base_agent import AgentResult, AgentTask
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Ersatzagenten, falls ein Agent ausfällt.
_FALLBACKS: dict[str, tuple[str, ...]] = {
    "history": ("research", "conversation"),
    "research": ("conversation",),
    "coding": ("reasoning", "conversation"),
    "reasoning": ("conversation",),
    "vision": (),
    "voice": (),
    "desktop": (),
    "memory": (),
    "evolution": (),
}


class AgentScheduler:
    """Führt Agenten gemäß Plan aus und erfasst Kennzahlen."""

    def __init__(
        self,
        registry: AgentRegistry,
        metrics: AgentMetrics,
        *,
        timeout_seconds: float = 120.0,
        lazy_start: bool = True,
    ) -> None:
        self._registry = registry
        self._metrics = metrics
        self._timeout = timeout_seconds
        self._lazy_start = lazy_start

    async def execute(self, plan: RoutingPlan, task: AgentTask) -> list[AgentResult]:
        """Führt den Ausführungsplan aus.

        Args:
            plan: Der vom Agent Router erzeugte Plan.
            task: Die Aufgabe, die alle Agenten erhalten.

        Returns:
            Die Ergebnisse aller beteiligten Agenten.
        """

        results: list[AgentResult] = []
        preliminary: list[str] = []

        for stage_index, stage in enumerate(plan.stages):
            # Ergebnisse vorheriger Stufen als Kontext weitergeben.
            stage_context = task.context
            if preliminary:
                stage_context = (stage_context + "\n" + "\n".join(preliminary)).strip()

            stage_tasks = [
                AgentTask(
                    text=task.text,
                    context=stage_context,
                    project_id=task.project_id,
                    order=stage_index,
                    metadata=dict(task.metadata),
                )
                for _ in stage
            ]

            if len(stage) == 1:
                stage_results = [await self._run_one(stage[0], stage_tasks[0])]
            else:
                stage_results = await asyncio.gather(
                    *(
                        self._run_one(name, agent_task)
                        for name, agent_task in zip(stage, stage_tasks)
                    )
                )

            for result in stage_results:
                results.append(result)
                if result.success and result.response.strip():
                    preliminary.append(f"[{result.agent}] {result.response.strip()}")

        return results

    async def _run_one(self, name: str, task: AgentTask) -> AgentResult:
        """Führt einen einzelnen Agenten aus – mit Zeitlimit und Ersatz."""

        agent = self._registry.get(name)
        if agent is None:
            return AgentResult(
                agent=name,
                success=False,
                error="Agent ist nicht registriert.",
                order=task.order,
            )

        try:
            result = await asyncio.wait_for(agent.run(task), timeout=self._timeout)
        except asyncio.TimeoutError:
            logger.warning("Agent '%s' hat das Zeitlimit überschritten.", name)
            result = AgentResult(
                agent=name,
                success=False,
                error=f"Zeitlimit von {self._timeout:.0f} s überschritten.",
                order=task.order,
            )

        self._metrics.record(name, success=result.success, duration=result.duration_seconds)

        if not result.success:
            replacement = await self._try_fallback(name, task)
            if replacement is not None:
                logger.info("Agent '%s' ersetzt durch '%s'.", name, replacement.agent)
                return replacement

        return result

    async def _try_fallback(self, name: str, task: AgentTask) -> AgentResult | None:
        """Versucht, einen ausgefallenen Agenten zu ersetzen."""

        for candidate in _FALLBACKS.get(name, ()):
            agent = self._registry.get(candidate)
            if agent is None:
                continue
            try:
                result = await asyncio.wait_for(agent.run(task), timeout=self._timeout)
            except asyncio.TimeoutError:
                continue
            self._metrics.record(
                candidate, success=result.success, duration=result.duration_seconds
            )
            if result.success:
                result.data["ersetzt_agent"] = name
                return result
        return None

    async def shutdown(self) -> None:
        """Beendet alle gestarteten Agenten."""

        for agent in self._registry.all():
            if agent.is_started:
                await agent.stop()

    def status(self) -> dict[str, Any]:
        """Statusübersicht des Schedulers."""

        return {
            "timeout_seconds": self._timeout,
            "lazy_start": self._lazy_start,
            "running_agents": [
                agent.name for agent in self._registry.all() if agent.is_started
            ],
        }
