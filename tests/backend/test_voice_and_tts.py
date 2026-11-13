"""Tests der Sprachsteuerung (Phasen 2, 4, 15).

Geprüft wird das, was ohne Mikrofon und Lautsprecher prüfbar ist: die
Weckworterkennung, die Sprachaktivitätserkennung, das Aufbereiten und
Zerlegen von Text sowie die Ableitung der Gefühlslage.

Der Rest – Aufnahme und Wiedergabe – lässt sich nur an echter Hardware
prüfen und ist deshalb hier ausgespart.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import urllib.error
import wave
from pathlib import Path

from backend.audio.player import AudioPlayer
from backend.audio.vad import VadState, VoiceActivityDetector, rms
from backend.tts import emotion
from backend.tts.base_engine import SpeechRequest, SpeechResult
from backend.tts.chatterbox_engine import ChatterboxEngine
from backend.tts.elevenlabs_engine import ElevenLabsEngine
from backend.tts.german_text import jahreszahl_in_worten, jahreszahlen_sprechbar
from backend.tts.openai_tts_engine import OpenAITtsEngine
from backend.tts.pocket_tts_engine import PocketTtsEngine
from backend.tts.remote_tts_engine import RemoteTtsEngine
from backend.tts.supertonic_engine import SupertonicEngine
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


def test_jahreszahlen_werden_eindeutig_deutsch_gesprochen() -> None:
    assert jahreszahl_in_worten(1789) == "siebzehnhundertneunundachtzig"
    assert jahreszahl_in_worten(1815) == "achtzehnhundertfünfzehn"
    assert jahreszahl_in_worten(1945) == "neunzehnhundertfünfundvierzig"
    assert jahreszahl_in_worten(2026) == "zweitausendsechsundzwanzig"


def test_jahresbereiche_und_aeren_werden_sprechbar() -> None:
    text = jahreszahlen_sprechbar(
        "Der Krieg dauerte 1914–1918; Caesar starb 44 v. Chr. und um 800 begann Neues."
    )
    assert "neunzehnhundertvierzehn bis neunzehnhundertachtzehn" in text
    assert "vierundvierzig vor Christus" in text
    assert "um achthundert" in text


def test_dezimalzahlen_werden_nicht_als_jahr_umgedeutet() -> None:
    text = jahreszahlen_sprechbar("Der Messwert beträgt 1.789 und der Port ist 8080.")
    assert "1.789" in text
    assert "8080" in text


def test_prepare_text_entfernt_zoegernde_typografie() -> None:
    prepared = TtsManager.prepare_text("Nun … vielleicht — aber sicher im Jahr 1789.")
    assert "…" not in prepared
    assert "—" not in prepared
    assert "siebzehnhundertneunundachtzig" in prepared


def test_elevenlabs_bekommt_stabile_prosodie_und_das_echte_tempo(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    engine = ElevenLabsEngine(
        output_directory=tmp_path,
        options={
            "voice_id": "stimme",
            "stability": 0.61,
            "similarity_boost": 0.84,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    )
    payloads: list[dict] = []

    class _Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"\x00\x00" * 200

    def _urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _Antwort()

    monkeypatch.setattr("backend.tts.elevenlabs_engine.urllib.request.urlopen", _urlopen)
    request = SpeechRequest(text="Im Jahr 1789 begann es.", speed=0.93, pitch=0.5)
    ergebnis = engine.synthesize_blocking(request, engine.target_path(request))

    assert ergebnis.succeeded
    assert payloads[0]["model_id"] == "eleven_flash_v2_5"
    settings = payloads[0]["voice_settings"]
    assert settings == {
        "stability": 0.61,
        "similarity_boost": 0.84,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 0.93,
    }


def test_elevenlabs_cache_aendert_sich_mit_der_prosodie(tmp_path: Path) -> None:
    request = SpeechRequest(text="Gleicher Satz.", speed=1.0)
    ruhig = ElevenLabsEngine(
        output_directory=tmp_path,
        options={"voice_id": "a", "stability": 0.6, "style": 0.0},
    )
    dramatisch = ElevenLabsEngine(
        output_directory=tmp_path,
        options={"voice_id": "a", "stability": 0.4, "style": 0.5},
    )
    assert ruhig.target_path(request) != dramatisch.target_path(request)


def test_elevenlabs_status_zeigt_referenzstimme_und_echtzeitmodell(
    tmp_path: Path,
) -> None:
    engine = ElevenLabsEngine(
        output_directory=tmp_path,
        options={"voice_id": "orb-referenz"},
    )

    status = engine.status()

    assert status["voice_id"] == "orb-referenz"
    assert status["model"] == "eleven_flash_v2_5"
    assert status["low_latency"] is True


def test_elevenlabs_markiert_abgelehnten_schluessel_fuer_die_sitzung(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "ungueltig")
    engine = ElevenLabsEngine(
        output_directory=tmp_path,
        options={"voice_id": "stimme"},
    )

    def _urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"detail":"invalid key"}'),
        )

    monkeypatch.setattr("backend.tts.elevenlabs_engine.urllib.request.urlopen", _urlopen)
    result = engine.synthesize_blocking(
        SpeechRequest("Neue Antwort."), engine.target_path(SpeechRequest("Neue Antwort."))
    )

    assert not result.succeeded
    assert result.context["fatal_for_session"] is True
    assert "401" in result.error


def test_openai_tts_erhaelt_menschliche_regie_und_latenzformat(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    engine = OpenAITtsEngine(
        output_directory=tmp_path,
        options={
            "model": "gpt-4o-mini-tts",
            "voice": "cedar",
            "streaming": False,  # hier geht es um den Datei-Weg
            "instructions": (
                "Sprich spontan und natuerlich. Kein Nachrichtensprecher, "
                "kein Roboterklang."
            ),
        },
    )
    payloads: list[dict] = []
    wav = io.BytesIO()
    with wave.open(wav, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\0\0" * 2400)

    class _Antwort:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return wav.getvalue()

    def _urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _Antwort()

    monkeypatch.setattr(
        "backend.tts.openai_tts_engine.urllib.request.urlopen",
        _urlopen,
    )
    request = SpeechRequest(
        text="Naja, das ist ziemlich offensichtlich.",
        speed=0.98,
        emotion="freundlich",
    )

    result = engine.synthesize_blocking(request, engine.target_path(request))

    assert result.succeeded
    assert payloads[0]["model"] == "gpt-4o-mini-tts"
    assert payloads[0]["voice"] == "cedar"
    assert payloads[0]["response_format"] == "wav"
    assert "spontan und natuerlich" in payloads[0]["instructions"]
    assert "zugewandt und wach" in payloads[0]["instructions"]
    assert result.context["local"] is False


def test_openai_tts_cache_unterscheidet_regie_und_emotion(tmp_path: Path) -> None:
    request = SpeechRequest(text="Derselbe Satz.", emotion="freundlich")
    direkt = OpenAITtsEngine(
        output_directory=tmp_path,
        options={"instructions": "Sprich direkt."},
    )
    ruhig = OpenAITtsEngine(
        output_directory=tmp_path,
        options={"instructions": "Sprich sehr ruhig."},
    )

    assert direkt.target_path(request) != ruhig.target_path(request)
    nachdenklich = SpeechRequest(text=request.text, emotion="nachdenklich")
    assert direkt.target_path(request) != direkt.target_path(nachdenklich)


def test_tts_status_zeigt_pausierte_elevenlabs_engine_und_fallback(tmp_path: Path) -> None:
    manager = TtsManager.__new__(TtsManager)
    eleven = ElevenLabsEngine(
        output_directory=tmp_path, options={"voice_id": "stimme"}
    )
    piper = type(
        "PiperStatusStub",
        (),
        {
            "name": "piper",
            "is_available": lambda self: True,
            "status": lambda self: {"name": "piper", "available": True},
        },
    )()
    manager._enabled = True
    manager._offline_mode = False
    manager._active = piper
    manager._engines = [eleven, piper]
    manager._offline_engine_names = ["piper"]
    manager._engine_failed_until = {"elevenlabs": float("inf")}
    manager._engine_failure_reasons = {"elevenlabs": "HTTP 401: Schlüssel abgelehnt"}
    manager._spoken_count = 1
    manager._emotions_enabled = True
    manager._stable_volume = True
    manager._cache_enabled = True
    manager._output_directory = tmp_path
    manager._last_result = SpeechResult(audio_path=tmp_path / "piper.wav", engine="piper")

    status = manager.status()

    assert status["active_engine"] == "piper"
    assert status["preferred_engine"] == "piper"
    assert status["fallback_active"] is True
    assert "elevenlabs" not in status["available"]
    assert status["engines"][0]["paused"] is True
    assert "401" in status["degraded_reason"]


def test_remote_stimme_erhaelt_tempo_und_emotion(tmp_path: Path, monkeypatch) -> None:
    """Der GPU-Server muss wissen, wie der aktuelle Orb-Zustand klingen soll."""

    monkeypatch.setenv("REMOTE_TTS_TOKEN", "nur-test")
    engine = RemoteTtsEngine(
        output_directory=tmp_path,
        options={
            "endpoint": "https://stimme.invalid",
            "token_env": "REMOTE_TTS_TOKEN",
            "speaker": 0,
            "timeout": 12,
        },
    )
    payloads: list[dict] = []

    class _Antwort:
        headers = {"Content-Type": "audio/wav"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"RIFF" + b"\x00" * 64

    def _urlopen(request, timeout=0):  # noqa: ANN001, ARG001
        payloads.append(json.loads(request.data.decode("utf-8")))
        return _Antwort()

    monkeypatch.setattr("backend.tts.remote_tts_engine.urllib.request.urlopen", _urlopen)
    request = SpeechRequest(
        text="Das klingt neugierig.", speed=0.94, emotion="curious"
    )
    ergebnis = engine.synthesize_blocking(request, engine.target_path(request))

    assert ergebnis.succeeded
    assert payloads == [
        {
            "text": "Das klingt neugierig.",
            "speaker": 0,
            "speed": 0.94,
            "emotion": "curious",
        }
    ]


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


def _write_tone_with_silence(
    path: Path, amplitude: int, *, silence_samples: int
) -> Path:
    import array

    values = [0] * silence_samples + _tone(amplitude, count=16000) + [0] * silence_samples
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

    assert 1.0 < leise <= 2.0
    assert 0.50 <= laut < 1.0


def test_lautheitsmessung_ignoriert_unterschiedlich_lange_pausen(tmp_path: Path) -> None:
    player = AudioPlayer(normalize_volume=True, target_rms=0.10)
    ohne_pause = player._normalization_gain(
        _write_tone_with_silence(tmp_path / "ohne-pause.wav", 5000, silence_samples=0)
    )
    mit_pause = player._normalization_gain(
        _write_tone_with_silence(tmp_path / "mit-pause.wav", 5000, silence_samples=24000)
    )

    assert abs(ohne_pause - mit_pause) < 0.04


def test_ueberfluessige_randstille_wird_auf_einen_kurzen_atemrand_begrenzt(
    tmp_path: Path,
) -> None:
    path = _write_tone_with_silence(
        tmp_path / "mit-langem-rand.wav", 5000, silence_samples=16000
    )
    player = AudioPlayer(
        trim_boundary_silence=True,
        leading_silence_ms=30,
        trailing_silence_ms=70,
    )

    start, end = player._playback_bounds(path)

    # Eine Sekunde Stille davor/danach wird auf 30/70 ms reduziert.
    assert 15000 <= start <= 16000
    assert 32000 <= end <= 33400
    assert (end - start) / 16000 < 1.15


def test_sehr_unterschiedliche_sprachpegel_naehren_sich_demselben_ziel(tmp_path: Path) -> None:
    player = AudioPlayer(normalize_volume=True, target_rms=0.10)
    leiser_pfad = _write_tone(tmp_path / "sehr-leise.wav", 1500)
    lauter_pfad = _write_tone(tmp_path / "sehr-laut.wav", 9000)
    leise = player._normalization_gain(leiser_pfad)
    laut = player._normalization_gain(lauter_pfad)

    # Der Sinuston hat RMS = Amplitude / sqrt(2) / 32768.
    leise_nachher = (1500 / math.sqrt(2) / 32768) * leise
    laut_nachher = (9000 / math.sqrt(2) / 32768) * laut
    assert abs(leise_nachher - laut_nachher) < 0.015
    assert 0.085 <= leise_nachher <= 0.115


def test_emotion_veraendert_bei_stabilem_pegel_nicht_die_ausgabelautstaerke() -> None:
    manager = TtsManager()
    requests: list[SpeechRequest] = []

    async def capture(request: SpeechRequest) -> SpeechResult:
        requests.append(request)
        return SpeechResult(error="nur Test")

    manager._synthesize_with_fallback = capture  # type: ignore[method-assign]
    asyncio.run(manager.speak("Das hat geklappt.", emotion="erfreut"))
    asyncio.run(manager.speak("Das ist fehlgeschlagen.", emotion="bedauernd"))

    assert len(requests) == 2
    assert requests[0].volume == requests[1].volume == 1.0


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


def test_chatterbox_schreibt_kompatibles_pcm_wav(tmp_path):
    """Der lokale Klon muss von Windows und Orbs WAV-Pruefung lesbar sein."""

    import torch

    reference = tmp_path / "referenz.wav"
    reference.write_bytes(b"RIFF")
    engine = ChatterboxEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference), "language": "de"},
    )

    class _Model:
        sr = 24000

        @staticmethod
        def generate(*args, **kwargs):
            return torch.zeros((1, 2400), dtype=torch.float32)

    engine._model = _Model()
    result = engine.synthesize_blocking(
        SpeechRequest("Hallo"), tmp_path / "stimme.wav"
    )

    assert result.succeeded
    assert result.engine == "chatterbox"
    assert 0.09 <= result.duration_seconds <= 0.11


def test_pocket_tts_schreibt_schnelles_kompatibles_pcm_wav(tmp_path):
    """Die neue lokale Primaerstimme liefert simples PCM16 fuer den Player."""

    import torch

    engine = PocketTtsEngine(
        output_directory=tmp_path,
        options={
            "model_variant": "german_24l",
            "voice": "juergen",
            "streaming": False,
        },
    )

    class _Model:
        sample_rate = 24000

        @staticmethod
        def generate_audio(state, text, *, max_tokens):
            assert state == "juergen-state"
            assert text == "Hallo"
            assert max_tokens == 50
            return torch.zeros(2400, dtype=torch.float32)

    engine._model = _Model()
    engine._voice_state = "juergen-state"
    result = engine.synthesize_blocking(
        SpeechRequest("Hallo"), tmp_path / "pocket.wav"
    )

    assert result.succeeded
    assert result.engine == "pocket_tts"
    assert result.context["local"] is True
    assert result.context["model_variant"] == "german_24l"
    assert 0.09 <= result.duration_seconds <= 0.11


def test_supertonic_schreibt_klares_44100_hz_pcm_wav(tmp_path):
    """Die feste Offline-Stimme liefert hochaufloesendes Standard-PCM."""

    import numpy as np

    engine = SupertonicEngine(
        output_directory=tmp_path,
        options={"voice": "M1", "language": "de", "steps": 8},
    )
    received = {}

    class _Model:
        sample_rate = 44100

        @staticmethod
        def synthesize(text, **kwargs):
            received["text"] = text
            received.update(kwargs)
            return np.zeros((1, 4410), dtype=np.float32), np.array([0.1])

    engine._model = _Model()
    engine._voice_style = "m1-style"
    result = engine.synthesize_blocking(
        SpeechRequest("Markus Gabriel spricht klar."),
        tmp_path / "supertonic.wav",
    )

    assert result.succeeded
    assert result.engine == "supertonic"
    assert result.context["voice"] == "M1"
    assert result.context["avoid_stop_transcription"] is True
    assert received["lang"] == "de"
    assert received["total_steps"] == 8
    with wave.open(str(result.audio_path), "rb") as audio:
        assert audio.getframerate() == 44100
        assert audio.getsampwidth() == 2
        assert audio.getnchannels() == 1


def test_supertonic_cache_trennt_stimme_und_qualitaet(tmp_path):
    request = SpeechRequest("Derselbe Satz.")
    m1 = SupertonicEngine(output_directory=tmp_path, options={"voice": "M1", "steps": 8})
    m4 = SupertonicEngine(output_directory=tmp_path, options={"voice": "M4", "steps": 8})
    fein = SupertonicEngine(output_directory=tmp_path, options={"voice": "M1", "steps": 12})

    assert m1.target_path(request) != m4.target_path(request)
    assert m1.target_path(request) != fein.target_path(request)


def test_chatterbox_cache_trennt_v2_v3_und_referenzdateien(tmp_path):
    reference_a = tmp_path / "referenz-a.wav"
    reference_b = tmp_path / "referenz-b.wav"
    reference_a.write_bytes(b"RIFF-a")
    reference_b.write_bytes(b"RIFF-b")
    request = SpeechRequest("Derselbe Satz.")

    v2 = ChatterboxEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference_a), "model_variant": "v2"},
    )
    v3 = ChatterboxEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference_a), "model_variant": "v3"},
    )
    andere_referenz = ChatterboxEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference_b), "model_variant": "v3"},
    )

    assert v2.target_path(request) != v3.target_path(request)
    assert v3.target_path(request) != andere_referenz.target_path(request)


def test_chatterbox_reicht_v3_parameter_an_das_modell_durch(tmp_path):
    import torch

    reference = tmp_path / "referenz.wav"
    reference.write_bytes(b"RIFF")
    engine = ChatterboxEngine(
        output_directory=tmp_path,
        options={
            "reference_audio": str(reference),
            "model_variant": "v3",
            "language": "de",
            "exaggeration": 0.5,
            "cfg_weight": 0.45,
            "temperature": 0.72,
            "repetition_penalty": 1.2,
            "min_p": 0.05,
            "top_p": 1.0,
        },
    )
    received = {}

    class _Model:
        sr = 24000

        @staticmethod
        def generate(text, **kwargs):
            received.update(kwargs)
            return torch.zeros((1, 2400), dtype=torch.float32)

    engine._model = _Model()
    result = engine.synthesize_blocking(
        SpeechRequest("Hallo"), tmp_path / "v3.wav"
    )

    assert result.succeeded
    assert received["language_id"] == "de"
    assert received["cfg_weight"] == 0.45
    assert received["temperature"] == 0.72
    assert received["repetition_penalty"] == 1.2


def test_chatterbox_begrenzt_ausreisser_bei_der_token_erzeugung(tmp_path):
    """Ein verfehltes Satzende darf den Orb nicht minutenlang blockieren."""

    import torch

    reference = tmp_path / "referenz.wav"
    reference.write_bytes(b"RIFF")
    engine = ChatterboxEngine(
        output_directory=tmp_path,
        options={
            "reference_audio": str(reference),
            "max_new_tokens": 280,
            "tokens_per_character": 2.4,
            "token_margin": 32,
        },
    )
    received = {}

    class _T3:
        @staticmethod
        def inference(*args, **kwargs):
            received.update(kwargs)
            return torch.zeros((1, 1), dtype=torch.long)

    class _Model:
        sr = 24000
        t3 = _T3()

        def generate(self, text, **kwargs):
            self.t3.inference(max_new_tokens=1000)
            return torch.zeros((1, 2400), dtype=torch.float32)

    engine._model = _Model()
    result = engine.synthesize_blocking(
        SpeechRequest("Ein kurzer Satz."), tmp_path / "begrenzt.wav"
    )

    assert result.succeeded
    assert received["max_new_tokens"] == 80
    assert result.context["max_new_tokens"] == 80


def test_chatterbox_tokenlimit_waechst_mit_text_aber_nie_ueber_hartes_limit(tmp_path):
    reference = tmp_path / "referenz.wav"
    reference.write_bytes(b"RIFF")
    engine = ChatterboxEngine(
        output_directory=tmp_path,
        options={
            "reference_audio": str(reference),
            "max_new_tokens": 280,
            "tokens_per_character": 2.4,
            "token_margin": 32,
        },
    )

    assert engine._token_limit("kurz") == 80
    assert engine._token_limit("x" * 50) == 152
    assert engine._token_limit("x" * 500) == 280


def test_chatterbox_uebertraegt_gefuehl_auf_den_ausdruck(tmp_path):
    import torch

    reference = tmp_path / "referenz.wav"
    reference.write_bytes(b"RIFF")
    engine = ChatterboxEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference), "exaggeration": 0.5},
    )
    werte = []

    class _Model:
        sr = 24000

        @staticmethod
        def generate(text, **kwargs):
            werte.append(kwargs["exaggeration"])
            return torch.zeros((1, 2400), dtype=torch.float32)

    engine._model = _Model()
    engine.synthesize_blocking(
        SpeechRequest("Sachlich.", emotion="neutral"), tmp_path / "neutral.wav"
    )
    engine.synthesize_blocking(
        SpeechRequest("Geschafft!", emotion="erfreut"), tmp_path / "erfreut.wav"
    )

    assert werte[0] == 0.5
    assert werte[1] > werte[0]
