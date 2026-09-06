"""Sprachaktivitätserkennung (Voice Activity Detection).

Erkennt anhand der Lautstärke, wann gesprochen wird und wann eine Äußerung
zu Ende ist. Das ist die Voraussetzung dafür, dass nicht dauerhaft
transkribiert werden muss: Die Spracherkennung läuft nur auf Abschnitten,
in denen tatsächlich gesprochen wurde.

Bewusst ohne externe Bibliothek umgesetzt. Die Berechnung arbeitet auf
kurzen Blöcken (üblicherweise 30 Millisekunden) und ist damit auch in
reinem Python schnell genug – bei 16 kHz sind das 480 Werte pro Block.

Der Schwellwert passt sich der Umgebung selbst an: Der Grundpegel wird
laufend nachgeführt, sodass ein lauter Raum nicht zu Dauererkennung führt
und ein leiser Raum nicht zu Taubheit.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class VadState(Enum):
    """Der Zustand der Sprachaktivitätserkennung."""

    #: Es wird nicht gesprochen.
    SILENCE = "stille"
    #: Es wird gerade gesprochen.
    SPEECH = "sprache"


@dataclass
class VadEvent:
    """Ein Ereignis der Sprachaktivitätserkennung."""

    #: ``True``, wenn eine Äußerung begonnen hat.
    speech_started: bool = False
    #: ``True``, wenn eine Äußerung beendet wurde.
    speech_ended: bool = False
    #: Der aktuelle Lautstärkepegel (RMS, 0.0 bis 1.0).
    level: float = 0.0
    #: Der aktuell wirksame Grundpegel.
    noise_floor: float = 0.0


def rms(samples: Sequence[int]) -> float:
    """Berechnet den quadratischen Mittelwert eines Audioblocks.

    Args:
        samples: 16-Bit-Ganzzahlwerte des Audioblocks.

    Returns:
        Der Pegel zwischen 0.0 und 1.0.
    """

    if not samples:
        return 0.0

    total = 0
    for value in samples:
        total += value * value

    return math.sqrt(total / len(samples)) / 32768.0


class VoiceActivityDetector:
    """Erkennt Sprachbeginn und Sprachende in einem Audiostrom.

    Die Erkennung arbeitet mit zwei Verzögerungen, damit sie nicht auf
    einzelne Geräusche anspringt: Sprache gilt erst als begonnen, wenn der
    Pegel mehrere Blöcke lang über dem Schwellwert liegt, und erst als
    beendet, wenn er eine konfigurierte Zeit darunter bleibt.
    """

    def __init__(
        self,
        *,
        block_duration_ms: float = 30.0,
        start_blocks: int = 3,
        silence_duration_ms: float = 900.0,
        threshold_factor: float = 3.0,
        minimum_level: float = 0.004,
        max_utterance_seconds: float = 20.0,
    ) -> None:
        """
        Args:
            block_duration_ms: Dauer eines Audioblocks in Millisekunden.
            start_blocks: Wie viele laute Blöcke einen Sprachbeginn auslösen.
            silence_duration_ms: Wie lange es still sein muss, damit eine
                Äußerung als beendet gilt.
            threshold_factor: Um welchen Faktor der Pegel über dem
                Grundpegel liegen muss.
            minimum_level: Absoluter Mindestpegel; verhindert, dass in
                völliger Stille jedes Rauschen als Sprache gilt.
            max_utterance_seconds: Obergrenze für eine einzelne Äußerung.
                Verhindert, dass Dauergeräusch endlos aufgezeichnet wird.
        """

        self._block_duration = block_duration_ms / 1000.0
        self._start_blocks = max(1, start_blocks)
        self._silence_blocks = max(1, int(silence_duration_ms / block_duration_ms))
        self._threshold_factor = threshold_factor
        self._minimum_level = minimum_level
        self._max_blocks = max(1, int(max_utterance_seconds / self._block_duration))

        self._state = VadState.SILENCE
        self._noise_floor = minimum_level
        self._loud_blocks = 0
        self._quiet_blocks = 0
        self._speech_blocks = 0

    @property
    def state(self) -> VadState:
        """Der aktuelle Zustand."""

        return self._state

    @property
    def noise_floor(self) -> float:
        """Der aktuell angenommene Grundpegel."""

        return self._noise_floor

    @property
    def threshold(self) -> float:
        """Der aktuell wirksame Schwellwert."""

        return max(self._minimum_level, self._noise_floor * self._threshold_factor)

    def reset(self) -> None:
        """Setzt die Erkennung zurück, ohne den gelernten Grundpegel zu verlieren."""

        self._state = VadState.SILENCE
        self._loud_blocks = 0
        self._quiet_blocks = 0
        self._speech_blocks = 0

    def process(self, samples: Sequence[int]) -> VadEvent:
        """Verarbeitet einen Audioblock.

        Args:
            samples: 16-Bit-Ganzzahlwerte des Blocks.

        Returns:
            Das Ereignis mit Angabe, ob eine Äußerung begonnen oder geendet
            hat.
        """

        level = rms(samples)
        event = VadEvent(level=level, noise_floor=self._noise_floor)

        is_loud = level > self.threshold

        if self._state is VadState.SILENCE:
            # Grundpegel nur in Ruhe nachführen, damit Sprache ihn nicht
            # nach oben zieht und die Erkennung unempfindlich macht.
            if not is_loud:
                self._noise_floor = self._noise_floor * 0.95 + level * 0.05

            if is_loud:
                self._loud_blocks += 1
                if self._loud_blocks >= self._start_blocks:
                    self._state = VadState.SPEECH
                    self._quiet_blocks = 0
                    self._speech_blocks = self._loud_blocks
                    self._loud_blocks = 0
                    event.speech_started = True
            else:
                self._loud_blocks = 0

        else:
            self._speech_blocks += 1

            if is_loud:
                self._quiet_blocks = 0
            else:
                self._quiet_blocks += 1

            too_long = self._speech_blocks >= self._max_blocks
            if self._quiet_blocks >= self._silence_blocks or too_long:
                self._state = VadState.SILENCE
                self._quiet_blocks = 0
                self._speech_blocks = 0
                self._loud_blocks = 0
                event.speech_ended = True

        event.noise_floor = self._noise_floor
        return event

    @property
    def silence_blocks_needed(self) -> int:
        """Wie viele stille Blöcke eine Äußerung beenden."""

        return self._silence_blocks
