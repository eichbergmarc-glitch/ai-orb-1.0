"""Claude-Provider über die Anthropic Messages API.

Dieser Provider spricht Claude direkt über die offizielle API an. Er
benötigt einen **API-Schlüssel** von ``console.anthropic.com`` – ein
Claude-Abonnement (Pro oder Max) genügt dafür **nicht**, da API-Nutzung
getrennt abgerechnet wird.

Wer sein Abonnement nutzen möchte, verwendet stattdessen
:class:`~backend.orchestrator.providers.claude_code_provider.ClaudeCodeProvider`.

Der Modellname wird ausschließlich aus ``config.yaml`` gelesen. Steht dort
``auto``, ermittelt der Provider das aktuell neueste passende Modell selbst
– so bleibt die Einstellung gültig, auch wenn Anthropic neue Modelle
veröffentlicht.
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

#: Version der Messages-API, gegen die dieser Provider arbeitet.
_API_VERSION = "2023-06-01"

#: Reihenfolge, in der bei ``model: auto`` nach einem Modell gesucht wird.
_MODEL_PREFERENCE: tuple[str, ...] = ("sonnet", "opus", "haiku")


class ClaudeProvider(BaseProvider):
    """Netzbasierter Provider für die Anthropic Messages API."""

    name = "claude"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._base_url = str(settings.get("base_url", "https://api.anthropic.com")).rstrip("/")
        self._api_key_env = str(settings.get("api_key_env", "ANTHROPIC_API_KEY"))
        self._max_tokens = int(settings.get("max_tokens", 4096))
        self._fallback_model = str(settings.get("fallback_model", "claude-sonnet-4-5"))
        self._resolved_model: str | None = None

    @property
    def api_key(self) -> str:
        """Liest den API-Schlüssel aus der konfigurierten Umgebungsvariablen."""

        return os.environ.get(self._api_key_env, "").strip()

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    # --- Modellwahl ------------------------------------------------------------

    async def _resolve_model(self) -> str:
        """Ermittelt den zu verwendenden Modellnamen.

        Ist in ``config.yaml`` ein konkretes Modell eingetragen, wird dieses
        verwendet. Steht dort ``auto`` (oder nichts), fragt der Provider die
        verfügbaren Modelle ab und wählt das neueste bevorzugte.
        """

        configured = self._model.strip()
        if configured and configured.lower() != "auto":
            return configured

        if self._resolved_model is not None:
            return self._resolved_model

        try:
            data = await self._request_json(
                f"{self._base_url}/v1/models?limit=100",
                method="GET",
                headers=self._headers(),
                timeout=min(self._timeout, 15.0),
            )
        except ProviderError as error:
            logger.warning(
                "Modelliste konnte nicht abgefragt werden (%s); nutze '%s'.",
                error,
                self._fallback_model,
            )
            self._resolved_model = self._fallback_model
            return self._resolved_model

        entries = [entry for entry in (data.get("data") or []) if isinstance(entry, dict)]
        identifiers = [str(entry.get("id", "")) for entry in entries if entry.get("id")]

        for preference in _MODEL_PREFERENCE:
            matches = [name for name in identifiers if preference in name.lower()]
            if matches:
                # Die API liefert die neuesten Modelle zuerst.
                self._resolved_model = matches[0]
                logger.info("Claude-Modell automatisch gewählt: %s", self._resolved_model)
                return self._resolved_model

        self._resolved_model = identifiers[0] if identifiers else self._fallback_model
        return self._resolved_model

    # --- Verfügbarkeit ------------------------------------------------------------

    async def is_available(self) -> bool:
        """Prüft, ob ein Schlüssel hinterlegt und die API erreichbar ist."""

        if not self.api_key:
            logger.debug("Kein API-Schlüssel in %s hinterlegt.", self._api_key_env)
            return False

        try:
            await self._request_json(
                f"{self._base_url}/v1/models?limit=1",
                method="GET",
                headers=self._headers(),
                timeout=min(self._timeout, 10.0),
            )
            return True
        except ProviderError as error:
            message = str(error)
            if "HTTP 401" in message or "HTTP 403" in message:
                logger.warning(
                    "Der Anthropic-API-Schlüssel wurde abgelehnt. Prüfe %s in deiner .env.",
                    self._api_key_env,
                )
                return False
            logger.debug("Anthropic-API nicht erreichbar: %s", error)
            return False

    # --- Anfragen --------------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Führt eine Chat-Anfrage gegen die Messages API aus."""

        if not self.api_key:
            raise ProviderError(
                f"claude: Es ist kein API-Schlüssel hinterlegt. Trage ihn als "
                f"{self._api_key_env} in die Datei .env ein – oder nutze den "
                "Provider 'claude_code', wenn du dein Abonnement verwenden möchtest."
            )

        system_prompt, dialogue = self._split_messages(messages)
        model = await self._resolve_model()

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self._max_tokens,
            "messages": dialogue,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if temperature is not None:
            payload["temperature"] = temperature

        started = self._now()
        try:
            data = await self._request_json(
                f"{self._base_url}/v1/messages",
                payload=payload,
                headers=self._headers(),
            )
        except ProviderError as error:
            raise ProviderError(self._explain_failure(str(error))) from error
        latency = self._now() - started

        blocks = data.get("content") or []
        texts = [
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(part for part in texts if part).strip()

        if not text:
            raise ProviderError("claude: Die Antwort enthielt keinen Text.")

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=model,
            latency_seconds=latency,
            finish_reason=data.get("stop_reason"),
            raw={"usage": data.get("usage", {})},
        )

    # --- Hilfsfunktionen ------------------------------------------------------------

    @staticmethod
    def _split_messages(
        messages: list[ChatMessage],
    ) -> tuple[str, list[dict[str, str]]]:
        """Trennt Systemtext vom Verlauf und bringt diesen in gültige Form.

        Die Messages API erwartet den Systemtext als eigenes Feld, einen
        Verlauf, der mit einer Benutzernachricht beginnt, und keine zwei
        aufeinanderfolgenden Nachrichten derselben Rolle. Beides wird hier
        sichergestellt.
        """

        system_parts = [
            message.content.strip()
            for message in messages
            if message.role == "system" and message.content.strip()
        ]

        dialogue: list[dict[str, str]] = []
        for message in messages:
            if message.role == "system":
                continue
            content = message.content.strip()
            if not content:
                continue
            role = "assistant" if message.role == "assistant" else "user"

            if dialogue and dialogue[-1]["role"] == role:
                # Aufeinanderfolgende gleiche Rollen zusammenfassen.
                dialogue[-1]["content"] += f"\n\n{content}"
            else:
                dialogue.append({"role": role, "content": content})

        # Der Verlauf muss mit einer Benutzernachricht beginnen.
        while dialogue and dialogue[0]["role"] != "user":
            dialogue.pop(0)

        if not dialogue:
            dialogue = [{"role": "user", "content": "Bitte antworte kurz."}]

        return "\n\n".join(system_parts), dialogue

    @staticmethod
    def _explain_failure(message: str) -> str:
        """Übersetzt API-Fehler in verständlichen Klartext."""

        if "HTTP 401" in message or "HTTP 403" in message:
            return (
                "claude: Der API-Schlüssel wurde abgelehnt. Prüfe ihn in der Datei "
                ".env. Wichtig: Ein Claude-Abonnement (Pro/Max) ist kein "
                "API-Schlüssel – für die API brauchst du Guthaben auf "
                "console.anthropic.com."
            )
        if "HTTP 429" in message:
            return (
                "claude: Zu viele Anfragen oder das API-Guthaben ist aufgebraucht. "
                "Ich wechsle auf das lokale Modell."
            )
        if "HTTP 400" in message and "max_tokens" in message:
            return "claude: Die Antwortlänge überschreitet das Modelllimit."
        if "HTTP 404" in message:
            return (
                "claude: Das eingestellte Modell existiert nicht. Trage in "
                "config.yaml unter ai.primary.model 'auto' ein, dann wähle ich "
                "selbst ein passendes Modell."
            )
        return message
