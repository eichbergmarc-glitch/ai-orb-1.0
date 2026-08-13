"""Natürlicher Sprechrhythmus ohne Nachahmung einer Stimme.

Das Modul entscheidet sparsam, ob vor einer anspruchsvolleren Antwort ein
kurzes Denkgeräusch sinnvoll ist. Es arbeitet nur mit Textlänge und Zeit;
Inhalt, Audio und Identität werden weder gespeichert noch versendet.
"""

from __future__ import annotations

import time


class HumanSpeechPolicy:
    """Begrenzt Denklaute, damit sie menschlich und nicht mechanisch wirken."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        fillers_enabled: bool = True,
        cooldown_seconds: float = 38.0,
        minimum_words: int = 9,
    ) -> None:
        self.enabled = enabled
        self.fillers_enabled = fillers_enabled
        self.cooldown_seconds = max(5.0, cooldown_seconds)
        self.minimum_words = max(4, minimum_words)
        self._last_cue = -1e9
        self._eligible_turns = 0

    def thinking_cue(self, text: str, *, now: float | None = None) -> str:
        """Gibt gelegentlich einen kurzen Denklaut zurück, sonst leer.

        Lange/verschachtelte Fragen erhalten eher einen Laut. Bei normalen
        Fragen wird nur jeder dritte geeignete Gesprächszug markiert. Die
        Abkühlzeit verhindert, dass sich der Effekt als Tick wiederholt.
        """

        if not self.enabled or not self.fillers_enabled:
            return ""
        moment = time.monotonic() if now is None else now
        if moment - self._last_cue < self.cooldown_seconds:
            return ""

        words = [word for word in text.replace("?", " ").split() if word]
        complexity = len(words)
        complexity += 3 * sum(
            marker in text.lower()
            for marker in ("warum", "vergleiche", "analysiere", "erkläre", "abwägen", "entscheide")
        )
        if complexity < self.minimum_words:
            return ""

        self._eligible_turns += 1
        if complexity < 18 and self._eligible_turns % 3 != 1:
            return ""

        self._last_cue = moment
        return "Hmm." if complexity < 24 else "Hmm, lass mich kurz überlegen."
