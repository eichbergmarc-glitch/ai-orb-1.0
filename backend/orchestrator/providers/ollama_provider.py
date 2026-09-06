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
        # Die Frist fuer den ERSTEN Zug nach einer Pause.
        #
        # Ollama haelt die Antwort zurueck, bis das Modell im Speicher
        # steht. Vorher kommt nicht einmal der HTTP-Kopf. Fuer ein warmes
        # Modell ist das eine Sache von Millisekunden, fuer ein kaltes
        # 8-Milliarden-Modell auf einem beschaeftigten Rechner eine Minute
        # und mehr - dieselbe Frist fuer beides zu nehmen heisst, sich
        # zwischen "traege" und "gibt zu frueh auf" entscheiden zu muessen.
        #
        # Im Protokoll vom 06.09. sieht man beide Enden davon:
        #
        #     12:45:13  ollama      - keine Antwortverbindung in 60 s
        #     12:48:23  ollama_fast - Antwort da
        #     12:55:15  ollama_fast - keine Antwortverbindung in 10 s
        #
        # Der Fehlschlag um 12:55 kam sieben Minuten nach dem Erfolg um
        # 12:48 - also nach Ablauf von keep_alive: 5m. Das Modell war
        # ausgeraeumt und laedt neu; zehn Sekunden reichen dafuer nicht.
        # Es war nie kaputt, nur kalt.
        self._cold_first_token_timeout = min(
            self._timeout,
            max(
                self._first_token_timeout,
                float(
                    settings.get(
                        "first_token_timeout_cold",
                        max(self._first_token_timeout * 3.0, 90.0),
                    )
                ),
            ),
        )
        self._keep_alive_seconds = self._keep_alive_in_sekunden(self._keep_alive)
        #: Wann dieses Modell zuletzt wirklich geantwortet hat (Uhr des
        #: Providers, nicht Kalenderzeit). 0.0 heisst: noch nie.
        self._letzter_erfolg = 0.0
        self._warmup_tokens = max(1, int(settings.get("warmup_tokens", 8)))
        # Ollamas Standard ist modell- und installationsabhaengig. Der Orb
        # setzt das aktive Fenster deshalb bei JEDEM Aufruf ausdruecklich,
        # damit Dialog, Stream und Vorwaermen dieselbe Speicherplanung nutzen.
        self._context_window = max(
            2048,
            min(131072, int(settings.get("context_window", 10240))),
        )
        # Reasoning-Modelle koennen ein knappes num_predict vollstaendig fuer
        # ihren internen Denkkanal verbrauchen. Dann meldet Ollama Erfolg,
        # liefert dem Benutzer aber leeren Inhalt. Ein konfigurierbarer
        # Mindestetat verhindert genau diesen scheinbaren Haenger.
        self._minimum_predict_tokens = max(
            0, int(settings.get("minimum_predict_tokens", 0))
        )
        # Ein kleineres Modell schweift leichter ab; eine nuechternere
        # Vorgabe haelt es beim Werkzeugformat.
        roh = settings.get("temperature")
        self._temperatur = float(roh) if roh is not None else 0.4

    @staticmethod
    def _keep_alive_in_sekunden(wert: str) -> float:
        """Uebersetzt Ollamas ``keep_alive`` in Sekunden.

        Erlaubt sind blanke Zahlen (Sekunden) und die Kurzformen ``30m``,
        ``2h``, ``45s``. Ein negativer Wert heisst bei Ollama "nie
        ausraeumen"; dann wird das Modell nie kalt.
        """

        text = str(wert or "").strip().lower()
        if not text:
            return 0.0
        faktoren = {"s": 1.0, "m": 60.0, "h": 3600.0}
        faktor = faktoren.get(text[-1:], 1.0)
        zahl = text[:-1] if text[-1:] in faktoren else text
        try:
            sekunden = float(zahl) * faktor
        except ValueError:
            return 0.0
        return float("inf") if sekunden < 0 else sekunden

    def _erste_frist(self) -> float:
        """Die Frist auf das erste Lebenszeichen - kalt grosszuegig, warm knapp.

        Warm bleibt knapp, weil ein warmes Modell, das nicht antwortet,
        wirklich haengt und der Orb dann schnell ausweichen soll. Kalt
        wird grosszuegig, weil Warten dort nicht Nachsicht ist, sondern
        das Einzige, was hilft: Der naechste Anbieter in der Reihe muesste
        genauso lange laden.
        """

        if self._letzter_erfolg <= 0.0:
            return self._cold_first_token_timeout
        if self._keep_alive_seconds <= 0.0:
            return self._cold_first_token_timeout
        seit = self._now() - self._letzter_erfolg
        if seit >= self._keep_alive_seconds:
            return self._cold_first_token_timeout
        return self._first_token_timeout

    def _erfolg_vermerken(self) -> None:
        """Haelt fest, dass das Modell eben noch im Speicher stand."""

        self._letzter_erfolg = self._now()

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
            "temperature": temperature if temperature is not None else self._temperatur,
            "num_ctx": self._context_window,
        }
        if max_tokens is not None:
            options["num_predict"] = max(max_tokens, self._minimum_predict_tokens)

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
        self._erfolg_vermerken()

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
                        "num_ctx": self._context_window,
                    },
                },
                versuche=2,
            )
        except ProviderError as fehler:
            logger.info("Das lokale Modell ließ sich nicht vorwärmen: %s", fehler)
            return False
        self._erfolg_vermerken()
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
            "temperature": temperature if temperature is not None else self._temperatur,
            "num_ctx": self._context_window,
        }
        if max_tokens is not None:
            options["num_predict"] = max(max_tokens, self._minimum_predict_tokens)

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
        frist = self._erste_frist()
        if frist > self._first_token_timeout:
            logger.info(
                "Das lokale Modell '%s' ist vermutlich kalt; es bekommt %.0f s "
                "statt %.0f s auf das erste Lebenszeichen.",
                self._model,
                frist,
                self._first_token_timeout,
            )
        first_deadline = loop.time() + frist
        received_text = False

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                request = client.build_request(
                    "POST", f"{self._base_url}/api/chat", json=payload
                )
                try:
                    response = await asyncio.wait_for(
                        client.send(request, stream=True),
                        timeout=frist,
                    )
                except asyncio.TimeoutError as error:
                    raise ProviderError(
                        "ollama: Keine Antwortverbindung innerhalb von "
                        f"{frist:.0f} s."
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
                                    f"{frist:.0f} s."
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
                            self._erfolg_vermerken()
                            yield piece
                        if data.get("done"):
                            break
                finally:
                    await response.aclose()
            if not received_text:
                raise ProviderError(
                    "ollama: Der Antwortstrom endete ohne sichtbaren Text."
                )
        except ProviderError:
            raise
        except (httpx.HTTPError, OSError) as error:
            raise ProviderError(f"ollama: Streaming abgebrochen - {error}") from error
