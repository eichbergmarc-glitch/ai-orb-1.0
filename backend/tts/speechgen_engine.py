"""Sprachausgabe über SpeechGen.io (flüssige, natürliche Cloud-Stimme).

SpeechGen ist ein Netzdienst mit sehr natürlichen Stimmen, auch für Deutsch.
Er ist die Antwort auf den wiederkehrenden Wunsch nach einer Stimme, die
nicht nach Maschine klingt – und anders als die lokalen Stimmen (Piper,
SAPI) muss dafür nichts auf dem Rechner gerechnet werden, was ihn zugleich
schnell macht.

## Der Preis, offen benannt

Wie jede Cloud-Stimme schickt SpeechGen den zu sprechenden Text an einen
fremden Server. Das steht gegen das „alles bleibt lokal“ der übrigen
Anlage und ist deshalb eine ausdrückliche Wahl: Die Engine greift nur, wenn
``speechgen`` in ``voice.output.engines`` steht und Zugangsdaten hinterlegt
sind. Ohne sie meldet sie sich als nicht verfügbar, und Piper übernimmt.

## Wie sie arbeitet

Ein POST mit Text, Stimme und den Zugangsdaten; die Antwort ist ein JSON
mit einer Datei-URL, von der die fertige Sprachdatei geladen wird. Es wird
ausdrücklich ``wav`` angefordert – so spielt der Player von AI-Orb die Datei
ohne Umweg ab, ganz ohne zusätzliche Werkzeuge.

## Sicherheit

Token und E-Mail kommen aus Umgebungsvariablen, niemals aus dem Code oder
der Konfiguration. Dort steht nur der Name der Stimme.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)

_API_ENDPOINT = "https://speechgen.io/index.php?r=api/text"


class SpeechGenEngine(TtsEngine):
    """Erzeugt Sprache über den SpeechGen-Netzdienst."""

    name = "speechgen"

    def __init__(self, *, output_directory: Path, options: dict[str, Any] | None = None) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._token_env = str(self.option("token_env", "SPEECHGEN_TOKEN"))
        self._email_env = str(self.option("email_env", "SPEECHGEN_EMAIL"))
        self._voice = str(self.option("voice", "")).strip()

    @property
    def token(self) -> str:
        return os.environ.get(self._token_env, "").strip()

    @property
    def email(self) -> str:
        return os.environ.get(self._email_env, "").strip()

    # --- Verfügbarkeit ---------------------------------------------------------

    def is_available(self) -> bool:
        """Verfügbar nur mit Zugangsdaten und gewählter Stimme.

        Alle drei fehlen im Auslieferungszustand – die Engine ist also von
        sich aus still, bis der Benutzer sie einrichtet. Eine Cloud-Stimme
        darf sich nicht ungefragt einschalten.
        """

        if not self.token or not self.email:
            return False
        if not self._voice:
            logger.warning(
                "SpeechGen: keine Stimme gesetzt. Waehle eine unter "
                "voice.output.speechgen.voice in config.yaml."
            )
            return False
        return True

    def installation_hint(self) -> str:
        if not self.token or not self.email:
            return (
                "SpeechGen ist nicht eingerichtet. Trage SPEECHGEN_TOKEN und "
                "SPEECHGEN_EMAIL in die .env ein und eine Stimme in config.yaml. "
                "Wie, steht in docs/STIMME.md."
            )
        return "SpeechGen: es fehlt die Stimme in config.yaml."

    # --- Erzeugung -------------------------------------------------------------

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        """Fordert die Sprachdatei an und lädt sie herunter."""

        if not self.is_available():
            return SpeechResult(engine=self.name, error=self.installation_hint())

        # Geschwindigkeit von AI-Orb (0.5–2.0) auf SpeechGens Skala (-20..20,
        # 0 = normal) abbilden. Etwas unter normal klingt meist ruhiger.
        speed_percent = int(max(-20, min(20, round((request.speed - 1.0) * 20))))

        fields = {
            "token": self.token,
            "email": self.email,
            "voice": self._voice,
            "text": request.text,
            "format": "wav",
            "speed": str(1.0),          # Feinsteuerung über 'speed_alt' unten
            "speed_alt": str(speed_percent),
            "pitch": str(int(max(-20, min(20, round(request.pitch * 10))))),
        }
        data = urllib.parse.urlencode(fields).encode("utf-8")

        started = self._now()
        try:
            payload = self._post(data)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return SpeechResult(engine=self.name, error=f"SpeechGen nicht erreichbar: {error}")

        status = str(payload.get("status", ""))
        if status not in ("1", "done", "1.0"):
            message = str(payload.get("error") or payload.get("message") or "unbekannter Fehler")
            return SpeechResult(engine=self.name, error=f"SpeechGen meldete: {message}")

        file_url = str(payload.get("file", "")).strip()
        if not file_url:
            return SpeechResult(engine=self.name, error="SpeechGen lieferte keine Datei-URL.")

        try:
            audio = self._download(file_url)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return SpeechResult(engine=self.name, error=f"Download fehlgeschlagen: {error}")

        if not audio:
            return SpeechResult(engine=self.name, error="Die heruntergeladene Datei war leer.")

        try:
            target.write_bytes(audio)
        except OSError as error:
            return SpeechResult(engine=self.name, error=f"Datei nicht speicherbar: {error}")

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            processing_seconds=self._now() - started,
            context={"voice": self._voice, "kosten": payload.get("cost")},
        )

    # --- HTTP ------------------------------------------------------------------

    def _post(self, data: bytes) -> dict[str, Any]:
        request = urllib.request.Request(
            _API_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "-1", "error": raw[:300]}

    @staticmethod
    def _download(url: str) -> bytes:
        with urllib.request.urlopen(url, timeout=45) as response:
            return response.read()

    def voices(self) -> list[dict[str, str]]:
        return [{"engine": self.name, "voice": self._voice or "(nicht gesetzt)"}]
