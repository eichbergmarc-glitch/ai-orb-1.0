"""Verzeichnis der verfügbaren Sprachmodell-Anbieter (Phase 20).

Hält fest, welche Anbietertypen es gibt, und ist damit die eine Stelle, an
der ein neuer Anbieter angemeldet wird. Vorher war das über den Code
verstreut; die Vorgabe verlangt ausdrücklich, dass es **keine doppelte
Provider-Logik** gibt.

Die Trennung von Verzeichnis und Fabrik ist Absicht: Das Verzeichnis weiß,
*welche* Anbieter es gibt, die Fabrik weiß, *wie* einer aus einem
Konfigurationsabschnitt entsteht. Wer einen Anbieter ergänzt, meldet ihn
hier an und muss die Fabrik nicht anfassen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.orchestrator.providers.base_provider import BaseProvider
from backend.orchestrator.providers.claude_code_provider import ClaudeCodeProvider
from backend.orchestrator.providers.claude_provider import ClaudeProvider
from backend.orchestrator.providers.hermes_provider import HermesProvider
from backend.orchestrator.providers.ollama_provider import OllamaProvider
from backend.orchestrator.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProviderInfo:
    """Was über einen Anbietertyp bekannt ist."""

    name: str
    provider_class: type[BaseProvider]
    #: Für den Benutzer verständliche Beschreibung.
    description: str
    #: Ob eine Internetverbindung nötig ist.
    requires_internet: bool
    #: Ob ein API-Schlüssel gebraucht wird.
    requires_api_key: bool
    #: Wie der Zugang bezahlt wird.
    billing: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "requires_internet": self.requires_internet,
            "requires_api_key": self.requires_api_key,
            "billing": self.billing,
        }


class ProviderRegistry:
    """Verwaltet die bekannten Anbietertypen."""

    def __init__(self) -> None:
        self._entries: dict[str, ProviderInfo] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        """Meldet die mitgelieferten Anbieter an."""

        for info in (
            ProviderInfo(
                name="claude_code",
                provider_class=ClaudeCodeProvider,
                description=(
                    "Claude über die lokal angemeldete Claude-Code-Befehlszeile. "
                    "Nutzt dein Pro- oder Max-Abonnement, kein API-Schlüssel nötig."
                ),
                requires_internet=True,
                requires_api_key=False,
                billing="Im Abonnement enthalten",
            ),
            ProviderInfo(
                name="claude",
                provider_class=ClaudeProvider,
                description=(
                    "Claude über die Messages-API. Verlangt einen API-Schlüssel "
                    "und wird getrennt vom Abonnement abgerechnet."
                ),
                requires_internet=True,
                requires_api_key=True,
                billing="Nach Verbrauch über console.anthropic.com",
            ),
            ProviderInfo(
                name="ollama",
                provider_class=OllamaProvider,
                description=(
                    "Ein lokal laufendes Modell über Ollama. Braucht kein "
                    "Internet und kostet nichts, verlangt aber Arbeitsspeicher."
                ),
                requires_internet=False,
                requires_api_key=False,
                billing="Kostenlos, läuft auf deinem Rechner",
            ),
            ProviderInfo(
                name="hermes",
                provider_class=HermesProvider,
                description=(
                    "Ein OpenAI-kompatibler Dienst, etwa OpenRouter. Verlangt "
                    "einen API-Schlüssel."
                ),
                requires_internet=True,
                requires_api_key=True,
                billing="Je nach Anbieter",
            ),
            # --- Mit dem Master-Prompt ergaenzt (Abschnitte 7, 8, 9) ---------
            #
            # Alle vier sprechen dieselbe OpenAI-kompatible API und teilen
            # sich deshalb eine Klasse. Der Unterschied steckt allein im
            # 'preset' der Konfiguration.
            ProviderInfo(
                name="openai",
                provider_class=OpenAICompatibleProvider,
                description=(
                    "OpenAI ueber die offizielle API. Verlangt einen "
                    "API-Schluessel (OPENAI_API_KEY) und wird nach Verbrauch "
                    "abgerechnet."
                ),
                requires_internet=True,
                requires_api_key=True,
                billing="Nach Verbrauch ueber platform.openai.com",
            ),
            ProviderInfo(
                name="ollama_cloud",
                provider_class=OpenAICompatibleProvider,
                description=(
                    "Ollama Cloud: staerkere Modelle als lokal, ueber einen "
                    "Schluessel (OLLAMA_API_KEY)."
                ),
                requires_internet=True,
                requires_api_key=True,
                billing="Nach Verbrauch ueber ollama.com",
            ),
            ProviderInfo(
                name="lmstudio",
                provider_class=OpenAICompatibleProvider,
                description=(
                    "LM Studio: ein lokaler Modellserver mit Oberflaeche. "
                    "Braucht kein Internet und keinen Schluessel."
                ),
                requires_internet=False,
                requires_api_key=False,
                billing="Kostenlos, laeuft auf deinem Rechner",
            ),
            ProviderInfo(
                name="llamacpp",
                provider_class=OpenAICompatibleProvider,
                description=(
                    "llama.cpp im Servermodus. Genuegsam, lokal, ohne "
                    "Schluessel."
                ),
                requires_internet=False,
                requires_api_key=False,
                billing="Kostenlos, laeuft auf deinem Rechner",
            ),
        ):
            self.register(info)

    # --- Anmeldung ------------------------------------------------------------------

    def register(self, info: ProviderInfo) -> bool:
        """Meldet einen Anbietertyp an.

        Returns:
            ``True``, wenn er aufgenommen wurde.
        """

        name = info.name.strip().lower()
        if not name:
            return False

        if name in self._entries:
            logger.warning("Der Anbietertyp '%s' ist bereits angemeldet.", name)
            return False

        if not issubclass(info.provider_class, BaseProvider):
            logger.error(
                "Der Anbietertyp '%s' erbt nicht von BaseProvider und wurde "
                "abgewiesen.",
                name,
            )
            return False

        self._entries[name] = info
        return True

    def unregister(self, name: str) -> bool:
        """Meldet einen Anbietertyp ab."""

        return self._entries.pop(name.strip().lower(), None) is not None

    # --- Zugriff --------------------------------------------------------------------

    def get(self, name: str) -> ProviderInfo | None:
        """Sucht einen Anbietertyp."""

        return self._entries.get(name.strip().lower())

    def provider_class(self, name: str) -> type[BaseProvider] | None:
        """Die Klasse eines Anbietertyps."""

        info = self.get(name)
        return info.provider_class if info else None

    def names(self) -> list[str]:
        """Die Namen aller bekannten Anbietertypen."""

        return sorted(self._entries)

    def offline_capable(self) -> list[str]:
        """Die Anbieter, die ohne Internet arbeiten."""

        return sorted(
            name for name, info in self._entries.items() if not info.requires_internet
        )

    def catalog(self) -> list[dict[str, Any]]:
        """Alle Anbietertypen, für die Transparenzansicht."""

        return [info.to_dict() for _, info in sorted(self._entries.items())]

    def describe(self, name: str) -> str:
        """Beschreibt einen Anbietertyp im Klartext."""

        info = self.get(name)
        if info is None:
            return (
                f"'{name}' ist kein bekannter Anbieter. Bekannt sind: "
                + ", ".join(self.names())
            )

        parts = [info.description]
        if info.requires_api_key:
            parts.append("Ein API-Schlüssel ist nötig; er gehört in die Datei .env.")
        if not info.requires_internet:
            parts.append("Läuft ohne Internetverbindung.")
        if info.billing:
            parts.append(f"Abrechnung: {info.billing}")
        return " ".join(parts)

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return str(name).strip().lower() in self._entries


#: Das prozessweite Verzeichnis.
_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Gibt das prozessweite Anbieterverzeichnis zurück."""

    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
