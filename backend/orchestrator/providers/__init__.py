"""KI-Provider von AI-Orb.

Alle Provider implementieren dieselbe Basisschnittstelle
(:class:`~backend.orchestrator.providers.base_provider.BaseProvider`).
Neue Provider können ergänzt werden, ohne den Orchestrator zu verändern:
Sie werden lediglich in :data:`PROVIDER_TYPES` registriert und in
``config.yaml`` konfiguriert.

Verfügbare Provider:

``claude_code``
    Claude über die lokal angemeldete Claude-Code-Befehlszeile. Nutzt ein
    **Abonnement** (Pro oder Max) und benötigt keinen API-Schlüssel.

``claude``
    Claude über die Anthropic Messages API. Benötigt einen **API-Schlüssel**
    mit eigenem Guthaben.

``ollama``
    Lokales Modell ohne Internet – der Offline-Rückfall.

``hermes``
    OpenAI-kompatibler Dienst (z. B. OpenRouter). Bleibt erhalten, ist aber
    nicht mehr voreingestellt.
"""

from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider
from backend.orchestrator.providers.claude_provider import ClaudeProvider
from backend.orchestrator.providers.hermes_provider import HermesProvider
from backend.orchestrator.providers.ollama_provider import OllamaProvider
from backend.orchestrator.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)

#: Registry aller bekannten Provider-Typen. Der Schlüssel entspricht dem
#: Wert von ``engine`` in ``config.yaml``.
PROVIDER_TYPES: dict[str, type[BaseProvider]] = {
    ClaudeCodeProvider.name: ClaudeCodeProvider,
    ClaudeProvider.name: ClaudeProvider,
    OllamaProvider.name: OllamaProvider,
    HermesProvider.name: HermesProvider,
    "openai": OpenAICompatibleProvider,
    "openrouter": OpenAICompatibleProvider,
    "grok": OpenAICompatibleProvider,
    "xai": OpenAICompatibleProvider,
    "ollama_cloud": OpenAICompatibleProvider,
    "lmstudio": OpenAICompatibleProvider,
    "llamacpp": OpenAICompatibleProvider,
}

__all__ = [
    "BaseProvider",
    "ChatMessage",
    "ClaudeCodeProvider",
    "ClaudeProvider",
    "HermesProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "PROVIDER_TYPES",
    "ProviderError",
    "ProviderResponse",
]
