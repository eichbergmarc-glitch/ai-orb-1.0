"""Sprachausgabe über Kokoro.

Kokoro ist ein kompaktes neuronales Sprachmodell (rund 82 Millionen
Parameter), das auf einer gewöhnlichen CPU schneller als in Echtzeit
arbeitet und deutlich natürlicher klingt als die Windows-Sprachausgabe.

Eine Einschränkung, die du kennen solltest: Kokoro ist auf Englisch,
Spanisch, Französisch, Hindi, Italienisch, Japanisch, Portugiesisch und
Chinesisch trainiert. **Deutsch gehört nicht dazu.** Deutscher Text wird
zwar ausgesprochen, aber mit hörbar fremdem Akzent, weil die Lautfolgen
über das englische Modell laufen.

Deshalb ist in ``config.yaml`` standardmäßig die Reihenfolge Piper → SAPI →
Kokoro eingetragen: Piper hat sehr gute deutsche Stimmen, SAPI ist immer da,
und Kokoro steht bereit, falls du auf Englisch umstellst oder Kokoro später
Deutsch lernt. Die Reihenfolge lässt sich jederzeit ändern.
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine

logger = get_logger(__name__)

#: Abtastrate, mit der Kokoro arbeitet.
SAMPLE_RATE = 24000

#: Sprachkürzel von Kokoro. ``a`` = amerikanisches Englisch.
LANGUAGE_CODES: dict[str, str] = {
    "en": "a",
    "en-us": "a",
    "en-gb": "b",
    "es": "e",
    "fr": "f",
    "hi": "h",
    "it": "i",
    "ja": "j",
    "pt": "p",
    "zh": "z",
}


class KokoroEngine(TtsEngine):
    """Neuronale Sprachausgabe über das Paket ``kokoro``."""

    name = "kokoro"

    def __init__(self, *, output_directory: Path, options: dict[str, Any] | None = None) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._pipeline: Any | None = None
        self._load_failed = False

    # --- Verfügbarkeit -----------------------------------------------------------

    def is_available(self) -> bool:
        try:
            import kokoro  # noqa: F401
            import numpy  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    def installation_hint(self) -> str:
        return (
            "Für Kokoro fehlen Pakete. Installiere sie mit:\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt\n"
            "Beim ersten Sprechen lädt Kokoro etwa 330 MB Modelldaten herunter.\n"
            "Hinweis: Kokoro beherrscht kein Deutsch – für deutsche Sprache sind "
            "Piper oder die Windows-Sprachausgabe die bessere Wahl."
        )

    # --- Modell ------------------------------------------------------------------

    def _language_code(self) -> str:
        configured = str(self.option("language", "en")).strip().lower()
        return LANGUAGE_CODES.get(configured, "a")

    def _load(self) -> Any | None:
        """Lädt die Kokoro-Pipeline (blockierend)."""

        if self._pipeline is not None:
            return self._pipeline
        if self._load_failed:
            return None

        try:
            from kokoro import KPipeline
        except (ImportError, OSError):
            logger.error(self.installation_hint())
            self._load_failed = True
            return None

        try:
            logger.info("Kokoro wird geladen. Beim ersten Mal dauert das einige Minuten.")
            self._pipeline = KPipeline(lang_code=self._language_code())
        except Exception:  # noqa: BLE001 - jede Ursache soll verständlich gemeldet werden.
            logger.exception("Kokoro konnte nicht geladen werden.")
            self._load_failed = True
            return None

        logger.info("Kokoro ist bereit.")
        return self._pipeline

    # --- Erzeugung ---------------------------------------------------------------

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        started = self._now()

        pipeline = self._load()
        if pipeline is None:
            return SpeechResult(engine=self.name, error=self.installation_hint())

        voice = request.voice or str(self.option("voice", "af_heart"))

        try:
            import numpy as np

            chunks: list[Any] = []
            for _, _, audio in pipeline(request.text, voice=voice, speed=request.speed):
                if audio is None:
                    continue
                # Kokoro liefert je nach Fassung einen Torch-Tensor oder ein
                # NumPy-Feld; beides wird hier auf NumPy vereinheitlicht.
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))

            if not chunks:
                return SpeechResult(engine=self.name, error="Kokoro hat kein Audio geliefert.")

            samples = np.concatenate(chunks)

            # Lautstärke anwenden und begrenzen, damit nichts übersteuert.
            samples = np.clip(samples * float(request.volume), -1.0, 1.0)
            pcm = (samples * 32767.0).astype(np.int16)

            with wave.open(str(target), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(SAMPLE_RATE)
                handle.writeframes(pcm.tobytes())

        except Exception as error:  # noqa: BLE001
            logger.exception("Kokoro konnte den Text nicht sprechen.")
            return SpeechResult(engine=self.name, error=f"Kokoro ist fehlgeschlagen: {error}")

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={"voice": voice, "language": self._language_code()},
        )

    # --- Auskunft ------------------------------------------------------------------

    def voices(self) -> list[dict[str, str]]:
        """Die gebräuchlichen Kokoro-Stimmen.

        Kokoro führt keine abfragbare Liste; dies sind die dokumentierten
        Namen der Fassung 1.0.
        """

        return [
            {"name": "af_heart", "language": "en-us", "gender": "weiblich"},
            {"name": "af_bella", "language": "en-us", "gender": "weiblich"},
            {"name": "af_nicole", "language": "en-us", "gender": "weiblich"},
            {"name": "am_michael", "language": "en-us", "gender": "männlich"},
            {"name": "am_puck", "language": "en-us", "gender": "männlich"},
            {"name": "bf_emma", "language": "en-gb", "gender": "weiblich"},
            {"name": "bm_george", "language": "en-gb", "gender": "männlich"},
        ]

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["loaded"] = self._pipeline is not None
        base["language"] = self._language_code()
        base["note"] = "Beherrscht kein Deutsch – für deutschen Text Piper oder SAPI verwenden."
        return base
