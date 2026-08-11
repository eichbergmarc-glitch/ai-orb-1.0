"""Multi-Agent-System von AI-Orb (v3 Phase 5).

Der Orb besteht intern aus einem koordinierten Team spezialisierter
Agenten. Jeder Agent besitzt eine klar definierte Aufgabe, eine eindeutige
API, einen eigenen Arbeitskontext sowie klare Ein- und Ausgaben.

Es gibt keine unkontrollierte Kommunikation zwischen Agenten: Jede
Koordination läuft über den Agent Manager und damit über das Cognitive
Core. Der Benutzer spricht weiterhin mit nur einer Persönlichkeit – dem Orb.
"""

from backend.agents.agent_manager import AgentManager
from backend.agents.agent_metrics import AgentMetrics, AgentStats
from backend.agents.agent_registry import AgentRegistry
from backend.agents.agent_router import AgentRouter, RoutingPlan
from backend.agents.agent_scheduler import AgentScheduler
from backend.agents.base_agent import AgentResult, AgentTask, BaseAgent
from backend.agents.capability_registry import CapabilityRegistry, PERMISSIONS
from backend.agents.result_merger import MergedAnswer, ResultMerger
from backend.agents.task_dispatcher import DispatchResult, TaskDispatcher

__all__ = [
    "AgentManager",
    "AgentMetrics",
    "AgentRegistry",
    "AgentResult",
    "AgentRouter",
    "AgentScheduler",
    "AgentStats",
    "AgentTask",
    "BaseAgent",
    "CapabilityRegistry",
    "DispatchResult",
    "MergedAnswer",
    "PERMISSIONS",
    "ResultMerger",
    "RoutingPlan",
    "TaskDispatcher",
]
