"""Ollama-Provider – lokaler Offline-Fallback.

Spricht die native Ollama-API (``/api/chat``, ``/api/tags``) auf dem lokal
laufenden Ollama-Server an. Basis-URL und Modellname stammen ausschließlich
aus ``config.yaml``; es werden keine Daten an externe Dienste übertragen.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

import httpx

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

    @property
    def is_local(self) -> bool:
        """Ollama laeuft ausschliesslich ueber den lokalen Dienst."""

        return True

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self._base_url = str(settings.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        # Das Modell im Arbeitsspeicher halten - sonst laedt Ollama es nach
        # jeder Pause neu, und die erste Offline-Antwort dauert dann lange.
        self._keep_alive = str(settings.get("keep_alive", "30m"))
        self._first_token_timeout = max(
            1.0,
            float(settings.get("first_token_timeout", min(self._timeout, 10.0))),
        )
        self._warmup_tokens = max(1, int(settings.get("warmup_tokens", 8)))
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
        data = await self._mit_ladegeduld(f"{self._base_url}/api/chat", payload)
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

    #: Woran ein KALTSTART zu erkennen ist - nicht ein echter Fehler.
    #:
    #: Genau das stand im Protokoll des Benutzers an dem Tag, an dem der Orb
    #: „nicht mehr lief": Claude war am Kontingentende, und der lokale
    #: Ausweg antwortete mit
    #:
    #:     HTTP 500 - {"error":"timed out waiting for llama-server to start"}
    #:
    #: Damit war BEIDES weg und der Orb stumm. Der Sache nach ist das aber
    #: kein Ausfall, sondern Ungeduld: Ollama startet sein Rechenwerk erst
    #: bei der ersten Frage, und ein 8-Milliarden-Modell braucht dafür auf
    #: einem beschäftigten Rechner länger als die Vorgabe erlaubt. Beim
    #: zweiten Versuch liegt das Modell dann meist schon bereit.
    _KALTSTART: tuple[str, ...] = (
        "timed out waiting for llama-server",
        "llama runner process has terminated",
        "model is being loaded",
        "loading model",
    )

    async def _mit_ladegeduld(
        self, url: str, payload: dict[str, Any], *, versuche: int = 3
    ) -> dict[str, Any]:
        """Fragt Ollama und gibt einem Kaltstart die Zeit, die er braucht.

        Ein zweiter Anlauf ist hier keine Rateübung, sondern der Normalfall:
        Der erste Aufruf STÖSST DAS LADEN AN und läuft dabei in Ollamas
        eigene Frist; der zweite trifft ein Modell, das bereits lädt oder
        schon steht. Deshalb wird zwischen den Anläufen auch gewartet statt
        sofort nachzusetzen.
        """

        letzter: ProviderError | None = None
        for versuch in range(1, max(1, versuche) + 1):
            try:
                return await self._request_json(url, payload=payload)
            except ProviderError as fehler:
                text = str(fehler).lower()
                if not any(marker in text for marker in self._KALTSTART):
                    raise
                letzter = fehler
                if versuch >= versuche:
                    break
                wartezeit = 6.0 * versuch
                logger.info(
                    "Ollama lädt das Modell noch (Versuch %d von %d) - es wird "
                    "%.0f s gewartet und erneut gefragt.",
                    versuch, versuche, wartezeit,
                )
                await asyncio.sleep(wartezeit)

        raise ProviderError(
            "ollama: Das lokale Modell ließ sich nicht rechtzeitig laden. "
            "Meist hilft es, einmal 'ollama run " + self._model + "' im "
            "Terminal auszuführen, damit es geladen bleibt. "
            f"(Ursprüngliche Meldung: {letzter})"
        ) from letzter

    async def waermen(self) -> bool:
        """Lädt das Modell vorsorglich in den Arbeitsspeicher.

        Gedacht für den Augenblick, in dem Claude an seine Grenze stößt: Von
        da an trägt das lokale Modell den Betrieb, und dann soll es schon
        stehen - nicht erst geladen werden, während der Benutzer wartet.
        """

        try:
            await self._mit_ladegeduld(
                f"{self._base_url}/api/chat",
                {
                    "model": self._model,
                    # Nicht nur das Modell laden, sondern auch einen kurzen
                    # echten Dialogdurchlauf ausfuehren. Ein Ein-Token-Ping
                    # meldete bereits "warm", obwohl der erste Benutzerzug
                    # danach noch bis zu neun Sekunden auf die erste
                    # Dekodierung wartete.
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Du bist AI-Orb. Antworte auf Deutsch, direkt, "
                                "freundlich und in kurzen gesprochenen Saetzen."
                            ),
                        },
                        {"role": "user", "content": "Sage kurz, dass du bereit bist."},
                    ],
                    "stream": False,
                    "keep_alive": self._keep_alive,
                    "options": {
                        "num_predict": self._warmup_tokens,
                        "temperature": self._temperatur,
                    },
                },
                versuche=2,
            )
        except ProviderError as fehler:
            logger.info("Das lokale Modell ließ sich nicht vorwärmen: %s", fehler)
            return False
        logger.info("Das lokale Modell '%s' ist vorgewärmt.", self._model)
        return True

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream to Ollama while propagating cancellation to the socket."""

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
        timeout = httpx.Timeout(
            timeout=self._timeout,
            connect=min(self._timeout, 5.0),
        )
        loop = asyncio.get_running_loop()
        first_deadline = loop.time() + self._first_token_timeout
        received_text = False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request = client.build_request(
                    "POST", f"{self._base_url}/api/chat", json=payload
                )
                try:
                    response = await asyncio.wait_for(
                        client.send(request, stream=True),
                        timeout=self._first_token_timeout,
                    )
                except asyncio.TimeoutError as error:
                    raise ProviderError(
                        "ollama: Keine Antwortverbindung innerhalb von "
                        f"{self._first_token_timeout:.0f} s."
                    ) from error
                try:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise ProviderError(
                            f"ollama: HTTP {response.status_code} - {body[:500]}"
                        )

                    iterator = response.aiter_lines()
                    while True:
                        remaining = (
                            max(0.01, first_deadline - loop.time())
                            if not received_text
                            else self._timeout
                        )
                        try:
                            line = await asyncio.wait_for(
                                anext(iterator), timeout=remaining
                            )
                        except StopAsyncIteration:
                            break
                        except asyncio.TimeoutError as error:
                            if not received_text:
                                raise ProviderError(
                                    "ollama: Kein erstes Textstueck innerhalb von "
                                    f"{self._first_token_timeout:.0f} s."
                                ) from error
                            raise ProviderError(
                                "ollama: Der Antwortstrom ist stehen geblieben."
                            ) from error

                        text = line.strip()
                        if not text:
                            continue
                        try:
                            data = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        piece = str((data.get("message") or {}).get("content", ""))
                        if piece:
                            received_text = True
                            yield piece
                        if data.get("done"):
                            break
                finally:
                    await response.aclose()
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as error:
            raise ProviderError(f"ollama: Streaming abgebrochen - {error}") from error
