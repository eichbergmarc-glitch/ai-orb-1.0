"""Schnelle, hochwertige deutsche Offline-Stimme mit Pocket TTS.

Pocket TTS ist fuer Sprachassistenten auf CPUs gebaut. Anders als die zuvor
verwendete Kette aus Piper und OpenVoice erzeugt es Aussprache, Rhythmus und
Klang in einem einzigen neuronalen Modell. Das groessere deutsche
24-Layer-Modell bleibt auf diesem Rechner ungefaehr echtzeitschnell.

Im Betrieb werden ausschliesslich bereits lokal gespeicherte Modelldateien
verwendet. Damit wartet der Orb ohne Internet nicht auf Hugging-Face-Aufrufe
und sendet keinen zu sprechenden Text nach aussen.
"""

from __future__ import annotations

import hashlib
import queue
import threading
import time
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.utils.paths import get_models_dir

logger = get_logger(__name__)


class PcmAudioStream:
    """Threadsicherer Strom aus PCM16-Bloecken fuer den Orb-Player."""

    def __init__(self, *, sample_rate: int) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = 1
        self.sample_width = 2
        self.duration_seconds = 0.0
        self.error = ""
        self._chunks: queue.Queue[bytes | None] = queue.Queue()
        self._buffer_condition = threading.Condition()
        self._buffered_frames = 0
        self._first_ready = threading.Event()
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._has_audio = False

    @property
    def has_audio(self) -> bool:
        return self._has_audio

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def push(self, pcm: bytes) -> bool:
        if self.cancelled:
            return False
        if pcm:
            self._has_audio = True
            self._chunks.put(pcm)
            with self._buffer_condition:
                self._buffered_frames += len(pcm) // (
                    self.sample_width * self.channels
                )
                self._buffer_condition.notify_all()
            self._first_ready.set()
        return not self.cancelled

    def finish(self, *, duration_seconds: float = 0.0, error: str = "") -> None:
        self.duration_seconds = max(0.0, float(duration_seconds))
        self.error = str(error)
        self._chunks.put(None)
        self._done.set()
        self._first_ready.set()
        with self._buffer_condition:
            self._buffer_condition.notify_all()

    def cancel(self) -> None:
        self._cancelled.set()

    def wait_for_first(self, timeout: float) -> bool:
        return self._first_ready.wait(timeout=max(0.1, float(timeout)))

    def wait_until_done(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout=timeout)

    def wait_for_buffer(self, seconds: float, timeout: float) -> bool:
        """Wartet auf einen kleinen Wiedergabevorsprung gegen CPU-Schwankungen."""

        target_frames = max(0, int(float(seconds) * self.sample_rate))
        deadline = time.monotonic() + max(0.1, float(timeout))
        with self._buffer_condition:
            while self._buffered_frames < target_frames and not self.done:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._buffer_condition.wait(timeout=remaining)
        return self._buffered_frames > 0

    def iter_chunks(self):
        while True:
            chunk = self._chunks.get()
            if chunk is None:
                break
            yield chunk
        if self.error:
            raise RuntimeError(self.error)


class PocketTtsEngine(TtsEngine):
    """Lokale deutsche Pocket-TTS-Stimme fuer kurze Antwortlatenz."""

    name = "pocket_tts"

    def __init__(
        self, *, output_directory: Path, options: dict[str, Any] | None = None
    ) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._model: Any | None = None
        self._voice_state: Any | None = None
        self._load_error = ""
        self._load_lock = threading.Lock()
        # Das Modell verwaltet waehrend der Erzeugung KV-Caches und einen
        # Decoder-Thread. Zwei gleichzeitige Aufrufe auf derselben Instanz
        # sind laut Pocket-TTS-API nicht threadsicher.
        self._synthesis_lock = threading.Lock()
        self._model_variant = (
            str(self.option("model_variant", "german")).strip()
            or "german"
        )
        self._voice_name = str(self.option("voice", "juergen")).strip() or "juergen"

    @property
    def models_directory(self) -> Path:
        directory = get_models_dir() / "pocket-tts"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def hub_directory(self) -> Path:
        return self.models_directory / "huggingface" / "hub"

    def _cached_file(self, *, kind: str) -> Path | None:
        """Findet Modell, Tokenizer oder vorbereiteten Stimmenzustand lokal."""

        if kind == "model":
            filename = "model.safetensors"
            marker = f"languages/{self._model_variant}/model.safetensors"
        elif kind == "tokenizer":
            filename = "tokenizer.model"
            marker = f"languages/{self._model_variant}/tokenizer.model"
        elif kind == "voice":
            filename = f"{self._voice_name}.safetensors"
            marker = (
                f"languages/{self._model_variant}/embeddings/"
                f"{self._voice_name}.safetensors"
            )
        else:
            return None

        if not self.hub_directory.exists():
            return None
        for candidate in self.hub_directory.rglob(filename):
            normalisiert = candidate.as_posix()
            if marker in normalisiert and candidate.stat().st_size > 0:
                return candidate
        return None

    def _model_files(self) -> tuple[Path | None, Path | None, Path | None]:
        return (
            self._cached_file(kind="model"),
            self._cached_file(kind="tokenizer"),
            self._cached_file(kind="voice"),
        )

    def is_available(self) -> bool:
        try:
            from pocket_tts import TTSModel  # noqa: F401
        except (ImportError, OSError):
            return False
        return all(path is not None for path in self._model_files())

    def installation_hint(self) -> str:
        return (
            "Fuer die schnelle lokale Stimme fehlen Pocket TTS oder die einmalig "
            f"geladenen deutschen Modelldateien ({self._model_variant}, "
            f"Stimme {self._voice_name}). Installiere 'pocket-tts==3.0.2' und "
            "lade das deutsche Modell einmal bei bestehender Internetverbindung."
        )

    def _local_config(self, model: Path, tokenizer: Path) -> Path:
        """Erzeugt eine rein lokale Modellkonfiguration.

        Pocket TTS verweist in seiner mitgelieferten YAML-Datei auf
        Hugging-Face-URLs. Selbst wenn alles im Cache liegt, kann das bei
        fehlendem Netz einen Metadatenaufruf ausloesen. Die lokale Kopie zeigt
        direkt auf die vorhandenen Dateien und macht Offline auch zeitlich
        eindeutig: kein Timeout, keine DNS-Pruefung, kein Download.
        """

        import yaml
        from pocket_tts.utils.config import CONFIGS_DIR

        source = CONFIGS_DIR / f"{self._model_variant}.yaml"
        if not source.exists():
            raise FileNotFoundError(
                f"Pocket TTS kennt das Modell {self._model_variant!r} nicht."
            )
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        payload["weights_path"] = str(model.resolve())
        payload["weights_path_without_voice_cloning"] = str(model.resolve())
        payload["flow_lm"]["lookup_table"]["tokenizer_path"] = str(
            tokenizer.resolve()
        )
        rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        destination = self.models_directory / f"local-{self._model_variant}.yaml"
        if not destination.exists() or destination.read_text(encoding="utf-8") != rendered:
            destination.write_text(rendered, encoding="utf-8")
        return destination

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
                from pocket_tts import TTSModel

                model_path, tokenizer_path, voice_path = self._model_files()
                if model_path is None or tokenizer_path is None or voice_path is None:
                    raise FileNotFoundError(self.installation_hint())

                configuration = self._local_config(model_path, tokenizer_path)
                self._model = TTSModel.load_model(
                    config=configuration,
                    temp=float(self.option("temperature", 0.7)),
                    sampler_decode_steps=max(
                        1, int(self.option("sampler_decode_steps", 1))
                    ),
                    noise_clamp=self.option("noise_clamp", None),
                    eos_threshold=float(self.option("eos_threshold", -4.0)),
                    quantize=bool(self.option("quantize", True)),
                )
                # Die frei ladbaren Gewichte enthalten die vorbereiteten
                # Katalogstimmen, aber keinen Encoder fuer beliebige neue
                # Referenzen. Der lokale Safetensors-Zustand ist genau fuer
                # diese Gewichte vorbereitet und in Millisekunden geladen.
                self._model.has_voice_cloning = False
                self._voice_state = self._model.get_state_for_audio_prompt(voice_path)
                logger.info(
                    "Pocket-TTS-Stimme geladen (Modell=%s, Stimme=%s, CPU, lokal).",
                    self._model_variant,
                    self._voice_name,
                )
            except Exception as error:  # noqa: BLE001
                self._load_error = str(error)
                self._model = None
                self._voice_state = None
                logger.exception("Pocket TTS liess sich nicht lokal laden.")
                return None
        return self._model

    @staticmethod
    def _file_hash(path: Path | None) -> str:
        if path is None:
            return "missing"
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            return "missing"

    def target_path(self, request: SpeechRequest) -> Path:
        model, _, voice = self._model_files()
        settings = "|".join(
            (
                request.cache_key(),
                self._model_variant,
                self._voice_name,
                self._file_hash(model),
                self._file_hash(voice),
                str(self.option("temperature", 0.7)),
                str(self.option("sampler_decode_steps", 1)),
                str(self.option("noise_clamp", None)),
                str(self.option("eos_threshold", -4.0)),
                str(self.option("quantize", True)),
                str(self.option("max_tokens", 50)),
            )
        )
        digest = hashlib.sha256(settings.encode("utf-8")).hexdigest()[:24]
        return self._output_directory / f"{self.name}-{digest}.wav"

    def synthesize_blocking(
        self, request: SpeechRequest, target: Path
    ) -> SpeechResult:
        started = self._now()
        model = self._load()
        if model is None or self._voice_state is None:
            return SpeechResult(
                engine=self.name,
                error=self._load_error or self.installation_hint(),
                context={"fatal_for_session": True, "local": True},
            )

        if bool(self.option("streaming", True)):
            return self._start_streaming(request, target, model, started)

        temporary = target.with_suffix(".tmp.wav")
        try:
            with self._synthesis_lock:
                audio = model.generate_audio(
                    self._voice_state,
                    request.text,
                    max_tokens=max(16, int(self.option("max_tokens", 50))),
                )
            samples = (
                audio.detach().cpu().float().clamp(-1.0, 1.0).numpy().reshape(-1)
                * 32767.0
            ).astype("<i2")
            with wave.open(str(temporary), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(int(model.sample_rate))
                handle.writeframes(samples.tobytes())
            temporary.replace(target)
        except Exception as error:  # noqa: BLE001
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            logger.exception("Pocket TTS konnte den Text nicht sprechen.")
            return SpeechResult(
                engine=self.name,
                error=f"Pocket TTS ist fehlgeschlagen: {error}",
                context={"local": True},
            )

        if not target.exists() or target.stat().st_size <= 44:
            return SpeechResult(
                engine=self.name,
                error="Pocket TTS hat keine hoerbare Datei erzeugt.",
                context={"local": True},
            )

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={
                "model_variant": self._model_variant,
                "voice": self._voice_name,
                "sample_rate": int(model.sample_rate),
                "quantized": bool(self.option("quantize", True)),
                "local": True,
            },
        )

    @staticmethod
    def _pcm_bytes(audio: Any) -> bytes:
        samples = (
            audio.detach().cpu().float().clamp(-1.0, 1.0).numpy().reshape(-1)
            * 32767.0
        ).astype("<i2")
        return samples.tobytes()

    @staticmethod
    def _write_pcm_file(
        target: Path, pcm_chunks: list[bytes], *, sample_rate: int
    ) -> None:
        temporary = target.with_suffix(".tmp.wav")
        with wave.open(str(temporary), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(int(sample_rate))
            for pcm in pcm_chunks:
                handle.writeframes(pcm)
        temporary.replace(target)

    def _start_streaming(
        self, request: SpeechRequest, target: Path, model: Any, started: float
    ) -> SpeechResult:
        """Gibt nach dem ersten Block zurueck und schreibt die WAV parallel."""

        stream = PcmAudioStream(sample_rate=int(model.sample_rate))
        worker = threading.Thread(
            target=self._produce_stream,
            args=(request, target, model, stream),
            name="ai-orb-pocket-tts",
            daemon=True,
        )
        worker.start()

        timeout = max(2.0, float(self.option("first_chunk_timeout", 15.0)))
        if not stream.wait_for_first(timeout):
            stream.cancel()
            return SpeechResult(
                engine=self.name,
                error=(
                    "Pocket TTS hat nicht rechtzeitig mit der Sprachausgabe "
                    "begonnen."
                ),
                context={"local": True},
            )
        if stream.error and not stream.has_audio:
            return SpeechResult(
                engine=self.name,
                error=f"Pocket TTS ist fehlgeschlagen: {stream.error}",
                context={"local": True},
            )

        # Der volle Orb laeuft neben Whisper, Mikrofon und Oberflaeche. Ein
        # kleiner Vorsprung faengt kurze CPU-Spitzen ab, ohne die gefuehlte
        # Startzeit in den Sekundenbereich zu schieben.
        prebuffer_seconds = max(
            0.0, min(1.5, float(self.option("prebuffer_ms", 600)) / 1000.0)
        )
        stream.wait_for_buffer(prebuffer_seconds, timeout)

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            processing_seconds=self._now() - started,
            context={
                "model_variant": self._model_variant,
                "voice": self._voice_name,
                "sample_rate": int(model.sample_rate),
                "quantized": bool(self.option("quantize", True)),
                "local": True,
                "streaming": True,
                "prebuffer_seconds": prebuffer_seconds,
                "pcm_stream": stream,
            },
        )

    def _produce_stream(
        self,
        request: SpeechRequest,
        target: Path,
        model: Any,
        stream: PcmAudioStream,
    ) -> None:
        chunks: list[bytes] = []
        generated_started = time.perf_counter()
        first_chunk_seconds = 0.0
        try:
            with self._synthesis_lock:
                for audio in model.generate_audio_stream(
                    self._voice_state,
                    request.text,
                    max_tokens=max(16, int(self.option("max_tokens", 50))),
                ):
                    if stream.cancelled:
                        break
                    pcm = self._pcm_bytes(audio)
                    if not pcm:
                        continue
                    if not chunks:
                        first_chunk_seconds = time.perf_counter() - generated_started
                    chunks.append(pcm)
                    if not stream.push(pcm):
                        break

            if stream.cancelled:
                target.unlink(missing_ok=True)
                stream.finish()
                return
            if not chunks:
                raise RuntimeError("Das Modell hat keinen Audioblock erzeugt.")

            self._write_pcm_file(target, chunks, sample_rate=int(model.sample_rate))
            frames = sum(len(chunk) for chunk in chunks) // 2
            duration = frames / float(model.sample_rate)
            elapsed = time.perf_counter() - generated_started
            stream.finish(duration_seconds=duration)
            logger.info(
                "Pocket-TTS-Stream: erster Block %.3f s, Erzeugung %.3f s, "
                "Audio %.3f s, RTF %.3f.",
                first_chunk_seconds,
                elapsed,
                duration,
                elapsed / max(duration, 0.001),
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("Pocket-TTS-Streaming ist fehlgeschlagen.")
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            stream.finish(error=str(error))

    def voices(self) -> list[dict[str, str]]:
        return [
            {
                "name": self._voice_name,
                "language": "de-DE",
                "installed": "ja" if self._cached_file(kind="voice") else "nein",
            }
        ]

    def status(self) -> dict[str, Any]:
        base = super().status()
        model, tokenizer, voice = self._model_files()
        base.update(
            {
                "loaded": self._model is not None,
                "voice": self._voice_name,
                "model_variant": self._model_variant,
                "model_cached": bool(model and tokenizer and voice),
                "models_directory": str(self.models_directory),
                "quantized": bool(self.option("quantize", True)),
                "local": True,
                "quality": (
                    "hochwertiges deutsches 24-Layer-Neuralmodell"
                    if self._model_variant == "german_24l"
                    else "natuerliche deutsche Echtzeit-Neuralstimme"
                ),
            }
        )
        return base
