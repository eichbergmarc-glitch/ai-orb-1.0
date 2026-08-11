"""Cognitive Core von AI-Orb (v3 Phase 1).

Das Cognitive Core ist das zentrale Gehirn: Alle anderen Module
kommunizieren ausschließlich über es. Es verwaltet mehrere Ebenen des
Wissens (Working Memory, Long Term Memory), mehrere gleichzeitig aktive
Kontexte, Ziele, Aufgaben und Projekte – und entscheidet, welche Module,
welcher Kontext und welches Modell für eine Anfrage benötigt werden.
"""

from backend.cognitive.cognitive_core import CognitiveCore, CognitiveResponse
from backend.cognitive.context_manager import Context, ContextManager
from backend.cognitive.decision_engine import Decision, DecisionEngine
from backend.cognitive.goal_manager import GoalManager
from backend.cognitive.long_term_memory import LongTermMemory
from backend.cognitive.orchestrator import CognitiveOrchestrator, Distribution, SubTask
from backend.cognitive.planner import Plan, Planner, PlanStep
from backend.cognitive.project_manager import ProjectManager
from backend.cognitive.reasoning_context import ContextItem, ReasoningContext
from backend.cognitive.reflection_engine import Reflection, ReflectionEngine
from backend.cognitive.task_manager import TaskManager
from backend.cognitive.working_memory import WorkingMemory

__all__ = [
    "CognitiveCore",
    "CognitiveOrchestrator",
    "CognitiveResponse",
    "Context",
    "ContextItem",
    "ContextManager",
    "Decision",
    "DecisionEngine",
    "Distribution",
    "GoalManager",
    "LongTermMemory",
    "Plan",
    "PlanStep",
    "Planner",
    "ProjectManager",
    "ReasoningContext",
    "Reflection",
    "ReflectionEngine",
    "SubTask",
    "TaskManager",
    "WorkingMemory",
]
