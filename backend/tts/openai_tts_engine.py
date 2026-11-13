"""Schnelle, direkt steuerbare Cloud-Sprachausgabe ueber OpenAI.

Diese Engine ist der natuerliche Online-Rueckfall, wenn die ausgewaehlte
ElevenLabs-Stimme wegen eines abgelaufenen Schluessels oder fehlenden
Guthabens nicht sprechen kann. Anders als Piper kann das Sprachmodell die
Prosodie aus einer ausdruecklichen Regieanweisung ableiten: Satzmelodie,
Tempo, Pausen, Direktheit und emotionale Zurueckhaltung.

Die Antwort wird als unkomprimiertes WAV angefordert. Das spart einen
Decoder und ist fuer kurze, bereits satzweise gestreamte Orb-Antworten der
kleinste robuste Weg bis zum vorhandenen WAV-Player.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)

_API_URL = "https://api.openai.com/v1/audio/speech"

_EMOTION_REGIE: dict[str, str] = {
    "freundlich": "Klinge zugewandt und wach, aber nicht dienstleistungsmaessig.",
    "aufmerksam": "Klinge praesent, konzentriert und unmittelbar ansprechbar.",
    "nachdenklich": "Klinge ueberlegt; nur eine kurze Sinnpause, kein dramatisches Zoegern.",
    "erfreut": "Lass echte, knappe Freude hoerbar werden, ohne Uebertreibung.",
    "bedauernd": "Klinge ruhig und ernst, nicht sentimental.",
    "dringlich": "Sprich klar und bestimmt, etwas zuegiger, aber nie gehetzt.",
    "leise": "Sprich ruhig und weich, weiterhin deutlich.",
}


class OpenAITtsEngine(TtsEngine):
    """Erzeugt natuerlich regierte deutsche Sprache mit geringer Latenz."""

    name = "openai_tts"

    def __init__(
        self,
        *,
        output_directory: Path,
        options: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._api_key_env = str(self.option("api_key_env", "OPENAI_API_KEY"))
        self._model = str(self.option("model", "gpt-4o-mini-tts")).strip()
        self._voice = str(self.option("voice", "cedar")).strip()
        self._instructions = " ".join(
            str(self.option("instructions", "")).split()
        ).strip()
        self._timeout = max(5.0, float(self.option("timeout", 25)))

    @property
    def api_key(self) -> str:
        return os.environ.get(self._api_key_env, "").strip()

    def is_available(self) -> bool:
        return bool(self.api_key and self._model and self._voice)

    def installation_hint(self) -> str:
        return (
            "OpenAI-Sprachausgabe ist nicht eingerichtet. Hinterlege einen "
            f"gueltigen Schluessel in {self._api_key_env}."
        )

    def _regie(self, request: SpeechRequest) -> str:
        teile = [self._instructions]
        emotion = _EMOTION_REGIE.get(request.emotion.strip().lower(), "")
        if emotion:
            teile.append(emotion)
        if request.speed >= 1.06:
            teile.append("Waehle ein zuegiges, klares Gespraechstempo.")
        elif request.speed <= 0.93:
            teile.append(
                "Sprich eine Spur ruhiger, aber ohne gedehnte Silben oder lange Pausen."
            )
        return " ".join(teil for teil in teile if teil).strip()

    def target_path(self, request: SpeechRequest) -> Path:
        einstellungen = "|".join(
            (
                request.cache_key(),
                request.emotion,
                self._model,
                self._voice,
                self._regie(request),
                "wav",
            )
        )
        digest = hashlib.sha256(einstellungen.encode("utf-8")).hexdigest()[:24]
        return self._output_directory / f"{self.name}-{digest}.wav"

    def synthesize_blocking(
        self,
        request: SpeechRequest,
        target: Path,
    ) -> SpeechResult:
        if not self.is_available():
            return SpeechResult(engine=self.name, error=self.installation_hint())

        payload = {
            "model": self._model,
            "voice": request.voice.strip() or self._voice,
            "input": request.text,
            "instructions": self._regie(request),
            "response_format": "wav",
        }
        # Strom statt Datei (13.11.2026): Bisher wartete der Orb, bis der
        # ganze Satz als WAV fertig war - gemessen 1,1 bis 1,6 s vor der
        # ersten Silbe. Als PCM-Strom beginnt er nach den ersten Millisekunden.
        from backend.tts.base_engine import DATEI_NOETIG

        if bool(self.option("streaming", True)) and not DATEI_NOETIG.get():
            ergebnis = self._als_strom(dict(payload, response_format="pcm"), target)
            if ergebnis is not None:
                return ergebnis
        http_request = urllib.request.Request(
            _API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "audio/wav",
            },
            method="POST",
        )

        started = self._now()
        try:
            with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
                audio = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:400]
            hinweis = {
                401: "Der OPENAI_API_KEY wurde abgelehnt.",
                403: "Der Schluessel darf das Sprachmodell nicht verwenden.",
                429: "Das API-Limit oder Guthaben ist erreicht.",
            }.get(error.code, detail or "Unbekannter API-Fehler")
            logger.warning("OpenAI-TTS %s: %s", error.code, hinweis)
            return SpeechResult(
                engine=self.name,
                error=f"OpenAI-TTS antwortete mit {error.code}: {hinweis}",
                context={"fatal_for_session": error.code in (401, 403)},
            )
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return SpeechResult(
                engine=self.name,
                error=f"OpenAI-TTS ist nicht erreichbar: {error}",
            )

        if len(audio) <= 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            return SpeechResult(
                engine=self.name,
                error="OpenAI-TTS lieferte keine gueltige WAV-Datei.",
            )
        try:
            target.write_bytes(audio)
            with wave.open(str(target), "rb") as handle:
                if handle.getnframes() < 1:
                    raise ValueError("leere WAV-Datei")
        except (OSError, EOFError, ValueError, wave.Error) as error:
            target.unlink(missing_ok=True)
            return SpeechResult(
                engine=self.name,
                error=f"OpenAI-TTS-Audio ist unlesbar: {error}",
            )

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={
                "model": self._model,
                "voice": payload["voice"],
                "instructions": payload["instructions"],
                "local": False,
            },
        )

    def _als_strom(self, payload: dict[str, Any], target: Path) -> SpeechResult | None:
        """Startet die Sprachausgabe als PCM-Strom (24 kHz, 16 Bit, mono).

        ``None`` heisst: Strom ging nicht - der gewohnte Weg uebernimmt.
        """

        import threading

        from backend.tts.pocket_tts_engine import PcmAudioStream

        anfrage = urllib.request.Request(
            _API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        started = self._now()
        try:
            antwort = urllib.request.urlopen(anfrage, timeout=self._timeout)
        except Exception as fehler:  # noqa: BLE001
            logger.info("OpenAI-TTS-Strom nicht moeglich (%s) - Datei-Weg.", fehler)
            return None

        strom = PcmAudioStream(sample_rate=24000)

        def lesen() -> None:
            teile: list[bytes] = []
            rest = b""
            try:
                with antwort:
                    while not strom.cancelled:
                        block = antwort.read(4800)
                        if not block:
                            break
                        block = rest + block
                        gerade = len(block) // 2 * 2
                        rest = block[gerade:]
                        if gerade:
                            teile.append(block[:gerade])
                            strom.push(block[:gerade])
                daten = b"".join(teile)
                if daten:
                    with wave.open(str(target), "wb") as datei:
                        datei.setnchannels(1)
                        datei.setsampwidth(2)
                        datei.setframerate(24000)
                        datei.writeframes(daten)
                strom.finish(duration_seconds=len(daten) / 48000.0,
                             error="" if daten else "OpenAI-TTS lieferte keinen Ton.")
            except Exception as fehler:  # noqa: BLE001
                strom.finish(error=f"OpenAI-TTS-Strom abgebrochen: {fehler}")

        threading.Thread(target=lesen, name="openai-tts-strom", daemon=True).start()
        if not strom.wait_for_first(self._timeout) or (strom.error and not strom.has_audio):
            strom.cancel()
            return None
        # Ein kleiner Vorsprung gegen Netzschwankungen - sonst stockt der
        # Satz, wenn ein Paket einen Moment laenger braucht.
        vorsprung = max(0.0, min(1.0, float(self.option("prebuffer_ms", 250)) / 1000.0))
        strom.wait_for_buffer(vorsprung, 3.0)
        return SpeechResult(
            audio_path=target,
            engine=self.name,
            processing_seconds=self._now() - started,
            context={
                "model": self._model,
                "voice": payload["voice"],
                "instructions": payload["instructions"],
                "local": False,
                "streaming": True,
                "pcm_stream": strom,
            },
        )

    def voices(self) -> list[dict[str, str]]:
        return [{"engine": self.name, "voice": self._voice}]

    def status(self) -> dict[str, Any]:
        status = super().status()
        status.update(
            {
                "voice": self._voice,
                "model": self._model,
                "style_controlled": bool(self._instructions),
                "low_latency_format": "wav",
                "local": False,
            }
        )
        return status
