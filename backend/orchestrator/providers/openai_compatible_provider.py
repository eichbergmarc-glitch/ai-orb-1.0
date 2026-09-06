"""OpenAI- und OpenAI-kompatible Provider (Master-Prompt Abschnitte 7, 8, 9).

Ein einziger Adapter für alles, was die OpenAI-``/chat/completions``-API
spricht. Das ist mehr, als der Name vermuten lässt: OpenAI selbst, LM
Studio, llama.cpp im Servermodus, Ollama Cloud und die meisten anderen
lokalen Modellserver reden genau dieses Protokoll. Sie unterscheiden sich
nur in drei Dingen – der Basis-URL, dem Modellnamen und der Frage, ob ein
Schlüssel nötig ist.

## Warum ein neuer Adapter neben ``hermes``

Der bestehende ``hermes``-Provider tut technisch dasselbe. Ihn umzubenennen
oder zu ersetzen widerspräche der obersten Regel dieses Projekts (EXTEND,
DON'T REPLACE) und bräche jede Konfiguration, die ihn schon nutzt. Statt
dessen sind die einzelnen Dienste hier als *Voreinstellungen* hinterlegt:
Wer ``engine: openai`` schreibt, bekommt die richtige Basis-URL und
Schlüsselvariable geschenkt, ohne sie zu kennen. ``hermes`` bleibt für
OpenRouter und alles Übrige.

## Zum Sicherheitsgebot der Spezifikation

Die Abschnitte 11, 12 und 52 verlangen es unmissverständlich: kein
Schlüssel im Quellcode, keiner in der Konfiguration, keiner im Frontend.
Dieser Adapter liest den Schlüssel ausschließlich aus einer
Umgebungsvariablen, deren *Name* in der Konfiguration steht – der Wert
niemals. Ein lokaler Server (LM Studio, llama.cpp) braucht gar keinen und
läuft schlüssellos.
"""

from __future__ import annotations

import asyncio
import json
import os
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


#: Voreinstellungen je Dienst: Basis-URL, Schlüsselvariable, ob lokal.
#:
#: Die URLs sind die dokumentierten Standardadressen. Wer einen Dienst auf
#: einem anderen Port betreibt, überschreibt ``base_url`` in der
#: Konfiguration – die Voreinstellung ist eine Bequemlichkeit, kein Zwang.
PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "requires_key": True,
        "local": False,
    },
    "ollama_cloud": {
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_API_KEY",
        "requires_key": True,
        "local": False,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "requires_key": True,
        "local": False,
    },
    "grok": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "requires_key": True,
        "local": False,
    },
    # Alias fuer Konfigurationen, die den Herstellernamen verwenden.
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "requires_key": True,
        "local": False,
    },
    "lmstudio": {
        # LM Studio lauscht standardmäßig hier und verlangt keinen Schlüssel.
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key_env": "LMSTUDIO_API_KEY",
        "requires_key": False,
        "local": True,
    },
    "llamacpp": {
        # llama.cpp im Servermodus (`llama-server`).
        "base_url": "http://127.0.0.1:8080/v1",
        "api_key_env": "LLAMACPP_API_KEY",
        "requires_key": False,
        "local": True,
    },
}


class OpenAICompatibleProvider(BaseProvider):
    """Spricht OpenAI Responses oder eine kompatible Chat-API an.

    Der konkrete Dienst wird über ``preset`` gewählt (``openai``,
    ``ollama_cloud``, ``lmstudio``, ``llamacpp``) oder vollständig von Hand
    über ``base_url`` und ``api_key_env`` gesetzt.
    """

    name = "openai_compatible"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)

        preset_name = str(settings.get("preset", "")).strip().lower()
        preset = PRESETS.get(preset_name, {})
        # Mehrere Instanzen dieses Adapters muessen fuer Routing, Metriken und
        # Gesundheitspruefungen unterscheidbar bleiben. Ohne Instanznamen
        # ueberschrieben sich OpenAI, OpenRouter und xAI im Health-Monitor.
        self.name = str(
            settings.get("provider_name")
            or settings.get("instance_name")
            or settings.get("engine")
            or preset_name
            or type(self).name
        ).strip().lower()

        # Konfiguration schlägt Voreinstellung. Eine ausdrücklich gesetzte
        # base_url gilt, auch wenn ein Preset etwas anderes vorschlägt.
        self._base_url = str(
            settings.get("base_url") or preset.get("base_url", "")
        ).rstrip("/")
        self._api_key_env = str(
            settings.get("api_key_env") or preset.get("api_key_env", "OPENAI_API_KEY")
        )
        self._requires_key = bool(
            settings.get("requires_key", preset.get("requires_key", True))
        )
        self._is_local = bool(settings.get("local", preset.get("local", False)))
        self._preset_name = preset_name or "eigen"
        # OpenAI selbst empfiehlt fuer neue agentische Anwendungen die
        # Responses API. OpenRouter, xAI und lokale Server bleiben dagegen
        # bei der breit unterstuetzten Chat-Completions-Schnittstelle.
        self._api_style = str(
            settings.get("api_style")
            or ("responses" if preset_name == "openai" else "chat_completions")
        ).strip().lower()
        self._first_token_timeout = max(
            1.0,
            float(settings.get("first_token_timeout", min(self._timeout, 20.0))),
        )
        # Der offizielle OpenAI-Responses-Endpunkt nimmt Bilder direkt als
        # Eingabe an. Kompatible Drittanbieter werden nicht pauschal als
        # bildfaehig markiert, weil deren Schemas voneinander abweichen.
        self.supports_images = (
            self._preset_name == "openai" and self._api_style == "responses"
        )

    # --- Schlüssel -------------------------------------------------------------

    @property
    def api_key(self) -> str:
        """Der Schlüssel aus der Umgebung – niemals aus der Konfiguration."""

        return os.environ.get(self._api_key_env, "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        # OpenRouter nutzt diese optionalen Angaben fuer die transparente
        # Zuordnung der Anwendung. Andere kompatible APIs ignorieren sie.
        referer = self._settings.get("http_referer")
        if referer:
            headers["HTTP-Referer"] = str(referer)
        title = self._settings.get("app_title")
        if title:
            headers["X-Title"] = str(title)
        return headers

    @property
    def is_local(self) -> bool:
        """Ob der Dienst auf diesem Rechner läuft – wichtig fürs Routing."""

        return self._is_local

    # --- Verfügbarkeit ---------------------------------------------------------

    async def is_available(self) -> bool:
        """Prüft, ob der Dienst erreichbar und einsatzbereit ist.

        Ein Cloud-Dienst ohne Schlüssel gilt als nicht verfügbar – der
        Aufruf würde ohnehin mit 401 scheitern, und das früh zu erkennen
        erspart einen Fehlversuch. Ein lokaler Dienst braucht keinen und
        wird direkt angefragt.
        """

        if not self._base_url:
            logger.debug("%s: keine base_url.", self._preset_name)
            return False

        if self._requires_key and not self.api_key:
            logger.warning(
                "%s: kein Schlüssel in %s. Trage ihn in die .env ein "
                "(niemals in config.yaml).",
                self._preset_name,
                self._api_key_env,
            )
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
            level = logger.debug if self._is_local else logger.warning
            level("%s nicht erreichbar (%s): %s", self._preset_name, self._base_url, error)
            return False

    async def available_models(self) -> list[str]:
        """Fragt die Modellliste ab (Master-Prompt Abschnitt 57).

        Für die automatische Modellerkennung beim Start. Ein leeres
        Ergebnis ist kein Fehler – manche lokalen Server melden nichts,
        bevor ein Modell geladen ist.
        """

        if not self._base_url:
            return []
        try:
            data = await self._request_json(
                f"{self._base_url}/models",
                method="GET",
                headers=self._headers(),
                timeout=min(self._timeout, 8.0),
            )
        except ProviderError:
            return []

        return [
            str(entry.get("id", ""))
            for entry in (data.get("data") or [])
            if entry.get("id")
        ]

    # --- Anfrage ---------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Stellt eine Chat-Anfrage."""

        if not self._base_url:
            raise ProviderError(f"{self._preset_name}: keine base_url konfiguriert.")

        if self._api_style == "responses":
            return await self._chat_responses(
                messages, temperature=temperature, max_tokens=max_tokens
            )

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
            raise ProviderError(f"{self._preset_name}: Antwort ohne Auswahl.")

        first = choices[0]
        text = str((first.get("message") or {}).get("content", "")).strip()

        if not text:
            raise ProviderError(f"{self._preset_name}: leere Antwort.")

        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self._model,
            latency_seconds=latency,
            finish_reason=first.get("finish_reason"),
            raw=data,
        )

    async def _chat_responses(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Antwortet ueber OpenAIs aktuelle Responses API."""

        payload = self._responses_payload(
            [message.to_dict() for message in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        started = self._now()
        data = await self._request_json(
            f"{self._base_url}/responses",
            payload=payload,
            headers=self._headers(),
        )
        latency = self._now() - started

        return self._response_from_responses_data(data, latency=latency)

    def _responses_payload(
        self,
        input_items: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Baut den gemeinsamen Request fuer Text, Bilder und Streaming."""

        payload: dict[str, Any] = {"model": self._model, "input": input_items}
        if max_tokens is not None:
            payload["max_output_tokens"] = self._ausgabegrenze(max_tokens)

        # Die aktuellen Reasoning-Modelle akzeptieren keine frei gesetzte
        # Temperatur. Fuer aeltere OpenAI-Modelle bleibt sie verfuegbar.
        if temperature is not None and not self._model.lower().startswith("gpt-5"):
            payload["temperature"] = temperature
        effort = str(self._settings.get("effort", "")).strip().lower()
        if effort and self._model.lower().startswith("gpt-5"):
            payload["reasoning"] = {"effort": effort}
        if stream:
            payload["stream"] = True
        return payload

    def _ist_denkmodell(self) -> bool:
        """Ob dieses Modell vor dem Antworten nachdenkt."""

        return self._model.lower().startswith("gpt-5")

    def _ausgabegrenze(self, gewuenscht: int) -> int:
        """Rechnet die Denk-Tokens zur gewünschten Antwortlänge dazu.

        Das war der Grund für „Keine Modellantwort möglich" am 31.08.2026.
        ``max_output_tokens`` begrenzt bei einem Reasoning-Modell nicht die
        Antwort, sondern Denken UND Antwort zusammen. Eine gesprochene
        Antwort gibt 40 Tokens mit - die verbrauchte das Modell im Denken,
        und die Antwort kam als ``incomplete`` zurück, ohne ein einziges
        sichtbares Wort. Für den Orb sah das aus wie ein Ausfall des
        Anbieters; es war ein zu enger Rahmen.

        Die Kürze der gesprochenen Antwort hängt ohnehin nicht an dieser
        Zahl, sondern an der Anweisung im Systemtext. Diese Grenze ist ein
        Sicherheitsnetz gegen Ausufern, kein Stilmittel.
        """

        gewuenscht = max(1, int(gewuenscht))
        if not self._ist_denkmodell():
            return gewuenscht
        reserve = int(self._settings.get("reasoning_token_reserve", 512))
        mindestens = int(self._settings.get("reasoning_token_minimum", 256))
        return max(mindestens, gewuenscht + max(0, reserve))

    @staticmethod
    def _responses_text(data: dict[str, Any]) -> str:
        """Extrahiert sichtbaren Text aus einer Responses-Antwort."""

        text = str(data.get("output_text") or "").strip()
        if not text:
            pieces: list[str] = []
            for item in data.get("output") or []:
                if not isinstance(item, dict):
                    continue
                for content in item.get("content") or []:
                    if not isinstance(content, dict):
                        continue
                    if content.get("type") == "output_text" and content.get("text"):
                        pieces.append(str(content["text"]))
            text = "".join(pieces).strip()
        return text

    def _response_from_responses_data(
        self, data: dict[str, Any], *, latency: float
    ) -> ProviderResponse:
        text = self._responses_text(data)

        if not text:
            raise ProviderError(f"{self._preset_name}: leere Responses-Antwort.")

        incomplete = data.get("incomplete_details") or {}
        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self._model,
            latency_seconds=latency,
            finish_reason=(
                str(incomplete.get("reason"))
                if incomplete.get("reason")
                else str(data.get("status") or "completed")
            ),
            raw=data,
        )

    async def complete_with_images(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        images: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Sendet Bilddaten ueber die offizielle OpenAI Responses API."""

        if not self.supports_images:
            raise ProviderError(f"{self.name}: Bilddaten werden nicht unterstuetzt.")

        content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
        for image in images:
            media_type = str(image.get("media_type") or "image/png").strip().lower()
            encoded = str(image.get("data") or "").strip()
            if not media_type.startswith("image/") or not encoded:
                raise ProviderError(f"{self.name}: ungueltige Bilddaten.")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{media_type};base64,{encoded}",
                }
            )

        input_items: list[dict[str, Any]] = []
        if system_prompt:
            input_items.append({"role": "system", "content": system_prompt})
        input_items.append({"role": "user", "content": content})
        payload = self._responses_payload(
            input_items,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        started = self._now()
        data = await self._request_json(
            f"{self._base_url}/responses",
            payload=payload,
            headers=self._headers(),
        )
        return self._response_from_responses_data(
            data, latency=self._now() - started
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streamt OpenAI-Responses-Deltas, damit der Orb frueh sprechen kann."""

        if self._api_style != "responses":
            async for piece in super().chat_stream(
                messages, temperature=temperature, max_tokens=max_tokens
            ):
                yield piece
            return

        payload = self._responses_payload(
            [message.to_dict() for message in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        timeout = httpx.Timeout(
            timeout=self._timeout,
            connect=min(self._timeout, 8.0),
        )
        received_text = False
        completed_response: dict[str, Any] | None = None
        loop = asyncio.get_running_loop()
        first_deadline = loop.time() + self._first_token_timeout

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request = client.build_request(
                    "POST",
                    f"{self._base_url}/responses",
                    json=payload,
                    headers=self._headers(),
                )
                try:
                    response = await asyncio.wait_for(
                        client.send(request, stream=True),
                        timeout=self._first_token_timeout,
                    )
                except asyncio.TimeoutError as error:
                    raise ProviderError(
                        f"{self.name}: keine Antwortverbindung innerhalb von "
                        f"{self._first_token_timeout:.0f} s."
                    ) from error

                try:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode(
                            "utf-8", errors="replace"
                        )
                        raise ProviderError(
                            f"{self.name}: HTTP {response.status_code} - {body[:500]}"
                        )

                    iterator = response.aiter_lines()
                    event_name = ""
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
                            message = (
                                "kein erstes Textstueck rechtzeitig erhalten"
                                if not received_text
                                else "Antwortstrom ist stehen geblieben"
                            )
                            raise ProviderError(f"{self.name}: {message}.") from error

                        stripped = line.strip()
                        if not stripped:
                            event_name = ""
                            continue
                        if stripped.startswith("event:"):
                            event_name = stripped[6:].strip()
                            continue
                        if not stripped.startswith("data:"):
                            continue
                        raw = stripped[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue

                        event_type = str(event.get("type") or event_name)
                        if event_type == "response.output_text.delta":
                            delta = str(event.get("delta") or "")
                            if delta:
                                received_text = True
                                yield delta
                        elif event_type == "response.completed":
                            candidate = event.get("response")
                            if isinstance(candidate, dict):
                                completed_response = candidate
                        elif event_type in {
                            "response.failed",
                            "response.incomplete",
                            "error",
                        }:
                            detail = event.get("error") or event.get("response") or event
                            # Ein abgeschnittener Satz ist immer noch eine
                            # Antwort. Wurde bereits Text gesprochen, endet
                            # der Strom hier ruhig, statt den ganzen Zug als
                            # Fehlschlag zu werfen - der Benutzer hat den
                            # Anfang schliesslich schon gehoert.
                            if received_text:
                                logger.info(
                                    "%s: Der Antwortstrom wurde abgeschnitten "
                                    "(%s). Der bereits gesprochene Teil bleibt "
                                    "stehen.",
                                    self.name,
                                    str(
                                        (detail or {}).get("incomplete_details")
                                        if isinstance(detail, dict)
                                        else detail
                                    )[:120],
                                )
                                break
                            raise ProviderError(
                                f"{self.name}: Responses-Stream fehlgeschlagen - "
                                f"{str(detail)[:500]}"
                            )
                finally:
                    await response.aclose()
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as error:
            raise ProviderError(
                f"{self.name}: Streaming abgebrochen - {error}"
            ) from error

        if not received_text and completed_response is not None:
            final_text = self._responses_text(completed_response)
            if final_text:
                received_text = True
                yield final_text
        if not received_text:
            raise ProviderError(
                f"{self.name}: der Antwortstrom endete ohne sichtbaren Text."
            )
