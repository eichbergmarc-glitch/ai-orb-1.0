"""Orchestrator-Schicht von AI-Orb (v2 Phase 4).

Enthält den Orchestrator, die Intent-Klassifikation, das Task-Routing, die
Gesprächsverwaltung sowie den AI Provider Manager mit automatischer
Umschaltung zwischen dem netzbasierten Primärmodell und dem lokalen
Offline-Fallback.
"""

from backend.orchestrator.conversation_manager import Conversation, ConversationManager
from backend.orchestrator.intent_classifier import (
    IntentClassifier,
    IntentDefinition,
    IntentResult,
)
from backend.orchestrator.orchestrator import Orchestrator, OrchestrationResult
from backend.orchestrator.provider_health import ProviderHealth
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.task_router import RouteResult, TaskRouter

__all__ = [
    "Conversation",
    "ConversationManager",
    "IntentClassifier",
    "IntentDefinition",
    "IntentResult",
    "OrchestrationResult",
    "Orchestrator",
    "ProviderHealth",
    "ProviderManager",
    "RouteResult",
    "TaskRouter",
]
