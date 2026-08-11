"""Arbeitsabläufe (Phase 19).

Ein Workflow ist eine gespeicherte Folge von Werkzeugaufrufen, die sich mit
einem Satz auslösen lässt. Er ist anhaltbar, abbrechbar, und jeder Schritt
läuft über die Sicherheitsschicht – ein Ablauf kann nichts, was ein
Werkzeug nicht darf.
"""

from backend.workflows.workflow import (
    OnError,
    RunState,
    StepResult,
    Workflow,
    WorkflowRun,
    WorkflowStep,
    evaluate_condition,
    resolve_placeholders,
)
from backend.workflows.workflow_engine import WorkflowEngine

__all__ = [
    "OnError",
    "RunState",
    "StepResult",
    "Workflow",
    "WorkflowEngine",
    "WorkflowRun",
    "WorkflowStep",
    "evaluate_condition",
    "resolve_placeholders",
]
