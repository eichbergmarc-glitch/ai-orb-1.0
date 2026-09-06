"""Lokale deutsche Stimmklon-Ausgabe mit Chatterbox Multilingual.

Das Modell und die Referenz liegen ausschliesslich lokal. Nach dem einmaligen
Modelldownload wird weder ein API-Schluessel noch eine Netzverbindung benoetigt.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.utils.paths import get_models_dir, get_project_root

logger = get_logger(__name__)


class ChatterboxEngine(TtsEngine):
    """Zero-Shot-Stimmklon fuer Deutsch, lokal auf CPU oder CUDA."""

    name = "chatterbox"

    _EMOTION_EXAGGERATION: dict[str, float] = {
        "neutral": 1.00,
        "freundlich": 1.06,
        "aufmerksam": 1.04,
        "nachdenklich": 0.88,
        "erfreut": 1.22,
        "bedauernd": 0.86,
        "dringlich": 1.16,
        "leise": 0.82,
    }

    def __init__(
        self, *, output_directory: Path, options: dict[str, Any] | None = None
    ) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._model: Any | None = None
        self._load_error = ""
        self._load_lock = threading.Lock()
        # Das Modell ist nicht threadsicher: Gefuehlsparameter und die
        # vorbereitete Sprecherkonditionierung liegen direkt am Modell.
        # Gleichzeitig gestartete Saetze konnten sich deshalb gegenseitig
        # beeinflussen oder den Prozess scheinbar festfahren lassen.
        self._synthesis_lock = threading.Lock()
        self._model_variant = str(self.option("model_variant", "v3")).strip() or "v3"
        cache = self.models_directory / "huggingface"
        cache.mkdir(parents=True, exist_ok=True)
        # Muss VOR dem ersten Import von huggingface_hub gesetzt sein. Auf
        # Windows sind symbolische Links ohne Entwicklermodus nicht erlaubt;
        # der Hub kopiert die Dateien dann normal in den lokalen Cache.
        os.environ.setdefault("HF_HOME", str(cache))
        os.environ.setdefault("HF_HUB_CACHE", str(cache / "hub"))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("PKUSEG_HOME", str(self.models_directory / "pkuseg"))
        self._required_model_files = {
            "ve.pt",
            f"t3_mtl23ls_{self._model_variant}.safetensors",
            "s3gen.pt",
            "grapheme_mtl_merged_expanded_v1.json",
            "conds.pt",
            "Cangjie5_TC.json",
        }

    def _cached_snapshot(self) -> Path | None:
        """Findet einen vollstaendigen lokalen Modell-Snapshot.

        Nach dem ersten Download wird bewusst ``from_local`` verwendet.
        Damit ist der Offlinebetrieb wirklich offline und wartet nicht erst
        auf fehlgeschlagene Hugging-Face-HEAD-Anfragen.
        """

        cache = self.models_directory / "huggingface" / "hub"
        model_name = f"t3_mtl23ls_{self._model_variant}.safetensors"
        for candidate in cache.rglob(model_name):
            directory = candidate.parent
            if all((directory / name).exists() for name in self._required_model_files):
                return directory
        return None

    @property
    def models_directory(self) -> Path:
        directory = get_models_dir() / "chatterbox"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def reference_path(self) -> Path:
        raw = str(self.option("reference_audio", "data/voice/orb-reference.wav"))
        path = Path(raw)
        return path if path.is_absolute() else get_project_root() / path

    def is_available(self) -> bool:
        if not self.reference_path.exists():
            return False
        try:
            import torch  # noqa: F401
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    def installation_hint(self) -> str:
        return (
            "Fuer die lokale Orb-Stimme fehlen Chatterbox oder die autorisierte "
            f"Referenzaufnahme ({self.reference_path}). Installiere "
            "'chatterbox-tts' und hinterlege die WAV-Datei."
        )

    def _load(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._load_error:
            return None

        # Satz-Streaming kann den naechsten Abschnitt schon vorbereiten,
        # waehrend der erste entsteht. Ohne Sperre laden zwei Worker dann
        # dasselbe 500-Millionen-Parameter-Modell doppelt in den Speicher.
        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_error:
                return None
            return self._load_locked()

    def _load_locked(self) -> Any | None:
        """Laedt Modell und Referenz genau einmal; Aufrufer haelt die Sperre."""

        # Hugging Face darf nicht in einen Benutzer-Cache ausserhalb des Orb
        # schreiben. Derselbe lokale Ordner macht den Betrieb nach dem ersten
        # Download reproduzierbar und vollstaendig offlinefaehig.
        try:
            import perth
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            # Resemble Perth liefert fuer Windows derzeit keine native
            # Watermarker-Implementierung und setzt die Klasse dort auf None.
            # Ohne diesen offiziellen Dummy startet Chatterbox ueberhaupt
            # nicht. Das betrifft nur die unsichtbare Herkunftsmarkierung,
            # nicht Stimme, Referenz oder Offlineverarbeitung.
            if perth.PerthImplicitWatermarker is None:
                perth.PerthImplicitWatermarker = perth.DummyWatermarker
                logger.warning(
                    "Perth-Wasserzeichen ist unter Windows nicht verfuegbar; "
                    "Chatterbox nutzt den kompatiblen Dummy-Watermarker."
                )

            configured = str(self.option("device", "auto")).lower()
            device = (
                "cuda"
                if configured == "auto" and torch.cuda.is_available()
                else "cpu"
                if configured == "auto"
                else configured
            )
            # chatterbox-tts vergleicht das Geraet intern mit den
            # Zeichenketten "cpu"/"mps", um CUDA-gespeicherte Gewichte beim
            # Laden korrekt auf die CPU umzubiegen. Ein torch.device waere
            # zwar dokumentiert, umgeht in dieser Fassung aber genau diese
            # Schutzabfrage.
            snapshot = self._cached_snapshot()
            if snapshot is not None:
                self._model = ChatterboxMultilingualTTS.from_local(
                    snapshot,
                    device=device,
                    t3_model=self._model_variant,
                )
                quelle = "lokaler Snapshot"
            else:
                self._model = ChatterboxMultilingualTTS.from_pretrained(
                    device=device,
                    t3_model=self._model_variant,
                )
                quelle = "erster Modelldownload"
            # Die Stimmkonditionierung ist fuer jeden Satz identisch. Sie bei
            # jeder Synthese erneut aus denselben 11,8 Sekunden Referenz zu
            # berechnen kostet Zeit und kann minimale Klangabweichungen
            # zwischen Saetzen erzeugen. Einmal vorbereiten, danach nur noch
            # Text erzeugen.
            self._model.prepare_conditionals(
                str(self.reference_path),
                exaggeration=float(self.option("exaggeration", 0.5)),
            )
            logger.info(
                "Lokale Chatterbox-Stimme geladen (Modell=%s, Geraet=%s, %s).",
                self._model_variant,
                device,
                quelle,
            )
        except Exception as error:  # noqa: BLE001
            self._load_error = str(error)
            logger.exception("Die lokale Chatterbox-Stimme liess sich nicht laden.")
            return None
        return self._model

    def target_path(self, request: SpeechRequest) -> Path:
        """Cachepfad inklusive Klonmodell, Referenz und Prosodie.

        Der gemeinsame TTS-Cache beruecksichtigt normalerweise nur Text und
        Tempo. Fuer einen Stimmklon reicht das nicht: Nach dem Wechsel von V2
        zu V3 wurde sonst weiterhin die alte V2-Datei abgespielt und jede
        Qualitaetsverbesserung blieb unsichtbar.
        """

        try:
            reference_hash = hashlib.sha256(self.reference_path.read_bytes()).hexdigest()[:16]
        except OSError:
            reference_hash = "missing"
        settings = "|".join(
            (
                request.cache_key(),
                self._model_variant,
                reference_hash,
                str(self.option("language", "de")),
                str(self.option("exaggeration", 0.5)),
                str(self.option("cfg_weight", 0.5)),
                str(self.option("temperature", 0.8)),
                str(self.option("repetition_penalty", 1.2)),
                str(self.option("min_p", 0.05)),
                str(self.option("top_p", 1.0)),
                str(self.option("max_new_tokens", 280)),
                str(self.option("tokens_per_character", 2.4)),
                str(self.option("token_margin", 32)),
            )
        )
        digest = hashlib.sha256(settings.encode("utf-8")).hexdigest()[:24]
        return self._output_directory / f"{self.name}-{digest}.wav"

    def _token_limit(self, text: str) -> int:
        """Begrenzt Ausreisser, bei denen Chatterbox sein Satzende verfehlt.

        Die Bibliothek setzt intern pauschal 1.000 Tokens. Auf diesem
        CPU-Rechner sind das mehrere Minuten Rechenzeit. Fuer normale
        deutsche Saetze reichen rund 2,4 Sprachtokens je Zeichen plus ein
        kleiner Rand. Die konfigurierte Obergrenze verhindert endlose
        Wiederholungen, ohne regulaere kurze Ausgaben abzuschneiden.
        """

        per_character = max(1.5, float(self.option("tokens_per_character", 2.4)))
        margin = max(16, int(self.option("token_margin", 32)))
        hard_limit = max(80, int(self.option("max_new_tokens", 280)))
        estimated = int(math.ceil(len(text.strip()) * per_character)) + margin
        return max(80, min(hard_limit, estimated))

    def _generate_bounded(self, model: Any, text: str, **kwargs: Any) -> Any:
        """Ruft das unveraenderte Modell mit einer sicheren Tokenobergrenze.

        Chatterbox exponiert ``max_new_tokens`` derzeit nicht in seiner
        oeffentlichen ``generate``-Signatur. Der kleine Adapter begrenzt nur
        diesen einen internen Aufruf und stellt ihn danach garantiert wieder
        her. Fake-Modelle in Tests und kuenftige Implementierungen ohne T3
        funktionieren weiterhin unveraendert.
        """

        t3 = getattr(model, "t3", None)
        inference = getattr(t3, "inference", None)
        if not callable(inference):
            return model.generate(text, **kwargs)

        limit = self._token_limit(text)

        def bounded_inference(*args: Any, **inner_kwargs: Any) -> Any:
            requested = int(inner_kwargs.get("max_new_tokens", limit))
            inner_kwargs["max_new_tokens"] = min(requested, limit)
            return inference(*args, **inner_kwargs)

        t3.inference = bounded_inference
        try:
            return model.generate(text, **kwargs)
        finally:
            t3.inference = inference

    def synthesize_blocking(
        self, request: SpeechRequest, target: Path
    ) -> SpeechResult:
        started = self._now()
        model = self._load()
        if model is None:
            return SpeechResult(
                engine=self.name,
                error=self._load_error or self.installation_hint(),
            )

        try:
            basis_ausdruck = float(self.option("exaggeration", 0.5))
            ausdruck = max(
                0.25,
                min(
                    0.80,
                    basis_ausdruck
                    * self._EMOTION_EXAGGERATION.get(request.emotion.lower(), 1.0),
                ),
            )
            with self._synthesis_lock:
                waveform = self._generate_bounded(
                    model,
                    request.text,
                    language_id=str(self.option("language", "de")),
                    audio_prompt_path=None,
                    exaggeration=ausdruck,
                    cfg_weight=float(self.option("cfg_weight", 0.5)),
                    temperature=float(self.option("temperature", 0.8)),
                    repetition_penalty=float(self.option("repetition_penalty", 1.2)),
                    min_p=float(self.option("min_p", 0.05)),
                    top_p=float(self.option("top_p", 1.0)),
                )
            if getattr(waveform, "ndim", 1) == 1:
                waveform = waveform.unsqueeze(0)
            # torchaudio schreibt je nach Backend WAVE_FORMAT_EXTENSIBLE und
            # benoetigt unter Windows weitere DLLs. Orb braucht fuer Piper,
            # winsound und seine Dauerpruefung bewusst simples PCM16-WAV.
            samples = (
                waveform.detach().cpu().float().clamp(-1.0, 1.0).numpy().reshape(-1)
                * 32767.0
            ).astype("<i2")
            with wave.open(str(target), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(int(model.sr))
                handle.writeframes(samples.tobytes())
        except Exception as error:  # noqa: BLE001
            logger.exception("Chatterbox konnte den Text nicht sprechen.")
            return SpeechResult(
                engine=self.name,
                error=f"Chatterbox ist fehlgeschlagen: {error}",
            )

        if not target.exists() or target.stat().st_size <= 44:
            return SpeechResult(
                engine=self.name, error="Chatterbox hat keine hoerbare Datei erzeugt."
            )
        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={
                "reference": str(self.reference_path),
                "language": str(self.option("language", "de")),
                "model_variant": self._model_variant,
                "exaggeration": ausdruck,
                "max_new_tokens": self._token_limit(request.text),
                "local": True,
            },
        )

    def status(self) -> dict[str, Any]:
        base = super().status()
        base.update(
            {
                "loaded": self._model is not None,
                "reference": str(self.reference_path),
                "models_directory": str(self.models_directory),
                "model_variant": self._model_variant,
                "model_cached": self._cached_snapshot() is not None,
                "max_new_tokens": int(self.option("max_new_tokens", 280)),
                "local": True,
            }
        )
        return base
