"""Tests der Stop-Wort-Erkennung.

Der Orb soll aufhoeren zu sprechen, wenn "stop" faellt - aber nicht bei
jedem Geraeusch und nicht mitten im eigenen Wort. Geprueft wird beides:
dass "stop" greift, und dass es NICHT in "Gehalt" oder "Haltung" anschlaegt.
"""

from __future__ import annotations

from backend.voice.voice_pipeline import VoicePipeline


class _Stub(VoicePipeline):
    """Nur die Stop-Wort-Pruefung, ohne den ganzen Aufbau zu starten."""

    def __init__(self, stop_words):
        # Bewusst nicht super().__init__ - wir brauchen nur das eine Feld.
        self._stop_words = {w.lower() for w in stop_words}


def test_stop_wird_erkannt():
    p = _Stub(["stop", "stopp", "halt"])
    assert p._contains_stop_word("stop")
    assert p._contains_stop_word("Stopp!")
    assert p._contains_stop_word("ja halt bitte")
    assert p._contains_stop_word("Moment, STOP")


def test_stop_wort_in_anderem_wort_greift_nicht():
    """'halt' darf nicht in 'Gehalt' oder 'Haltung' anschlagen."""

    p = _Stub(["stop", "halt"])
    assert not p._contains_stop_word("Das Gehalt war hoch")
    assert not p._contains_stop_word("seine Haltung war klar")
    assert not p._contains_stop_word("der Stopfen")


def test_ohne_stop_woerter_nie():
    p = _Stub([])
    assert not p._contains_stop_word("stop")


def test_leerer_text():
    p = _Stub(["stop"])
    assert not p._contains_stop_word("")
