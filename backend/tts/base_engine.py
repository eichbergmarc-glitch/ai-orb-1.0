"""Gemeinsame Grundlage aller Sprachausgabe-Verfahren.

Ein Verfahren wandelt Text in eine WAV-Datei um. Mehr verlangt AI-Orb nicht
von ihm – die Wiedergabe, das Stummschalten des Mikrofons und die
Zustandswechsel des Orb regelt die Ebene darüber.

Diese Trennung erlaubt es, ein Verfahren auszutauschen, ohne irgendetwas
anderes anzufassen, und macht die Verfahren einzeln testbar: Eine WAV-Datei
lässt sich prüfen, ein Lautsprecher nicht.
"""

from __future__ import annotations

import abc
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SpeechRequest:
    """Ein Auftrag an die Sprachausgabe."""

    text: str
    #: Stimmlage; die Bedeutung hängt vom Verfahren ab.
    voice: str = ""
    #: Sprechgeschwindigkeit, 1.0 ist normal.
    speed: float = 1.0
    #: Tonhöhe in Halbtönen, 0 ist normal. Nicht jedes Verfahren kann das.
    pitch: float = 0.0
    #: Lautstärke von 0.0 bis 1.0.
    volume: float = 1.0
    #: Gefühlslage, aus der Geschwindigkeit und Tonhöhe abgeleitet wurden.
    emotion: str = "neutral"

    def cache_key(self) -> str:
        """Eine Kennung, unter der das Ergebnis wiederverwendet werden kann."""

        raw = f"{self.text}|{self.voice}|{self.speed:.3f}|{self.pitch:.2f}|{self.volume:.2f}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass
class SpeechResult:
    """Das Ergebnis einer Sprachausgabe."""

    #: Pfad zur erzeugten WAV-Datei; leer, wenn es nicht geklappt hat.
    audio_path: Path | None = None
    #: Welches Verfahren gearbeitet hat.
    engine: str = ""
    #: Dauer der Aufnahme in Sekunden, soweit bekannt.
    duration_seconds: float = 0.0
    #: Wie lange die Erzeugung gedauert hat.
    processing_seconds: float = 0.0
    #: Ob das Ergebnis aus dem Zwischenspeicher kam.
    from_cache: bool = False
    #: Klartextbegründung, falls es nicht geklappt hat.
    error: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        """Ob eine abspielbare Datei entstanden ist."""

        return self.audio_path is not None and self.audio_path.exists()


class TtsEngine(abc.ABC):
    """Grundgerüst eines Sprachausgabe-Verfahrens."""

    #: Kurzname, wie er in ``config.yaml`` steht.
    name: str = "unbenannt"

    def __init__(self, *, output_directory: Path, options: dict[str, Any] | None = None) -> None:
        """
        Args:
            output_directory: Wohin die WAV-Dateien geschrieben werden.
            options: Der zugehörige Abschnitt aus ``config.yaml``.
        """

        self._output_directory = output_directory
        self._output_directory.mkdir(parents=True, exist_ok=True)
        self._options: dict[str, Any] = options or {}

    # --- Von den Verfahren zu erfüllen ------------------------------------------

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Ob dieses Verfahren auf diesem Rechner benutzbar ist."""

    @abc.abstractmethod
    def installation_hint(self) -> str:
        """Was zu tun ist, falls es nicht benutzbar ist."""

    @abc.abstractmethod
    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        """Erzeugt die Sprachausgabe.

        Läuft blockierend und wird von der Ebene darüber in einem
        Worker-Thread aufgerufen.

        Args:
            request: Der Auftrag.
            target: Wohin die WAV-Datei geschrieben werden soll.
        """

    # --- Gemeinsame Hilfen -------------------------------------------------------

    def target_path(self, request: SpeechRequest) -> Path:
        """Der Dateipfad, unter dem das Ergebnis abgelegt wird."""

        return self._output_directory / f"{self.name}-{request.cache_key()}.wav"

    def option(self, key: str, default: Any = None) -> Any:
        """Liest eine Einstellung dieses Verfahrens."""

        return self._options.get(key, default)

    @staticmethod
    def wav_duration(path: Path) -> float:
        """Liest die Dauer einer WAV-Datei in Sekunden."""

        import wave

        try:
            with wave.open(str(path), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate() or 1
                return frames / float(rate)
        except Exception:  # noqa: BLE001 - eine unlesbare Datei ist kein Absturzgrund.
            return 0.0

    def voices(self) -> list[dict[str, str]]:
        """Die verfügbaren Stimmen. Standard: keine Auskunft."""

        return []

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "name": self.name,
            "available": self.is_available(),
            "voice": self.option("voice", ""),
        }

    @staticmethod
    def _now() -> float:
        return time.perf_counter()
