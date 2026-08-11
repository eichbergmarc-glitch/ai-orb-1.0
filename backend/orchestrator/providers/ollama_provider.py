"""Ollama-Provider – lokaler Offline-Fallback.

Spricht die native Ollama-API (``/api/chat``, ``/api/tags``) auf dem lokal
laufenden Ollama-Server an. Basis-URL und Modellname stammen ausschließlich
aus ``config.yaml``; es werden keine Daten an externe Dienste übertragen.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

from backend.orchestrator.providers.base_provider import (
    BaseProvider,
    ChatMessage,
    ProviderError,
    ProviderResponse,
)
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class OllamaProvider(BaseProvider):
    """Lokaler Provider auf Basis von Ollama."""

    name = "ollama"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._base_url = str(settings.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        # Das Modell im Arbeitsspeicher halten - sonst laedt Ollama es nach
        # jeder Pause neu, und die erste Offline-Antwort dauert dann lange.
        self._keep_alive = str(settings.get("keep_alive", "30m"))
        # Ein kleineres Modell schweift leichter ab; eine nuechternere
        # Vorgabe haelt es beim Werkzeugformat.
        roh = settings.get("temperature")
        self._temperatur = float(roh) if roh is not None else 0.4

    async def is_available(self) -> bool:
        """Prüft, ob der Ollama-Server läuft und das Modell geladen werden kann."""

        try:
            data = await self._request_json(
                f"{self._base_url}/api/tags",
                method="GET",
                timeout=min(self._timeout, 5.0),
            )
        except ProviderError as error:
            logger.debug("Ollama nicht erreichbar: %s", error)
            return False

        models = data.get("models") or []
        available_names = {str(entry.get("name", "")) for entry in models if isinstance(entry, dict)}

        if not self._model:
            return bool(available_names)

        # Ollama führt Modelle teils mit, teils ohne Tag-Suffix.
        base_name = self._model.split(":")[0]
        if self._model in available_names:
            return True
        if any(name.split(":")[0] == base_name for name in available_names):
            return True

        logger.warning(
            "Ollama läuft, aber Modell '%s' ist nicht installiert. "
            "Verfügbar: %s",
            self._model,
            ", ".join(sorted(available_names)) or "(keine)",
        )
        return False

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Führt eine Chat-Anfrage gegen den lokalen Ollama-Server aus."""

        options: dict[str, Any] = {
            "temperature": temperature if temperature is not None else self._temperatur
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [message.to_dict() for message in messages],
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": options,
        }

        started = self._now()
        data = await self._request_json(f"{self._base_url}/api/chat", payload=payload)
        latency = self._now() - started

        message = data.get("message") or {}
        text = str(message.get("content", "")).strip()
        if not text:
            raise ProviderError("ollama: Antwort enthält keinen Text.")

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self._model,
            latency_seconds=latency,
            finish_reason=data.get("done_reason"),
            raw=data,
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streamt die Antwort Stück für Stück (Ollama kann das nativ).

        Ollama liefert bei ``stream: true`` zeilenweise JSON, jede Zeile mit
        einem kleinen Textstück. Weil ``urllib`` blockierend liest, läuft
        das Lesen in einem Thread und reicht die Stücke über eine Queue an
        die Ereignisschleife weiter – so blockiert das Streamen die
        Oberfläche nicht.
        """

        options: dict[str, Any] = {
            "temperature": temperature if temperature is not None else self._temperatur
        }
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [message.to_dict() for message in messages],
            "stream": True,
            "keep_alive": self._keep_alive,
            "options": options,
        }
        if options:
            payload["options"] = options

        chunks: queue.Queue[str | None] = queue.Queue()
        error_box: list[str] = []

        def reader() -> None:
            try:
                request = urllib.request.Request(
                    f"{self._base_url}/api/chat",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    for line in response:
                        text = line.decode("utf-8", errors="replace").strip()
                        if not text:
                            continue
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        piece = str((data.get("message") or {}).get("content", ""))
                        if piece:
                            chunks.put(piece)
                        if data.get("done"):
                            break
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                error_box.append(str(error))
            finally:
                chunks.put(None)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()

        while True:
            piece = await asyncio.to_thread(chunks.get)
            if piece is None:
                break
            yield piece

        if error_box:
            raise ProviderError(f"ollama: Streaming abgebrochen – {error_box[0]}")
