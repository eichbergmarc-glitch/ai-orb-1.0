"""Basisschnittstelle aller KI-Provider.

Jeder Provider (Hermes, Ollama und künftig OpenAI, Gemini, Claude,
Mistral, weitere lokale Modelle) implementiert exakt diese Schnittstelle.
Der Provider Manager kennt ausschließlich diese Basisklasse, wodurch neue
Provider ohne Änderungen am Orchestrator ergänzt werden können.

Modellnamen werden niemals im Code festgelegt, sondern ausschließlich aus
``config.yaml`` gelesen.
"""

from __future__ import annotations

import abc
import asyncio
import json
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ChatMessage:
    """Eine einzelne Nachricht im Gesprächsverlauf."""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ProviderResponse:
    """Antwort eines Providers inklusive Metadaten für Logging und Metriken."""

    text: str
    provider: str
    model: str
    latency_seconds: float = 0.0
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    """Fehler bei der Kommunikation mit einem KI-Provider."""


class BaseProvider(abc.ABC):
    """Abstrakte Basisklasse für alle KI-Provider."""

    #: Eindeutiger Name des Providers (z. B. ``"hermes"``).
    name: str = "base"

    def __init__(self, settings: dict[str, Any]) -> None:
        """
        Args:
            settings: Der zugehörige Konfigurationsabschnitt aus
                ``config.yaml`` (u. a. ``model``, ``base_url``, ``timeout``).
        """

        self._settings = settings
        # Mehrere Instanzen derselben Engine muessen fuer Routing, Health-
        # Checks und Metriken unterscheidbar bleiben. Ohne Instanznamen
        # wuerden etwa zwei lokale Ollama-Modelle beide als ``ollama``
        # registriert und der zweite Eintrag den ersten ueberschreiben.
        instance_name = str(settings.get("instance_name", "")).strip()
        if instance_name:
            self.name = instance_name
        self._model = str(settings.get("model", ""))
        self._timeout = float(settings.get("timeout", 60))

    @property
    def model(self) -> str:
        """Der konfigurierte Modellname (ausschließlich aus ``config.yaml``)."""

        return self._model

    @property
    def settings(self) -> dict[str, Any]:
        """Der Konfigurationsabschnitt dieses Providers."""

        return self._settings

    @property
    def is_local(self) -> bool:
        """Ob Anfragen dieses Providers den Rechner nicht verlassen.

        Cloud-Provider erben bewusst ``False``. Lokale Provider muessen
        diese Eigenschaft ausdruecklich ueberschreiben; dadurch kann ein
        erzwungener Offlinebetrieb niemals versehentlich einen neuen,
        unbekannten Cloud-Provider als lokal behandeln.
        """

        return False

    # --- Von Unterklassen zu implementieren ---------------------------------

    @abc.abstractmethod
    async def is_available(self) -> bool:
        """Prüft, ob der Provider aktuell erreichbar und einsatzbereit ist."""

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        """Führt eine Chat-Anfrage aus und gibt die Antwort zurück."""

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Streamt die Antwort in Stücken, sobald sie entstehen.

        Das ist die Grundlage für „denken, sprechen, weiterdenken,
        weitersprechen": Wer die Antwort erst vollständig abwartet, kann
        nicht früh anfangen zu reden.

        Die Vorgabe hier ist ehrlich und ungefährlich: Sie holt die ganze
        Antwort über :meth:`chat` und gibt sie in *einem* Stück zurück. Ein
        Provider, der nicht streamen kann, verhält sich damit wie bisher –
        die Oberfläche merkt keinen Unterschied, außer dass eben nichts
        früher kommt. Provider, die es können (Ollama, Claude Code), setzen
        diese Methode außer Kraft und liefern die Stücke wirklich einzeln.
        """

        response = await self.chat(
            messages, temperature=temperature, max_tokens=max_tokens
        )
        if response.text:
            yield response.text

    # --- Gemeinsame Hilfsfunktionen ------------------------------------------

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        """Bequemlichkeitsfunktion für Einzelanfragen ohne Verlauf."""

        response = await self.chat([ChatMessage(role="user", content=prompt)], **kwargs)
        return response.text

    async def _request_json(
        self,
        url: str,
        *,
        method: str = "POST",
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Führt eine HTTP-Anfrage asynchron aus (ohne externe Bibliotheken).

        Die blockierende ``urllib``-Anfrage wird in einen Worker-Thread
        ausgelagert, damit die Event-Loop und damit die Oberfläche niemals
        blockiert werden (Performance-Anforderung).
        """

        return await asyncio.to_thread(
            self._request_json_blocking, url, method, payload, headers, timeout
        )

    def _request_json_blocking(
        self,
        url: str,
        method: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str] | None,
        timeout: float | None,
    ) -> dict[str, Any]:
        data: bytes | None = None
        request_headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)

        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout or self._timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ProviderError(
                f"{self.name}: HTTP {error.code} – {detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ProviderError(f"{self.name}: nicht erreichbar – {error}") from error

        if not body.strip():
            return {}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:
            raise ProviderError(f"{self.name}: ungültige JSON-Antwort") from error
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    @staticmethod
    def _now() -> float:
        return time.perf_counter()
