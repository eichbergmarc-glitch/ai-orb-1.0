"""Schneller lokaler Stimmklon aus Piper und OpenVoice V2.

Piper erzeugt die deutsche Aussprache und Prosodie. Der deutlich kleinere
OpenVoice-Konverter uebertraegt danach die Klangfarbe der autorisierten
ElevenLabs-Referenz. Anders als autoregressive Klonmodelle laeuft diese
Kombination auf der CPU knapp schneller als die erzeugte Aufnahme und kann
deshalb im Satz-Streaming ohne wachsende Pausen sprechen.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.tts.piper_engine import PiperEngine
from backend.utils.paths import get_models_dir, get_project_root

logger = get_logger(__name__)


class _ToneColorConverter:
    """Nur der OpenVoice-Konverter, ohne Gradio, Whisper und MeloTTS."""

    def __init__(self, config_path: Path, checkpoint_path: Path) -> None:
        import torch
        from openvoice import utils
        from openvoice.models import SynthesizerTrn

        self._torch = torch
        self.hps = utils.get_hparams_from_file(str(config_path))
        self.model = SynthesizerTrn(
            len(getattr(self.hps, "symbols", [])),
            self.hps.data.filter_length // 2 + 1,
            n_speakers=self.hps.data.n_speakers,
            **self.hps.model,
        ).to("cpu")
        checkpoint = torch.load(
            str(checkpoint_path), map_location="cpu", weights_only=True
        )
        self.model.load_state_dict(checkpoint["model"], strict=False)
        self.model.eval()

    def _spectrogram(self, audio_path: Path) -> Any:
        import librosa
        from openvoice.mel_processing import spectrogram_torch

        audio, _ = librosa.load(
            str(audio_path), sr=int(self.hps.data.sampling_rate), mono=True
        )
        samples = self._torch.from_numpy(audio).float().unsqueeze(0)
        return spectrogram_torch(
            samples,
            self.hps.data.filter_length,
            self.hps.data.sampling_rate,
            self.hps.data.hop_length,
            self.hps.data.win_length,
            center=False,
        )

    def extract_se(self, audio_path: Path) -> Any:
        spec = self._spectrogram(audio_path)
        with self._torch.inference_mode():
            return self.model.ref_enc(spec.transpose(1, 2)).unsqueeze(-1).detach()

    def convert(
        self,
        source_path: Path,
        source_se: Any,
        target_se: Any,
        target_path: Path,
        *,
        tau: float,
    ) -> None:
        import soundfile

        spec = self._spectrogram(source_path)
        lengths = self._torch.LongTensor([spec.size(-1)])
        with self._torch.inference_mode():
            waveform = self.model.voice_conversion(
                spec,
                lengths,
                sid_src=source_se,
                sid_tgt=target_se,
                tau=tau,
            )[0][0, 0].cpu().float().numpy()
        # PCM16 bleibt mit winsound, der Dauerpruefung und dem Orb-Player
        # kompatibel. OpenVoice liefert ansonsten standardmaessig Float-WAV.
        soundfile.write(
            str(target_path),
            waveform,
            int(self.hps.data.sampling_rate),
            subtype="PCM_16",
        )


class OpenVoiceCloneEngine(TtsEngine):
    """CPU-schneller lokaler Klon der autorisierten Orb-Referenzstimme."""

    name = "openvoice_clone"

    _SOURCE_TEXT = (
        "Dies ist eine ruhige deutsche Referenzstimme. Sie spricht klar, "
        "natürlich und mit gleichmäßigem Tempo."
    )

    def __init__(
        self, *, output_directory: Path, options: dict[str, Any] | None = None
    ) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._converter: _ToneColorConverter | None = None
        self._source_se: Any | None = None
        self._target_se: Any | None = None
        self._load_error = ""
        self._load_lock = threading.Lock()
        self._synthesis_lock = threading.Lock()
        self._piper = PiperEngine(
            output_directory=output_directory,
            options={
                "voice": str(self.option("base_voice", "de_DE-thorsten-high")),
                "noise_scale": float(self.option("noise_scale", 0.667)),
                "noise_w": float(self.option("noise_w", 0.8)),
            },
        )

    @property
    def reference_path(self) -> Path:
        raw = Path(str(self.option("reference_audio", "data/voice/orb-reference.wav")))
        return raw if raw.is_absolute() else get_project_root() / raw

    @property
    def source_reference_path(self) -> Path:
        raw = Path(
            str(
                self.option(
                    "source_reference",
                    "data/voice/piper-source-reference.wav",
                )
            )
        )
        return raw if raw.is_absolute() else get_project_root() / raw

    @property
    def models_directory(self) -> Path:
        directory = get_models_dir() / "openvoice"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def source_directory(self) -> Path:
        raw = Path(
            str(
                self.option(
                    "source_directory",
                    "runtime/openvoice-source",
                )
            )
        )
        return raw if raw.is_absolute() else get_project_root() / raw

    @property
    def converter_directory(self) -> Path:
        return self.models_directory / "converter"

    def _model_files_exist(self) -> bool:
        return all(
            path.is_file()
            for path in (
                self.converter_directory / "config.json",
                self.converter_directory / "checkpoint.pth",
                self.source_directory / "openvoice" / "models.py",
            )
        )

    def is_available(self) -> bool:
        if not self.reference_path.is_file() or not self._model_files_exist():
            return False
        if not self._piper.is_available():
            return False
        try:
            import librosa  # noqa: F401
            import soundfile  # noqa: F401
            import torch  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    def installation_hint(self) -> str:
        return (
            "Fuer den schnellen lokalen Stimmklon fehlen OpenVoice V2, Piper "
            f"oder die autorisierte Referenz ({self.reference_path}). Starte "
            "scripts\\download-openvoice.py einmal mit Internetverbindung."
        )

    @staticmethod
    def _file_hash(path: Path) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()[:20]
        except OSError:
            return "missing"

    def _embedding_path(self, role: str, audio_path: Path) -> Path:
        checkpoint = self.converter_directory / "checkpoint.pth"
        try:
            checkpoint_stat = checkpoint.stat()
            checkpoint_version = (
                f"{checkpoint_stat.st_size}:{checkpoint_stat.st_mtime_ns}"
            )
        except OSError:
            checkpoint_version = "missing"
        identity = hashlib.sha256(
            (
                f"{role}|{self._file_hash(audio_path)}|"
                f"{checkpoint_version}"
            ).encode("utf-8")
        ).hexdigest()[:24]
        directory = self.models_directory / "embeddings"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{role}-{identity}.pt"

    def _load_embedding(
        self, converter: _ToneColorConverter, role: str, audio_path: Path
    ) -> Any:
        import torch

        cache_path = self._embedding_path(role, audio_path)
        if cache_path.is_file():
            return torch.load(str(cache_path), map_location="cpu", weights_only=True)
        embedding = converter.extract_se(audio_path)
        torch.save(embedding.cpu(), str(cache_path))
        return embedding

    def _ensure_source_reference(self) -> bool:
        path = self.source_reference_path
        if path.is_file() and path.stat().st_size > 44:
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        result = self._piper.synthesize_blocking(
            SpeechRequest(text=self._SOURCE_TEXT),
            path,
        )
        if result.succeeded:
            return True
        self._load_error = result.error
        return False

    def _load(self) -> _ToneColorConverter | None:
        if self._converter is not None:
            return self._converter
        if self._load_error:
            return None
        with self._load_lock:
            if self._converter is not None:
                return self._converter
            if self._load_error:
                return None
            try:
                if not self.is_available():
                    self._load_error = self.installation_hint()
                    return None
                if not self._ensure_source_reference():
                    return None
                source = str(self.source_directory)
                if source not in sys.path:
                    sys.path.insert(0, source)
                self._converter = _ToneColorConverter(
                    self.converter_directory / "config.json",
                    self.converter_directory / "checkpoint.pth",
                )
                self._source_se = self._load_embedding(
                    self._converter, "source", self.source_reference_path
                )
                self._target_se = self._load_embedding(
                    self._converter, "target", self.reference_path
                )
                logger.info(
                    "Schneller lokaler Orb-Stimmklon geladen "
                    "(Piper %s + OpenVoice V2, CPU).",
                    self.option("base_voice", "de_DE-thorsten-high"),
                )
            except Exception as error:  # noqa: BLE001
                self._converter = None
                self._load_error = str(error)
                logger.exception("Der schnelle lokale Stimmklon liess sich nicht laden.")
                return None
        return self._converter

    def target_path(self, request: SpeechRequest) -> Path:
        settings = "|".join(
            (
                request.cache_key(),
                self._file_hash(self.reference_path),
                str(self.option("base_voice", "de_DE-thorsten-high")),
                str(self.option("tau", 0.3)),
                "openvoice-v2",
            )
        )
        digest = hashlib.sha256(settings.encode("utf-8")).hexdigest()[:24]
        return self._output_directory / f"{self.name}-{digest}.wav"

    def synthesize_blocking(
        self, request: SpeechRequest, target: Path
    ) -> SpeechResult:
        started = self._now()
        converter = self._load()
        if converter is None:
            return SpeechResult(
                engine=self.name,
                error=self._load_error or self.installation_hint(),
            )

        source_path = target.with_name(f"{target.stem}-source.wav")
        try:
            with self._synthesis_lock:
                base = self._piper.synthesize_blocking(request, source_path)
                if not base.succeeded:
                    return SpeechResult(engine=self.name, error=base.error)
                converter.convert(
                    source_path,
                    self._source_se,
                    self._target_se,
                    target,
                    tau=float(self.option("tau", 0.3)),
                )
        except Exception as error:  # noqa: BLE001
            logger.exception("Der schnelle lokale Stimmklon konnte nicht sprechen.")
            return SpeechResult(
                engine=self.name,
                error=f"OpenVoice-Stimmklon ist fehlgeschlagen: {error}",
            )
        finally:
            try:
                source_path.unlink(missing_ok=True)
            except OSError:
                pass

        if not target.is_file() or target.stat().st_size <= 44:
            return SpeechResult(
                engine=self.name,
                error="OpenVoice hat keine hoerbare Datei erzeugt.",
            )
        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={
                "reference": str(self.reference_path),
                "base_voice": str(
                    self.option("base_voice", "de_DE-thorsten-high")
                ),
                "model": "OpenVoice V2",
                "local": True,
            },
        )

    def status(self) -> dict[str, Any]:
        base = super().status()
        base.update(
            {
                "loaded": self._converter is not None,
                "reference": str(self.reference_path),
                "source_reference": str(self.source_reference_path),
                "models_directory": str(self.models_directory),
                "model_variant": "OpenVoice V2",
                "model_cached": self._model_files_exist(),
                "base_voice": str(
                    self.option("base_voice", "de_DE-thorsten-high")
                ),
                "local": True,
                "note": "Schneller CPU-Klangfarbenklon der ElevenLabs-Referenz.",
            }
        )
        return base
