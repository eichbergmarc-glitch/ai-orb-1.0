"""Erkennung des Weckworts („Hallo Orb").

Das Weckwort wird nicht auf dem Audiosignal erkannt, sondern auf dem
transkribierten Text. Das hat zwei Vorteile: Es wird kein zusätzliches
Weckwort-Modell benötigt, und der Benutzer kann in ``config.yaml`` beliebige
Weckworte eintragen, ohne etwas neu zu trainieren.

Die Erkennung ist bewusst fehlertolerant. Die Spracherkennung liefert je
nach Aussprache und Hintergrundgeräusch „Hallo Orb", „Hallo, Orb!",
„Hallo Ort" oder „hallo orp". All das soll den Orb wecken, ohne dass jedes
beliebige Wort ihn aufweckt.

Enthält die Äußerung nach dem Weckwort bereits einen Auftrag – etwa
„Hallo Orb, woran arbeite ich gerade?" –, wird dieser gleich mit
zurückgegeben, damit der Benutzer nicht zweimal sprechen muss.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Satzzeichen, die vor dem Vergleich entfernt werden.
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)

#: Füllwörter, die einer Anrede vorangehen können und ignoriert werden.
_LEADING_FILLER: frozenset[str] = frozenset({"ähm", "äh", "hm", "also", "ok", "okay"})


@dataclass
class WakeWordMatch:
    """Das Ergebnis der Weckwort-Prüfung."""

    #: Ob das Weckwort erkannt wurde.
    detected: bool = False
    #: Das erkannte Weckwort in seiner konfigurierten Schreibweise.
    phrase: str = ""
    #: Übereinstimmungsgrad zwischen 0.0 und 1.0.
    score: float = 0.0
    #: Der Text nach dem Weckwort – der eigentliche Auftrag, falls vorhanden.
    command: str = ""

    @property
    def has_command(self) -> bool:
        """Ob nach dem Weckwort bereits ein Auftrag folgte."""

        return bool(self.command.strip())


def normalize(text: str) -> str:
    """Bereitet Text für den Vergleich auf.

    Entfernt Satzzeichen, vereinheitlicht Umlaute in ihrer Zusammensetzung
    und reduziert Mehrfach-Leerzeichen.
    """

    lowered = unicodedata.normalize("NFC", text).lower().strip()
    without_punctuation = _PUNCTUATION.sub(" ", lowered)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def similarity(left: str, right: str) -> float:
    """Ähnlichkeit zweier Zeichenketten zwischen 0.0 und 1.0."""

    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


class WakeWordDetector:
    """Prüft transkribierten Text auf das Weckwort."""

    def __init__(
        self,
        phrases: list[str] | None = None,
        *,
        threshold: float = 0.78,
        max_leading_words: int = 3,
    ) -> None:
        """
        Args:
            phrases: Die zu erkennenden Weckworte.
            threshold: Ab welcher Ähnlichkeit ein Treffer gilt. Höhere Werte
                bedeuten strengere Erkennung.
            max_leading_words: Wie viele Wörter vor dem Weckwort stehen
                dürfen. Verhindert, dass ein Weckwort mitten in einem langen
                Satz den Orb weckt.
        """

        self._phrases = [phrase for phrase in (phrases or ["hallo orb"]) if phrase.strip()]
        self._threshold = threshold
        self._max_leading_words = max(0, max_leading_words)
        self._normalized = [(phrase, normalize(phrase)) for phrase in self._phrases]

    @property
    def phrases(self) -> list[str]:
        """Die konfigurierten Weckworte."""

        return list(self._phrases)

    def detect(self, transcript: str) -> WakeWordMatch:
        """Prüft eine Äußerung auf das Weckwort.

        Args:
            transcript: Der von der Spracherkennung gelieferte Text.

        Returns:
            Das Ergebnis inklusive des nachfolgenden Auftrags, falls vorhanden.
        """

        normalized_text = normalize(transcript)
        if not normalized_text:
            return WakeWordMatch()

        words = normalized_text.split(" ")

        # Führende Füllwörter überspringen, damit "Ähm, hallo Orb" ebenfalls
        # erkannt wird.
        start_index = 0
        while start_index < len(words) and words[start_index] in _LEADING_FILLER:
            start_index += 1

        best = WakeWordMatch()

        for original, phrase in self._normalized:
            phrase_length = len(phrase.split(" "))

            # Das Weckwort darf nicht beliebig weit hinten stehen.
            last_offset = min(len(words), start_index + self._max_leading_words + 1)
            for offset in range(start_index, last_offset):
                window = " ".join(words[offset : offset + phrase_length])
                if not window:
                    continue

                score = similarity(window, phrase)
                if score >= self._threshold and score > best.score:
                    remainder = " ".join(words[offset + phrase_length :]).strip()
                    best = WakeWordMatch(
                        detected=True,
                        phrase=original,
                        score=score,
                        command=remainder,
                    )

        return best

    def strip_wake_word(self, transcript: str) -> str:
        """Entfernt ein etwaiges Weckwort und gibt nur den Auftrag zurück.

        Nützlich, wenn der Orb bereits wach ist, der Benutzer ihn aber aus
        Gewohnheit erneut anspricht.
        """

        match = self.detect(transcript)
        if match.detected:
            return match.command
        return transcript.strip()
