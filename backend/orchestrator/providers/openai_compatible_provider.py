"""OpenAI-kompatible Provider (Master-Prompt Abschnitte 7, 8, 9).

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
    """Spricht jede OpenAI-kompatible ``/chat/completions``-API an.

    Der konkrete Dienst wird über ``preset`` gewählt (``openai``,
    ``ollama_cloud``, ``lmstudio``, ``llamacpp``) oder vollständig von Hand
    über ``base_url`` und ``api_key_env`` gesetzt.
    """

    name = "openai_compatible"

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)

        preset_name = str(settings.get("preset", "")).strip().lower()
        preset = PRESETS.get(preset_name, {})

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
