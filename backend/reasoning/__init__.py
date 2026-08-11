"""Reasoning-, Planning- und Decision-Schicht von AI-Orb (v3 Phase 2).

Der Orb beantwortet Aufgaben nicht impulsiv: Er analysiert, plant,
entscheidet, prüft, führt aus und reflektiert. Alle Module dieser Schicht
werden ausschließlich über das Cognitive Core angesprochen.
"""

from backend.reasoning.confidence_estimator import ConfidenceEstimator, ConfidenceResult
from backend.reasoning.decision_tree import DecisionTree, TreeDecision
from backend.reasoning.execution_manager import ExecutionManager, ExecutionReport
from backend.reasoning.plan_generator import PlanGenerator
from backend.reasoning.reasoning_engine import ReasoningEngine, ReasoningResult
from backend.reasoning.reflection_manager import ExecutionTrace, ReflectionManager
from backend.reasoning.strategy_selector import StrategySelection, StrategySelector
from backend.reasoning.task_analyzer import TaskAnalyzer, TaskProfile
from backend.reasoning.verification_engine import VerificationEngine, VerificationReport

__all__ = [
    "ConfidenceEstimator",
    "ConfidenceResult",
    "DecisionTree",
    "ExecutionManager",
    "ExecutionReport",
    "ExecutionTrace",
    "PlanGenerator",
    "ReasoningEngine",
    "ReasoningResult",
    "ReflectionManager",
    "StrategySelection",
    "StrategySelector",
    "TaskAnalyzer",
    "TaskProfile",
    "TreeDecision",
    "VerificationEngine",
    "VerificationReport",
]
