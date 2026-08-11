"""Sprachmodell-Schicht von AI-Orb (Phasen 3, 17 und 20).

Hier liegt alles, was mit dem Sprachmodell selbst zu tun hat. Die Vorgabe
verlangt ausdrücklich, dass es **nur einen** zentralen ProviderManager gibt
und keine doppelte Anbieterlogik – deshalb ist dieses Paket die eine
Anlaufstelle:

* :mod:`backend.ai.provider_registry` – welche Anbieter es gibt.
* :mod:`backend.ai.provider_factory` – wie einer aus der Konfiguration
  entsteht, samt Prüfung.
* :mod:`backend.ai.response_pipeline` – wie eine Anfrage abläuft, sodass
  niemals eine leere Antwort herauskommt.
* :data:`ProviderManager` – die Auswahl und Umschaltung zur Laufzeit. Sie
  liegt weiterhin unter :mod:`backend.orchestrator.provider_manager`; hier
  steht sie zusätzlich zur Verfügung, damit alle Anlaufpunkte an einem Ort
  sind.
"""

from backend.ai.provider_factory import BuildResult, ProviderFactory, build_provider
from backend.ai.provider_registry import (
    ProviderInfo,
    ProviderRegistry,
    get_provider_registry,
)
from backend.ai.response_pipeline import (
    INVALID_ANSWERS,
    Attempt,
    PipelineResult,
    ResponsePipeline,
    is_valid_answer,
)
from backend.orchestrator.provider_manager import ProviderManager
from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)

__all__ = [
    "INVALID_ANSWERS",
    "Attempt",
    "BaseProvider",
    "BuildResult",
    "ChatMessage",
    "PipelineResult",
    "ProviderError",
    "ProviderFactory",
    "ProviderInfo",
    "ProviderManager",
    "ProviderRegistry",
    "ProviderResponse",
    "ResponsePipeline",
    "build_provider",
    "get_provider_registry",
    "is_valid_answer",
]
