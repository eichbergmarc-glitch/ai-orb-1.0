"""Tests der Sprachsteuerung (Phasen 2, 4, 15).

Geprüft wird das, was ohne Mikrofon und Lautsprecher prüfbar ist: die
Weckworterkennung, die Sprachaktivitätserkennung, das Aufbereiten und
Zerlegen von Text sowie die Ableitung der Gefühlslage.

Der Rest – Aufnahme und Wiedergabe – lässt sich nur an echter Hardware
prüfen und ist deshalb hier ausgespart.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

from backend.audio.player import AudioPlayer
from backend.audio.vad import VadState, VoiceActivityDetector, rms
from backend.tts import emotion
from backend.tts.base_engine import SpeechRequest
from backend.tts.tts_manager import TtsManager
from backend.whisper.wake_word import WakeWordDetector, normalize, similarity


# --- Weckwort ----------------------------------------------------------------


def test_wake_word_detects_exact_phrase() -> None:
    detector = WakeWordDetector(["Hallo Orb"])
    match = detector.detect("Hallo Orb")
    assert match.detected
    assert match.score > 0.95


def test_wake_word_tolerates_misrecognition() -> None:
    """Die Spracherkennung liefert selten genau das Richtige."""

    detector = WakeWordDetector(["Hallo Orb"])
    for variant in ["hallo orb", "Hallo, Orb!", "hallo orp", "Hallo Ort"]:
        assert detector.detect(variant).detected, variant


def test_wake_word_ignores_unrelated_speech() -> None:
    """Nicht jedes Wort weckt den Orb."""

    detector = WakeWordDetector(["Hallo Orb"])
    for text in ["Guten Morgen", "Wie geht es dir", "Das Fenster ist offen", ""]:
        assert not detector.detect(text).detected, text


def test_wake_word_extracts_trailing_command() -> None:
    """„Hallo Orb, wie spät ist es?" soll nicht zweimal gesprochen werden müssen."""

    detector = WakeWordDetector(["Hallo Orb"])
    match = detector.detect("Hallo Orb, wie spät ist es?")
    assert match.detected
    assert match.has_command
    assert "wie spät ist es" in match.command


def test_wake_word_skips_leading_filler() -> None:
    detector = WakeWordDetector(["Hallo Orb"])
    assert detector.detect("Ähm, hallo Orb").detected


def test_wake_word_not_in_middle_of_sentence() -> None:
    """Ein Weckwort weit hinten im Satz weckt nicht."""

    detector = WakeWordDetector(["Hallo Orb"], max_leading_words=2)
    text = "Ich habe gestern lange nachgedacht und dann gesagt hallo Orb"
    assert not detector.detect(text).detected


def test_strip_wake_word_leaves_command() -> None:
    detector = WakeWordDetector(["Hallo Orb"])
    assert detector.strip_wake_word("Hallo Orb, öffne den Browser") == "öffne den browser"
    # Ohne Weckwort bleibt der Text unverändert.
    assert detector.strip_wake_word("Öffne den Browser") == "Öffne den Browser"


def test_normalize_and_similarity() -> None:
    assert normalize("Hallo, Orb!") == "hallo orb"
    assert similarity("hallo orb", "hallo orb") == 1.0
    assert similarity("hallo orb", "") == 0.0
    assert 0.7 < similarity("hallo orb", "hallo orp") < 1.0


# --- Sprachaktivitätserkennung -------------------------------------------------


def _tone(amplitude: int, count: int = 480) -> list[int]:
    """Erzeugt einen Sinuston als Testsignal."""

    return [int(amplitude * math.sin(index * 0.3)) for index in range(count)]


def test_rms_of_silence_is_zero() -> None:
    assert rms([0] * 480) == 0.0
    assert rms([]) == 0.0


def test_rms_grows_with_amplitude() -> None:
    assert rms(_tone(1000)) < rms(_tone(8000))


def test_vad_detects_speech_start_and_end() -> None:
    detector = VoiceActivityDetector(
        block_duration_ms=30.0, start_blocks=2, silence_duration_ms=120.0
    )

    # Erst Ruhe, damit sich der Grundpegel einpendelt.
    for _ in range(20):
        detector.process([0] * 480)
    assert detector.state is VadState.SILENCE

    started = False
    for _ in range(6):
        event = detector.process(_tone(9000))
        started = started or event.speech_started
    assert started
    assert detector.state is VadState.SPEECH

    ended = False
    for _ in range(12):
        event = detector.process([0] * 480)
        ended = ended or event.speech_ended
    assert ended
    assert detector.state is VadState.SILENCE


def test_vad_ignores_single_noise_burst() -> None:
    """Ein einzelnes Geräusch löst keine Aufnahme aus."""

    detector = VoiceActivityDetector(block_duration_ms=30.0, start_blocks=4)
    for _ in range(20):
        detector.process([0] * 480)

    event = detector.process(_tone(9000))
    assert not event.speech_started


def test_vad_stops_after_maximum_duration() -> None:
    """Dauergeräusch wird nicht endlos aufgezeichnet."""

    detector = VoiceActivityDetector(
        block_duration_ms=30.0, start_blocks=1, max_utterance_seconds=0.3
    )
    for _ in range(10):
        detector.process([0] * 480)

    ended = False
    for _ in range(40):
        event = detector.process(_tone(9000))
        ended = ended or event.speech_ended
    assert ended


# --- Sprachausgabe ---------------------------------------------------------------


def test_prepare_text_removes_markup() -> None:
    """Auszeichnungszeichen würden sonst mitgelesen."""

    prepared = TtsManager.prepare_text("**Wichtig**: das _hier_ ist `Code`")
    assert "*" not in prepared
    assert "_" not in prepared
    assert "`" not in prepared
    assert "Wichtig" in prepared


def test_prepare_text_announces_code_blocks() -> None:
    """Ein Codeblock wird angekündigt, nicht vorgelesen."""

    prepared = TtsManager.prepare_text("Hier bitte:\n```python\nprint('x')\n```\nFertig.")
    assert "print" not in prepared
    assert "Code" in prepared
    assert "Fertig" in prepared


def test_prepare_text_removes_bullets() -> None:
    prepared = TtsManager.prepare_text("- erstens\n- zweitens")
    assert not prepared.startswith("-")
    assert "erstens" in prepared


def test_split_into_chunks_respects_sentences() -> None:
    """Zerlegt wird an Satzgrenzen, nicht mitten im Wort."""

    manager = TtsManager()
    text = "Erster Satz. Zweiter Satz. Dritter Satz. Vierter Satz."
    chunks = manager.split_into_chunks(text, max_characters=30)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 35, chunk
    # Nichts geht verloren.
    assert "Vierter" in " ".join(chunks)


def test_split_into_chunks_keeps_short_text_whole() -> None:
    manager = TtsManager()
    assert manager.split_into_chunks("Kurz.", max_characters=100) == ["Kurz."]
    assert manager.split_into_chunks("") == []


def test_speech_request_cache_key_is_stable() -> None:
    """Gleicher Text und gleiche Einstellung ergeben denselben Schlüssel."""

    first = SpeechRequest(text="Hallo", voice="a", speed=1.0)
    second = SpeechRequest(text="Hallo", voice="a", speed=1.0)
    third = SpeechRequest(text="Hallo", voice="a", speed=1.2)

    assert first.cache_key() == second.cache_key()
    assert first.cache_key() != third.cache_key()


def _write_tone(path: Path, amplitude: int) -> Path:
    values = _tone(amplitude, count=16000)
    import array

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(array.array("h", values).tobytes())
    return path


def test_wiedergabe_gleicht_unterschiedliche_tts_pegel_behutsam_aus(tmp_path: Path) -> None:
    player = AudioPlayer(normalize_volume=True, target_rms=0.14)
    leise = player._normalization_gain(_write_tone(tmp_path / "leise.wav", 3500))
    laut = player._normalization_gain(_write_tone(tmp_path / "laut.wav", 12000))

    assert 1.0 < leise <= 1.55
    assert 0.68 <= laut < 1.0


def test_pegelnormalisierung_laesst_sich_abschalten(tmp_path: Path) -> None:
    player = AudioPlayer(normalize_volume=False)
    assert player._normalization_gain(_write_tone(tmp_path / "satz.wav", 3500)) == 1.0


# --- Gefühlslage -------------------------------------------------------------------


def test_emotion_detected_from_text() -> None:
    assert emotion.detect("Da ist leider ein Fehler aufgetreten.").name == "bedauernd"
    assert emotion.detect("Achtung, das ist dringend!").name == "dringlich"
    assert emotion.detect("Fertig, das hat geklappt.").name == "erfreut"
    assert emotion.detect("Ich denke, vermutlich ist es so.").name == "nachdenklich"


def test_text_beats_state() -> None:
    """Eine Fehlermeldung klingt bedauernd, auch wenn der Orb munter ist."""

    assert emotion.detect("Ein Fehler ist aufgetreten.", state="speaking").name == "bedauernd"


def test_emotion_falls_back_to_state() -> None:
    assert emotion.detect("Ein ganz gewöhnlicher Satz.", state="listening").name == "aufmerksam"
    assert emotion.detect("Ein ganz gewöhnlicher Satz.", state="sleep").name == "leise"


def test_emotion_values_are_moderate() -> None:
    """Keine Gefühlslage übertreibt."""

    for profile in emotion.EMOTIONS.values():
        assert 0.85 <= profile.speed <= 1.15, profile.name
        assert abs(profile.pitch) <= 1.5, profile.name
        assert 0.6 <= profile.volume <= 1.15, profile.name


def test_unknown_emotion_falls_back_to_neutral() -> None:
    assert emotion.get_emotion("euphorisch").name == "neutral"


# ---------------------------------------------------------------------------
#  Dazwischenreden (Barge-in)
# ---------------------------------------------------------------------------
#
#  Der Anlass für diese Tests: Das Dazwischenreden war beschrieben, war
#  konfigurierbar, hatte Code – und konnte trotzdem nie funktionieren. Der
#  Orb schaltet das Mikrofon ab, solange er spricht, und die Erkennung
#  brach bei Stummschaltung sofort ab. Der Abbruch der Wiedergabe hing an
#  einem Rückruf, der genau dann nie kam.
#
#  Getestet wird deshalb nicht "gibt es die Einstellung", sondern: Kommt
#  die Meldung an, während stummgeschaltet ist?


class _StummeAufnahme:
    """Ein Ersatz für das Mikrofon, der Blöcke von Hand einspeist."""

    def __init__(self, capture):
        self.capture = capture

    def block(self, laut: bool):
        import array

        wert = 9000 if laut else 2
        samples = array.array("h", [wert] * 480)
        self.capture._handle_block(samples.tobytes())


def _capture(on_interruption, hold_ms=90.0):
    from backend.audio.audio_capture import AudioCapture

    return AudioCapture(
        lambda path, dauer: None,
        on_interruption=on_interruption,
        interruption_hold_ms=hold_ms,
    )


def test_unterbrechung_wird_trotz_stummschaltung_gemeldet(tmp_path):
    """Stumm heißt: nichts aufnehmen. Nicht: nichts merken."""

    gemeldet = []
    capture = _capture(lambda: gemeldet.append(1))
    capture._output_directory = tmp_path
    capture.mute(True)

    quelle = _StummeAufnahme(capture)
    for _ in range(40):
        quelle.block(laut=True)

    assert gemeldet, "Während der Stummschaltung wurde kein Dazwischenreden gemeldet."


def test_kurzes_geraeusch_gilt_nicht_als_unterbrechung(tmp_path):
    """Ein einzelner Ausschlag ist der eigene Lautsprecher, kein Wort."""

    gemeldet = []
    capture = _capture(lambda: gemeldet.append(1), hold_ms=300.0)
    capture._output_directory = tmp_path
    capture.mute(True)

    quelle = _StummeAufnahme(capture)
    quelle.block(laut=True)
    quelle.block(laut=False)
    quelle.block(laut=True)
    quelle.block(laut=False)

    assert not gemeldet, "Ein kurzes Geräusch wurde als Unterbrechung gewertet."


def test_unterbrechung_wird_nur_einmal_gemeldet(tmp_path):
    """Ein zweiter Hinweis brächte nichts – gestoppt ist gestoppt."""

    gemeldet = []
    capture = _capture(lambda: gemeldet.append(1), hold_ms=60.0)
    capture._output_directory = tmp_path
    capture.mute(True)

    quelle = _StummeAufnahme(capture)
    for _ in range(60):
        quelle.block(laut=True)

    assert len(gemeldet) == 1, f"Erwartet: eine Meldung. Bekommen: {len(gemeldet)}."


def test_ohne_rueckruf_bleibt_alles_still(tmp_path):
    """Wer nichts hören will, soll nicht abstürzen."""

    capture = _capture(None)
    capture._output_directory = tmp_path
    capture.mute(True)

    quelle = _StummeAufnahme(capture)
    for _ in range(40):
        quelle.block(laut=True)
