"""Klare, schnelle deutsche Offline-Stimme mit Supertonic 3.

Supertonic 3 erzeugt 44,1-kHz-Audio mit vier kleinen ONNX-Modulen. Das
Modell arbeitet vollstaendig lokal und ist auf einer normalen CPU deutlich
schneller als die resultierende Wiedergabe. Im Gegensatz zu autoregressiven
Sprachmodellen kann es unter Last nicht minutenlang in einer Tokenfolge
haengen oder den Satz phonetisch fortspinnen.

Im Betrieb wird niemals automatisch heruntergeladen. Die Modellpruefung
verlangt alle Dateien im Orb-Modellcache; dadurch bleibt "offline" wirklich
offline und ein fehlendes Netz verursacht weder DNS-Wartezeiten noch einen
unbemerkten Wechsel zu einer Cloud-Stimme.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import threading
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.german_text import satzzeichen_sprechbar
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.utils.paths import get_models_dir

logger = get_logger(__name__)


class SupertonicEngine(TtsEngine):
    """Supertonic-3-ONNX mit einer fest gewaehlten deutschen Stimme."""

    name = "supertonic"

    _REQUIRED_FILES = (
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
    )

    def __init__(
        self, *, output_directory: Path, options: dict[str, Any] | None = None
    ) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._model_name = str(self.option("model", "supertonic-3")).strip()
        self._voice_name = str(self.option("voice", "M1")).strip().upper() or "M1"
        self._language = str(self.option("language", "de")).strip() or "de"
        self._steps = max(4, min(16, int(self.option("steps", 8))))
        self._threads = max(1, int(self.option("cpu_threads", 6)))
        self._silence_seconds = max(
            0.0, min(0.3, float(self.option("chunk_silence_ms", 70)) / 1000.0)
        )
        self._model: Any | None = None
        self._voice_style: Any | None = None
        self._load_error = ""
        self._load_lock = threading.Lock()
        # Eine ONNX-Sitzung pro Prozess, immer nur ein Synthesezug zugleich.
        # Die Sprachpipeline produziert den Folgesatz bereits waehrend der
        # aktuelle spielt; eine weitere Parallelisierung wuerde nur CPU-
        # Ueberbelegung und damit Stottern erzeugen.
        self._synthesis_lock = threading.Lock()

    @property
    def models_directory(self) -> Path:
        directory = get_models_dir() / "supertonic-3"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _required_paths(self) -> list[Path]:
        paths = [self.models_directory / relative for relative in self._REQUIRED_FILES]
        paths.append(self.models_directory / "voice_styles" / f"{self._voice_name}.json")
        return paths

    def is_available(self) -> bool:
        return bool(
            importlib.util.find_spec("supertonic") is not None
            and all(path.is_file() and path.stat().st_size > 0 for path in self._required_paths())
        )

    def installation_hint(self) -> str:
        return (
            "Fuer die feste deutsche Offline-Stimme fehlen 'supertonic==1.3.1' "
            "oder die einmalig geladenen Supertonic-3-Modelldateien im "
            f"Ordner {self.models_directory}."
        )

    def _load(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._load_error:
            return None

        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_error:
                return None
            try:
                from supertonic import TTS

                if not self.is_available():
                    raise FileNotFoundError(self.installation_hint())
                self._model = TTS(
                    model=self._model_name,
                    model_dir=self.models_directory,
                    auto_download=False,
                    intra_op_num_threads=self._threads,
                    inter_op_num_threads=1,
                )
                self._voice_style = self._model.get_voice_style(self._voice_name)
                logger.info(
                    "Supertonic-Stimme geladen (Modell=%s, Stimme=%s, "
                    "Sprache=%s, Threads=%d, lokal).",
                    self._model_name,
                    self._voice_name,
                    self._language,
                    self._threads,
                )
            except Exception as error:  # noqa: BLE001
                self._load_error = str(error)
                self._model = None
                self._voice_style = None
                logger.exception("Supertonic liess sich nicht lokal laden.")
                return None
        return self._model

    def target_path(self, request: SpeechRequest) -> Path:
        settings = "|".join(
            (
                request.cache_key(),
                self._model_name,
                self._voice_name,
                self._language,
                str(self._steps),
                str(self._silence_seconds),
            )
        )
        digest = hashlib.sha256(settings.encode("utf-8")).hexdigest()[:24]
        return self._output_directory / f"{self.name}-{digest}.wav"

    @staticmethod
    def _write_wave(target: Path, waveform: Any, sample_rate: int) -> None:
        import numpy as np

        pcm = (
            np.asarray(waveform, dtype=np.float32).reshape(-1).clip(-1.0, 1.0)
            * 32767.0
        ).astype("<i2")
        temporary = target.with_suffix(".tmp.wav")
        with wave.open(str(temporary), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(int(sample_rate))
            handle.writeframes(pcm.tobytes())
        temporary.replace(target)

    def _sprechen(self, model: Any, text: str, speed: float) -> tuple[Any, float]:
        """Ein Aufruf des Modells unter dem Erzeugungs-Schloss."""

        with self._synthesis_lock:
            return model.synthesize(
                text,
                voice_style=self._voice_style,
                total_steps=self._steps,
                speed=speed,
                silence_duration=self._silence_seconds,
                lang=self._language,
            )

    @staticmethod
    def _unbekannte_zeichen(fehler: Exception) -> list[str]:
        """Liest aus Supertonics Fehlermeldung, welche Zeichen es nicht kennt.

        Die Meldung hat die Form ``Found 1 unsupported character(s): ['„']``.
        Alles andere ergibt eine leere Liste - dann ist es ein anderer
        Fehler, und der wird nicht verschleiert.
        """

        meldung = str(fehler)
        if "unsupported character" not in meldung:
            return []
        return re.findall(r"'(.+?)'", meldung.split(":", 1)[-1])

    def synthesize_blocking(
        self, request: SpeechRequest, target: Path
    ) -> SpeechResult:
        started = self._now()
        model = self._load()
        if model is None or self._voice_style is None:
            return SpeechResult(
                engine=self.name,
                error=self._load_error or self.installation_hint(),
                context={"fatal_for_session": True, "local": True},
            )

        # Die globale Orb-Regie liefert bereits ein leicht variiertes Tempo.
        # Supertonic bleibt im gut verstaendlichen Bereich; keine Emotion darf
        # aus einer Facherklaerung ein verschlucktes Schnellsprechen machen.
        speed = max(0.90, min(1.10, float(request.speed)))

        # Supertonic prueft seinen Zeichenvorrat streng: EIN unbekanntes
        # Zeichen, und die ganze Ausgabe bricht ab. Im Betrieb geschehen mit
        # typografischen Anfuehrungszeichen („ und ›) - der Orb blieb dann
        # mitten im Satz stumm. Die bekannten Faelle werden vorab ersetzt.
        text = satzzeichen_sprechbar(request.text)

        try:
            waveform, duration = self._sprechen(model, text, speed)
        except ValueError as error:
            # Das Sicherheitsnetz fuer alles, was die Ersetzungstabelle noch
            # nicht kennt: Die Meldung nennt die Zeichen - genau die werden
            # entfernt, ein zweiter Versuch, und die Tabelle sollte um sie
            # ergaenzt werden. Ein exotisches Zeichen zu verschlucken ist
            # besser, als den Satz nicht zu sprechen.
            zeichen = self._unbekannte_zeichen(error)
            if not zeichen:
                target.unlink(missing_ok=True)
                logger.exception("Supertonic konnte den Text nicht sprechen.")
                return SpeechResult(
                    engine=self.name,
                    error=f"Supertonic ist fehlgeschlagen: {error}",
                    context={"local": True},
                )
            logger.warning(
                "Supertonic kennt %s nicht - die Zeichen werden entfernt. "
                "Bitte in backend/tts/german_text.py nachtragen.",
                ", ".join(repr(z) for z in zeichen),
            )
            for einzel in zeichen:
                text = text.replace(einzel, " ")
            try:
                waveform, duration = self._sprechen(model, text, speed)
            except Exception as error2:  # noqa: BLE001
                target.unlink(missing_ok=True)
                logger.exception("Supertonic konnte den Text nicht sprechen.")
                return SpeechResult(
                    engine=self.name,
                    error=f"Supertonic ist fehlgeschlagen: {error2}",
                    context={"local": True},
                )
        except Exception as error:  # noqa: BLE001
            target.unlink(missing_ok=True)
            logger.exception("Supertonic konnte den Text nicht sprechen.")
            return SpeechResult(
                engine=self.name,
                error=f"Supertonic ist fehlgeschlagen: {error}",
                context={"local": True},
            )

        try:
            self._write_wave(target, waveform, int(model.sample_rate))
        except Exception as error:  # noqa: BLE001
            target.unlink(missing_ok=True)
            logger.exception("Supertonic konnte die WAV-Datei nicht schreiben.")
            return SpeechResult(
                engine=self.name,
                error=f"Supertonic ist fehlgeschlagen: {error}",
                context={"local": True},
            )

        if not target.is_file() or target.stat().st_size <= 44:
            return SpeechResult(
                engine=self.name,
                error="Supertonic hat keine hoerbare WAV-Datei erzeugt.",
                context={"local": True},
            )

        elapsed = self._now() - started
        audio_seconds = self.wav_duration(target)
        logger.info(
            "Supertonic: Erzeugung %.3f s, Audio %.3f s, RTF %.3f.",
            elapsed,
            audio_seconds,
            elapsed / max(audio_seconds, 0.001),
        )
        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=audio_seconds,
            processing_seconds=elapsed,
            context={
                "model": self._model_name,
                "voice": self._voice_name,
                "language": self._language,
                "sample_rate": int(model.sample_rate),
                "steps": self._steps,
                "local": True,
                # Stop-Whisper darf nicht parallel zur ONNX-Erzeugung des
                # naechsten Satzes laufen. VAD-Barge-in bleibt aktiv.
                "avoid_stop_transcription": True,
            },
        )

    def voices(self) -> list[dict[str, str]]:
        names = [f"M{index}" for index in range(1, 6)] + [
            f"F{index}" for index in range(1, 6)
        ]
        return [
            {
                "name": name,
                "language": "de-DE",
                "installed": "ja"
                if (self.models_directory / "voice_styles" / f"{name}.json").is_file()
                else "nein",
            }
            for name in names
        ]

    def status(self) -> dict[str, Any]:
        base = super().status()
        base.update(
            {
                "loaded": self._model is not None,
                "voice": self._voice_name,
                "model": self._model_name,
                "language": self._language,
                "model_cached": all(path.is_file() for path in self._required_paths()),
                "models_directory": str(self.models_directory),
                "sample_rate": 44100,
                "local": True,
                "quality": "klare 44,1-kHz-ONNX-Neuralstimme",
            }
        )
        return base
