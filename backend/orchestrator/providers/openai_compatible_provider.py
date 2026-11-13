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
import re
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
        # Seit 07.11.2026 auch ueber Chat-Completions (gpt-4.1-mini, gpt-4o-mini
        # nehmen Bilder an) - sonst konnte das Hauptmodell weder Bildschirm
        # noch Webcam sehen. ``supports_images: false`` schaltet es ab.
        self.supports_images = bool(
            settings.get("supports_images", self._preset_name == "openai")
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

        payload = self._chat_payload(
            messages, temperature=temperature, max_tokens=max_tokens
        )

        started = self._now()
        try:
            data = await self._request_json(
                f"{self._base_url}{self._endpunkt()}",
                payload=payload,
                headers=self._headers(),
            )
        except ProviderError as error:
            if not self._vorlagenschalter_abgelehnt(str(error), payload):
                raise
            data = await self._request_json(
                f"{self._base_url}{self._endpunkt()}",
                payload=payload,
                headers=self._headers(),
            )
        latency = self._now() - started

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"{self._preset_name}: Antwort ohne Auswahl.")

        first = choices[0]
        text = self._ohne_denkblock(self._wahltext(first, strom=False)).strip()

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

    # --- Chat-Completions: Nachrichten, Nutzlast, Denkbloecke ------------------
    #
    # Gebaut fuer LM Studio als Hauptmodell (06.11.2026). Drei Dinge gingen
    # dort vorher schief:
    #
    # 1. Mehrere Systemnachrichten. Der Orb schickt neben dem Grundprompt
    #    weitere Systemnachrichten (Suchergebnisse, Kontext). Die Vorlagen
    #    von Qwen und DeepSeek brechen dann mit "System message must be at
    #    the beginning" ab (Protokoll 04.11., 03:02:46). Lokal werden sie
    #    deshalb zu EINER Systemnachricht am Anfang zusammengefasst.
    # 2. Denkmodelle. Qwen 3.5/3.6 denkt standardmaessig. LM Studio legt
    #    das Gedachte getrennt in "reasoning_content" ab, und es zaehlt
    #    gegen max_tokens - bei 40 gesprochenen Tokens bleibt "content"
    #    leer. Abgeschaltet wird es ueber die Vorlage (enable_thinking);
    #    was trotzdem als <think>-Block kommt, wird entfernt.
    # 3. Kein Streaming. Ohne Strom spricht der Orb erst, wenn die ganze
    #    Antwort fertig ist. Auf der CPU sind das viele Sekunden Stille.

    def _api_messages(self, messages: list[ChatMessage]) -> list[dict[str, str]]:
        rohe = [message.to_dict() for message in messages]
        zusammenfassen = bool(
            self._settings.get("merge_system_messages", self._is_local)
        )
        if not zusammenfassen:
            return rohe
        system = [m["content"] for m in rohe if m.get("role") == "system" and m.get("content")]
        rest = [m for m in rohe if m.get("role") != "system"]
        # Zwei gleiche Rollen hintereinander moegen manche Vorlagen ebenfalls
        # nicht; sie werden zu einer Nachricht verbunden.
        verbunden: list[dict[str, str]] = []
        for nachricht in rest:
            if verbunden and verbunden[-1]["role"] == nachricht["role"]:
                verbunden[-1] = {
                    "role": nachricht["role"],
                    "content": verbunden[-1]["content"] + "\n\n" + nachricht["content"],
                }
            else:
                verbunden.append(dict(nachricht))
        if system:
            return [{"role": "system", "content": "\n\n".join(system)}, *verbunden]
        return verbunden

    def _chat_payload(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        if self._roh_chatml():
            payload: dict[str, Any] = {
                "model": self._model,
                "prompt": self._chatml_prompt(messages),
                "stop": ["<|im_end|>", "<|im_start|>", "<|endoftext|>"],
            }
        else:
            payload = {
                "model": self._model,
                "messages": self._api_messages(messages),
            }
        # Denkmodelle von OpenAI (gpt-5*, o*) kennen weder "max_tokens" noch
        # eine eigene Temperatur, dafuer "reasoning_effort" (13.11.2026). Mit
        # "minimal"/"none" antworten sie fast so schnell wie gpt-4.1-mini.
        denkmodell = bool(re.match(r"(?:openai/)?(?:gpt-5|o\d)", str(self._model or "").lower()))
        if temperature is None and self._settings.get("temperature") is not None:
            temperature = float(self._settings["temperature"])
        if temperature is not None and not denkmodell:
            payload["temperature"] = temperature
        if max_tokens is not None:
            mindestens = int(self._settings.get("minimum_predict_tokens", 0) or 0)
            schluessel = "max_completion_tokens" if denkmodell else "max_tokens"
            payload[schluessel] = max(int(max_tokens), mindestens)
        aufwand = str(self._settings.get("reasoning_effort", "") or "").strip()
        # Ohne Angabe denkt ein GPT-5-Modell "mittel" - mehrere Sekunden vor
        # jedem Wort. Fuer ein Gespraech ist "minimal" richtig (13.11.2026).
        if not aufwand and denkmodell and "messages" in payload:
            aufwand = "minimal"
        if aufwand and "messages" in payload:
            payload["reasoning_effort"] = aufwand
        wortfuelle = str(self._settings.get("verbosity", "") or "").strip()
        if wortfuelle and denkmodell and "messages" in payload:
            payload["verbosity"] = wortfuelle
        denken = self._settings.get("thinking")
        if (
            denken is not None
            and "messages" in payload
            and not getattr(self, "_vorlagenschalter_aus", False)
        ):
            payload["chat_template_kwargs"] = {"enable_thinking": bool(denken)}
        if stream:
            payload["stream"] = True
        return payload

    # LM Studio ignoriert ``chat_template_kwargs`` (Messung 06.11.2026:
    # Qwen 3.5 dachte trotzdem 15 s lang alle 96 Tokens weg, sichtbarer Text
    # leer; bekannt als lmstudio-bug-tracker #1990). Verlaesslich ist nur,
    # die Vorlage selbst zu bauen: ChatML mit einem LEEREN Denkblock am
    # Anfang der Antwort - genau das, was die Qwen-Vorlage bei
    # enable_thinking=false einfuegt - und das Ganze roh an /v1/completions.
    # Eingeschaltet mit ``prompt_format: chatml`` (nur fuer Qwen-Modelle).

    def _roh_chatml(self) -> bool:
        return str(self._settings.get("prompt_format", "")).strip().lower() == "chatml"

    def _chatml_prompt(self, messages: list[ChatMessage]) -> str:
        teile = [
            f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n"
            for m in self._api_messages(messages)
        ]
        anfang = "<|im_start|>assistant\n"
        if self._settings.get("thinking") is False:
            anfang += "<think>\n\n</think>\n\n"
        return "".join(teile) + anfang

    def _endpunkt(self) -> str:
        return "/completions" if self._roh_chatml() else "/chat/completions"

    @staticmethod
    def _wahltext(wahl: dict[str, Any], *, strom: bool) -> str:
        if "text" in wahl:
            return str(wahl.get("text") or "")
        quelle = wahl.get("delta") if strom else wahl.get("message")
        return str((quelle or {}).get("content") or "")

    def _vorlagenschalter_abgelehnt(self, fehler: str, payload: dict[str, Any]) -> bool:
        """Lehnt der Server ``chat_template_kwargs`` ab, ohne ihn weiter."""

        if "chat_template_kwargs" not in payload:
            return False
        lowered = fehler.lower()
        if "chat_template_kwargs" not in lowered and "enable_thinking" not in lowered:
            return False
        logger.info(
            "%s: Der Server kennt 'chat_template_kwargs' nicht; es wird kuenftig "
            "weggelassen.",
            self.name,
        )
        self._vorlagenschalter_aus = True
        payload.pop("chat_template_kwargs", None)
        return True

    @staticmethod
    def _ohne_denkblock(text: str) -> str:
        """Entfernt <think>...</think> - auch einen nie geschlossenen."""

        while "<think>" in text:
            anfang = text.index("<think>")
            ende = text.find("</think>", anfang)
            if ende < 0:
                text = text[:anfang]
                break
            text = text[:anfang] + text[ende + len("</think>"):]
        if "</think>" in text:
            # Manche Vorlagen setzen das oeffnende Tag selbst in den Prompt.
            text = text.split("</think>", 1)[1]
        return text

    async def _chat_completions_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streamt /chat/completions (SSE) Stueck fuer Stueck."""

        payload = self._chat_payload(
            messages, temperature=temperature, max_tokens=max_tokens, stream=True
        )
        timeout = httpx.Timeout(timeout=self._timeout, connect=min(self._timeout, 8.0))
        loop = asyncio.get_running_loop()
        first_deadline = loop.time() + self._first_token_timeout
        received_text = False
        # Inline-Denkbloecke ueber Stueckgrenzen hinweg herausfiltern.
        puffer = ""
        im_denken = False
        lebenszeichen = False

        for versuch in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=not self._is_local) as client:
                    request = client.build_request(
                        "POST",
                        f"{self._base_url}{self._endpunkt()}",
                        json=payload,
                        headers=self._headers(),
                    )
                    try:
                        response = await asyncio.wait_for(
                            client.send(request, stream=True),
                            timeout=max(0.01, first_deadline - loop.time()),
                        )
                    except asyncio.TimeoutError as error:
                        raise ProviderError(
                            f"{self.name}: keine Antwortverbindung innerhalb von "
                            f"{self._first_token_timeout:.0f} s."
                        ) from error
                    try:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", errors="replace")
                            fehler = f"{self.name}: HTTP {response.status_code} - {body[:500]}"
                            if versuch == 0 and self._vorlagenschalter_abgelehnt(fehler, payload):
                                continue
                            raise ProviderError(fehler)

                        iterator = response.aiter_lines()
                        while True:
                            # Denkt das Modell (reasoning_content), ist es am
                            # Leben: dann gilt die Gesamtfrist, nicht die
                            # Frist auf das erste Wort.
                            if received_text or lebenszeichen:
                                remaining = self._timeout
                            else:
                                remaining = max(0.01, first_deadline - loop.time())
                            try:
                                line = await asyncio.wait_for(anext(iterator), timeout=remaining)
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
                            if event.get("error"):
                                if received_text:
                                    logger.info("%s: Strom endete mit Fehler nach Text: %s",
                                                self.name, str(event["error"])[:200])
                                    break
                                raise ProviderError(
                                    f"{self.name}: Stream-Fehler - {str(event['error'])[:500]}"
                                )
                            choices = event.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            # Nur LOKAL zaehlt Denken als Lebenszeichen (das
                            # Modell muss dort erst laden). Ein Cloud-Modell,
                            # das 8 s lang nur denkt, wird uebersprungen - das
                            # naechste ist schneller als das Warten.
                            if self._is_local and (
                                delta.get("reasoning_content") or delta.get("reasoning")
                            ):
                                lebenszeichen = True
                            stueck = self._wahltext(choices[0], strom=True)
                            if not stueck:
                                continue
                            lebenszeichen = True
                            puffer += stueck
                            ausgabe = ""
                            while puffer:
                                if im_denken:
                                    ende = puffer.find("</think>")
                                    if ende < 0:
                                        puffer = puffer[-8:]
                                        break
                                    puffer = puffer[ende + 8:]
                                    im_denken = False
                                    continue
                                anfang = puffer.find("<think>")
                                if anfang >= 0:
                                    ausgabe += puffer[:anfang]
                                    puffer = puffer[anfang + 7:]
                                    im_denken = True
                                    continue
                                # Ein angeschnittenes "<thi" am Ende zurueckhalten.
                                schnitt = puffer.rfind("<")
                                if schnitt >= 0 and "<think>".startswith(puffer[schnitt:]):
                                    ausgabe += puffer[:schnitt]
                                    puffer = puffer[schnitt:]
                                else:
                                    ausgabe += puffer
                                    puffer = ""
                                break
                            if not received_text:
                                ausgabe = ausgabe.lstrip()
                            if ausgabe:
                                received_text = True
                                yield ausgabe
                    finally:
                        await response.aclose()
                break
            except ProviderError:
                raise
            except (httpx.HTTPError, OSError) as error:
                raise ProviderError(f"{self.name}: Streaming abgebrochen - {error}") from error

        if puffer and not im_denken and puffer.strip():
            received_text = True
            yield puffer
        if not received_text:
            raise ProviderError(f"{self.name}: der Antwortstrom endete ohne sichtbaren Text.")

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

    async def _chat_mit_bildern(
        self,
        prompt: str,
        *,
        system_prompt: str,
        images: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
    ) -> ProviderResponse:
        """Bilder ueber /chat/completions (image_url mit data:-URL)."""

        inhalt: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in images:
            media_type = str(image.get("media_type") or "image/png").strip().lower()
            encoded = str(image.get("data") or "").strip()
            if not media_type.startswith("image/") or not encoded:
                raise ProviderError(f"{self.name}: ungueltige Bilddaten.")
            inhalt.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{encoded}"},
            })
        nachrichten: list[dict[str, Any]] = []
        if system_prompt:
            nachrichten.append({"role": "system", "content": system_prompt})
        nachrichten.append({"role": "user", "content": inhalt})
        payload: dict[str, Any] = {"model": self._model, "messages": nachrichten}
        if temperature is not None:
            payload["temperature"] = temperature
        payload["max_tokens"] = max(int(max_tokens or 0), 400)
        started = self._now()
        data = await self._request_json(
            f"{self._base_url}/chat/completions",
            payload=payload,
            headers=self._headers(),
        )
        choices = data.get("choices") or []
        text = self._wahltext(choices[0], strom=False).strip() if choices else ""
        if not text:
            raise ProviderError(f"{self.name}: leere Antwort auf das Bild.")
        return ProviderResponse(
            text=text,
            provider=self.name,
            model=self._model,
            latency_seconds=self._now() - started,
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

        if self._api_style != "responses":
            return await self._chat_mit_bildern(
                prompt,
                system_prompt=system_prompt,
                images=images,
                temperature=temperature,
                max_tokens=max_tokens,
            )

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
            if not bool(self._settings.get("stream", True)):
                async for piece in super().chat_stream(
                    messages, temperature=temperature, max_tokens=max_tokens
                ):
                    yield piece
                return
            async for piece in self._chat_completions_stream(
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
