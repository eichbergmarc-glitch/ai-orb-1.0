"""Sprachausgabe über Piper.

Piper ist ein neuronales Sprachmodell, das lokal auf der CPU läuft und für
Deutsch mehrere sehr gute Stimmen mitbringt. Es ist deshalb die
Voreinstellung für deutschen Text: natürlicher als die Windows-Sprachausgabe
und im Gegensatz zu Kokoro tatsächlich auf Deutsch trainiert.

Ein Piper-Modell besteht aus zwei Dateien, die zusammengehören: der
eigentlichen ``.onnx``-Datei und einer ``.onnx.json`` daneben. Beide werden
beim ersten Gebrauch nach ``models/piper/`` heruntergeladen. Fehlt die
Netzverbindung, meldet das Modul das im Klartext und AI-Orb weicht auf die
Windows-Sprachausgabe aus, statt zu verstummen.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.utils.paths import get_models_dir

logger = get_logger(__name__)

#: Ablageort der Modelle bei Hugging Face.
MODEL_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

#: Die gebräuchlichen deutschen Stimmen mit ihrem Pfad im Ablageort.
GERMAN_VOICES: dict[str, str] = {
    "de_DE-thorsten-medium": "de/de_DE/thorsten/medium/de_DE-thorsten-medium",
    "de_DE-thorsten-high": "de/de_DE/thorsten/high/de_DE-thorsten-high",
    "de_DE-thorsten-low": "de/de_DE/thorsten/low/de_DE-thorsten-low",
    "de_DE-eva_k-x_low": "de/de_DE/eva_k/x_low/de_DE-eva_k-x_low",
    "de_DE-kerstin-low": "de/de_DE/kerstin/low/de_DE-kerstin-low",
    "de_DE-ramona-low": "de/de_DE/ramona/low/de_DE-ramona-low",
    "de_DE-karlsson-low": "de/de_DE/karlsson/low/de_DE-karlsson-low",
}


class PiperEngine(TtsEngine):
    """Neuronale Sprachausgabe über das Paket ``piper-tts``."""

    name = "piper"

    def __init__(self, *, output_directory: Path, options: dict[str, Any] | None = None) -> None:
        super().__init__(output_directory=output_directory, options=options)
        self._voice: Any | None = None
        self._loaded_name = ""
        self._load_failed = False

    # --- Verfügbarkeit -----------------------------------------------------------

    def is_available(self) -> bool:
        try:
            import piper  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    def installation_hint(self) -> str:
        return (
            "Für Piper fehlt das Paket 'piper-tts'. Installiere es mit:\n"
            "    .venv\\Scripts\\python.exe -m pip install -r requirements-voice.txt\n"
            "Das deutsche Sprachmodell (etwa 60 MB) lädt AI-Orb beim ersten "
            "Sprechen selbst herunter."
        )

    # --- Modelldateien -------------------------------------------------------------

    @property
    def models_directory(self) -> Path:
        """Wohin die Sprachmodelle geladen werden.

        Der Zwischenspeicher, nicht der Programmordner: In ``C:\\Program
        Files`` darf nicht geschrieben werden, und ein Modell von sechzig
        Megabyte hat in einem wandernden Benutzerprofil nichts verloren.
        """

        directory = get_models_dir() / "piper"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _voice_name(self) -> str:
        return str(self.option("voice", "de_DE-thorsten-medium"))

    def _download(self, voice_name: str) -> Path | None:
        """Lädt Modell und Beschreibung herunter, falls sie fehlen.

        Returns:
            Der Pfad zur ``.onnx``-Datei, oder ``None`` bei Misserfolg.
        """

        relative = GERMAN_VOICES.get(voice_name)
        if relative is None:
            logger.error(
                "Die Stimme '%s' ist nicht bekannt. Bekannt sind: %s",
                voice_name,
                ", ".join(sorted(GERMAN_VOICES)),
            )
            return None

        model_path = self.models_directory / f"{voice_name}.onnx"
        config_path = self.models_directory / f"{voice_name}.onnx.json"

        if model_path.exists() and config_path.exists():
            return model_path

        logger.info(
            "Das Sprachmodell '%s' wird heruntergeladen (etwa 60 MB, einmalig).",
            voice_name,
        )

        for url_suffix, destination in (
            (".onnx", model_path),
            (".onnx.json", config_path),
        ):
            if destination.exists():
                continue
            url = f"{MODEL_BASE_URL}/{relative}{url_suffix}?download=true"
            temporary = destination.with_suffix(destination.suffix + ".part")
            try:
                with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
                    temporary.write_bytes(response.read())
                temporary.replace(destination)
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                logger.error(
                    "Das Sprachmodell konnte nicht geladen werden (%s). "
                    "AI-Orb spricht so lange über die Windows-Sprachausgabe.",
                    error,
                )
                try:
                    temporary.unlink()
                except OSError:
                    pass
                return None

        logger.info("Das Sprachmodell '%s' ist bereit.", voice_name)
        return model_path

    def _load(self) -> Any | None:
        """Lädt das Piper-Modell (blockierend)."""

        voice_name = self._voice_name()

        if self._voice is not None and self._loaded_name == voice_name:
            return self._voice
        if self._load_failed:
            return None

        try:
            from piper import PiperVoice
        except (ImportError, OSError):
            logger.error(self.installation_hint())
            self._load_failed = True
            return None

        model_path = self._download(voice_name)
        if model_path is None:
            self._load_failed = True
            return None

        try:
            self._voice = PiperVoice.load(str(model_path))
            self._loaded_name = voice_name
        except Exception:  # noqa: BLE001
            logger.exception("Das Piper-Modell konnte nicht geladen werden.")
            self._load_failed = True
            return None

        return self._voice

    # --- Erzeugung ---------------------------------------------------------------

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        started = self._now()

        voice = self._load()
        if voice is None:
            return SpeechResult(engine=self.name, error=self.installation_hint())

        # Piper steuert die Geschwindigkeit über die Lautlänge: Ein größerer
        # Wert bedeutet längere Laute, also langsamere Sprache. Das ist
        # gerade der Kehrwert dessen, was der Auftrag angibt.
        length_scale = 1.0 / max(0.5, min(2.0, request.speed))

        try:
            with wave.open(str(target), "wb") as handle:
                self._write_audio(voice, request, handle, length_scale)
        except Exception as error:  # noqa: BLE001
            logger.exception("Piper konnte den Text nicht sprechen.")
            return SpeechResult(engine=self.name, error=f"Piper ist fehlgeschlagen: {error}")

        if not target.exists() or target.stat().st_size <= 44:
            return SpeechResult(engine=self.name, error="Piper hat keine hörbare Datei erzeugt.")

        return SpeechResult(
            audio_path=target,
            engine=self.name,
            duration_seconds=self.wav_duration(target),
            processing_seconds=self._now() - started,
            context={"voice": self._loaded_name},
        )

    def _write_audio(self, voice: Any, request: SpeechRequest, handle: Any, length_scale: float) -> None:
        """Schreibt die Sprachausgabe in eine geöffnete WAV-Datei.

        Piper hat seine Schnittstelle zwischen den Fassungen geändert.
        Deshalb wird zuerst der neuere Weg versucht und bei Bedarf der
        ältere – so läuft AI-Orb mit beiden, ohne eine Version festzunageln.

        Zwei Regler entscheiden über den natürlichen Klang, und beide waren
        vorher ungenutzt:

        * ``noise_w`` steuert, wie sehr die Länge der Laute schwankt. Höhere
          Werte geben der Sprache Rhythmus statt Gleichtakt – der
          Unterschied zwischen „vorgelesen“ und „gesprochen“.
        * ``noise_scale`` steuert die Schwankung im Klang selbst. Etwas mehr
          davon nimmt der Stimme das Blecherne, zu viel macht sie unruhig.

        Die Werte kommen aus der Konfiguration, mit Vorgaben, die wärmer und
        lebendiger klingen als Pipers nüchterne Standardwerte.
        """

        # Die Vorgaben entsprechen den Werten, mit denen thorsten-high
        # trainiert wurde. Höhere Werte klangen lebendiger, machten die
        # Aussprache aber hastig und stellenweise unverständlich.
        noise_scale = float(self.option("noise_scale", 0.667))
        noise_w = float(self.option("noise_w", 0.8))

        try:
            from piper import SynthesisConfig

            configuration = SynthesisConfig(
                length_scale=length_scale,
                noise_scale=noise_scale,
                noise_w=noise_w,
                volume=max(0.0, min(1.0, request.volume)),
            )
            voice.synthesize_wav(request.text, handle, syn_config=configuration)
            return
        except (ImportError, TypeError, AttributeError):
            pass

        try:
            voice.synthesize_wav(request.text, handle)
            return
        except (TypeError, AttributeError):
            pass

        # Älteste bekannte Schnittstelle.
        voice.synthesize(request.text, handle, length_scale=length_scale)

    # --- Auskunft ------------------------------------------------------------------

    def voices(self) -> list[dict[str, str]]:
        """Die bekannten deutschen Piper-Stimmen."""

        installed = {path.stem for path in self.models_directory.glob("*.onnx")}
        return [
            {
                "name": name,
                "language": "de-DE",
                "installed": "ja" if name in installed else "nein",
            }
            for name in sorted(GERMAN_VOICES)
        ]

    def status(self) -> dict[str, Any]:
        base = super().status()
        base["loaded"] = self._voice is not None
        base["voice"] = self._voice_name()
        base["models_directory"] = str(self.models_directory)
        base["note"] = "Auf Deutsch trainiert, läuft lokal auf der CPU."
        return base

    def describe_installed(self) -> str:
        """Kurzauskunft, welche Modelle bereits lokal liegen."""

        files = sorted(path.stem for path in self.models_directory.glob("*.onnx"))
        if not files:
            return "Es ist noch kein Sprachmodell heruntergeladen."
        return "Vorhandene Sprachmodelle: " + ", ".join(files)


def voice_catalog() -> str:
    """Die bekannten Stimmen als lesbarer Text (für die Dokumentation)."""

    return json.dumps(sorted(GERMAN_VOICES), ensure_ascii=False, indent=2)
