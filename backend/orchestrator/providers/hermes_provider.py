"""Hermes-Provider – primäres, netzbasiertes Sprachmodell.

Der Provider spricht eine OpenAI-kompatible ``/chat/completions``-API an.
Basis-URL, Modellname und Zeitlimit stammen ausschließlich aus
``config.yaml``; der API-Schlüssel wird aus der Umgebungsvariablen gelesen,
die in ``config.yaml`` benannt ist (Standard: ``HERMES_API_KEY``), damit
keine Zugangsdaten im Quellcode oder in der Konfiguration stehen.
"""

from __future__ import annotations

import os
from typing import Any

from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class HermesProvider(BaseProvider):
    """Netzbasierter Provider mit OpenAI-kompatibler Schnittstelle."""

    name = "hermes"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._base_url = str(settings.get("base_url", "")).rstrip("/")
        self._api_key_env = str(settings.get("api_key_env", "HERMES_API_KEY"))

    @property
    def api_key(self) -> str:
        """Liest den API-Schlüssel aus der konfigurierten Umgebungsvariablen."""

        return os.environ.get(self._api_key_env, "").strip()

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        key = self.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        referer = self._settings.get("http_referer")
        if referer:
            headers["HTTP-Referer"] = str(referer)
        title = self._settings.get("app_title")
        if title:
            headers["X-Title"] = str(title)
        return headers

    async def is_available(self) -> bool:
        """Prüft die Erreichbarkeit der Hermes-API.

        Ohne hinterlegten API-Schlüssel oder ohne konfigurierte Basis-URL
        gilt der Provider als nicht verfügbar; AI-Orb wechselt dann
        automatisch auf den lokalen Fallback.
        """

        if not self._base_url or not self.api_key:
            return False
        try:
            await self._request_json(
                f"{self._base_url}/models",
                method="GET",
                headers=self._headers(),
                timeout=min(self._timeout, 8.0),
            )
            return True
        except ProviderError as error:
            logger.debug("Hermes nicht erreichbar: %s", error)
            return False

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Führt eine Chat-Anfrage gegen die Hermes-API aus."""

        if not self._base_url:
            raise ProviderError("hermes: keine base_url konfiguriert.")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [message.to_dict() for message in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        started = self._now()
        data = await self._request_json(
            f"{self._base_url}/chat/completions",
            payload=payload,
            headers=self._headers(),
        )
        latency = self._now() - started

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("hermes: Antwort enthält keine Auswahl.")

        first = choices[0]
        text = str((first.get("message") or {}).get("content", "")).strip()

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self._model,
            latency_seconds=latency,
            finish_reason=first.get("finish_reason"),
            raw=data,
        )
