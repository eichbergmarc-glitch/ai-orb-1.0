"""Schnelle natuerliche Microsoft-Neuralstimme ohne eigenen API-Schluessel.

``edge-tts`` nutzt denselben Online-Sprachdienst wie die Vorlesefunktion
von Microsoft Edge. Er ist kein Offlineverfahren: Der Text verlaesst den
Rechner. Im normalen Automatikbetrieb ist er aber ein wesentlich
natuerlicherer und zugleich schnellerer Rueckfall als Piper, wenn die
bezahlten Cloud-Schluessel gerade nicht funktionieren.

Der Dienst liefert MP3. AI-Orb arbeitet intern bewusst nur mit WAV; PyAV
wandelt deshalb direkt im Speicherpfad in 24-kHz-Mono-PCM um. Die kleine
Zwischendatei wird immer entfernt.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)


class EdgeNeuralEngine(TtsEngine):
    """Deutsche Neuralstimme aus Microsoft Edge mit kurzer Anlaufzeit."""

    name = "edge_neural"

    def __init__(
        self,
        *,
        output_directory: Path,
        options: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._voice = str(
            self.option("voice", "de-DE-FlorianMultilingualNeural")
        ).strip()
        self._base_rate = int(self.option("rate_percent", 2))
        self._base_pitch = int(self.option("pitch_hz", 0))
        self._timeout_seconds = max(
            1.0, float(self.option("timeout_seconds", 4.0))
        )

    def is_available(self) -> bool:
        return bool(
            self._voice
            and importlib.util.find_spec("edge_tts") is not None
            and importlib.util.find_spec("av") is not None
        )

    def installation_hint(self) -> str:
        return (
            "Fuer die natuerliche Edge-Neuralstimme fehlen edge-tts oder PyAV. "
            "Installiere requirements-voice.txt."
        )

    @staticmethod
    def _signed(value: int, suffix: str) -> str:
        return f"{value:+d}{suffix}"

    def _controls(self, request: SpeechRequest) -> dict[str, str]:
        # ``rate`` ist ein relativer Prozentwert. Die globale Orb-
        # Geschwindigkeit und die erkannte Gefuehlslage stecken bereits in
        # request.speed. Der enge Rahmen verhindert gehetzte oder gedehnte
        # Sprache und laesst dennoch kleine spontane Temposchwankungen zu.
        rate = self._base_rate + round((request.speed - 1.0) * 100)
        rate = max(-12, min(15, rate))
        pitch = self._base_pitch + round(request.pitch * 7)
        pitch = max(-25, min(25, pitch))
        volume = round((request.volume - 1.0) * 100)
        volume = max(-20, min(10, volume))
        return {
            "rate": self._signed(rate, "%"),
            "pitch": self._signed(pitch, "Hz"),
            "volume": self._signed(volume, "%"),
        }

    def target_path(self, request: SpeechRequest) -> Path:
        controls = self._controls(request)
        raw = "|".join(
            (
                request.cache_key(),
                request.emotion,
                self._voice,
                controls["rate"],
                controls["pitch"],
                controls["volume"],
            )
        )
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return self._output_directory / f"{self.name}-{digest}.wav"

    def _synthesize_mp3(
        self,
        request: SpeechRequest,
        destination: Path,
        controls: dict[str, str],
    ) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(
            request.text,
            self._voice,
            rate=controls["rate"],
            volume=controls["volume"],
            pitch=controls["pitch"],
        )
        async def _save() -> None:
            await asyncio.wait_for(
                communicate.save(str(destination)),
                timeout=self._timeout_seconds,
            )

        asyncio.run(_save())

    @staticmethod
    def _decode_mp3(source: Path, destination: Path) -> None:
        import av

        with av.open(str(source)) as container:
            audio_stream = next(
                (stream for stream in container.streams if stream.type == "audio"),
                None,
            )
            if audio_stream is None:
                raise ValueError("MP3 enthaelt keine Audiospur")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
            with wave.open(str(destination), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(24000)
                for frame in container.decode(audio_stream):
                    for converted in resampler.resample(frame):
                        handle.writeframes(converted.to_ndarray().tobytes())
                for converted in resampler.resample(None):
                    handle.writeframes(converted.to_ndarray().tobytes())

    def synthesize_blocking(
        self,
        request: SpeechRequest,
        target: Path,
    ) -> SpeechResult:
        if not self.is_available():
            return SpeechResult(engine=self.name, error=self.installation_hint())

        controls = self._controls(request)
        intermediate = target.with_name(f"{target.stem}-edge.mp3")
        started = self._now()
        try:
            self._synthesize_mp3(request, intermediate, controls)
            self._decode_mp3(intermediate, target)
        except Exception as error:  # noqa: BLE001 - Netzwerk und Decoder sind Rueckfaelle.
            target.unlink(missing_ok=True)
            logger.warning("Edge-Neuralstimme ist fehlgeschlagen: %s", error)
            return SpeechResult(
                engine=self.name,
                error=f"Edge-Neuralstimme ist nicht erreichbar: {error}",
            )
        finally:
            intermediate.unlink(missing_ok=True)

        if not target.is_file() or target.stat().st_size <= 44:
            return SpeechResult(
                engine=self.name,
                error="Edge-Neuralstimme lieferte keine hoerbare WAV-Datei.",
            )
        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={
                "voice": self._voice,
                "rate": controls["rate"],
                "pitch": controls["pitch"],
                "local": False,
            },
        )

    def voices(self) -> list[dict[str, str]]:
        return [{"engine": self.name, "voice": self._voice, "language": "de-DE"}]

    def status(self) -> dict[str, Any]:
        status = super().status()
        status.update(
            {
                "voice": self._voice,
                "service": "Microsoft Edge Neural TTS",
                "local": False,
                "no_api_key": True,
            }
        )
        return status
