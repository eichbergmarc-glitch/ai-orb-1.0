from __future__ import annotations

import wave
from pathlib import Path

from backend.tts.base_engine import SpeechRequest, SpeechResult
from backend.tts.openvoice_clone_engine import OpenVoiceCloneEngine
from backend.tts.tts_manager import TtsManager


def _write_wav(path: Path, *, frames: int = 2205) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(b"\0\0" * frames)


class _FakePiper:
    def synthesize_blocking(
        self, request: SpeechRequest, target: Path
    ) -> SpeechResult:
        _write_wav(target)
        return SpeechResult(audio_path=target, engine="piper", duration_seconds=0.1)


class _FakeConverter:
    def convert(
        self,
        source: Path,
        source_se: object,
        target_se: object,
        target: Path,
        *,
        tau: float,
    ) -> None:
        assert source_se == "quelle"
        assert target_se == "ziel"
        assert tau == 0.3
        target.write_bytes(source.read_bytes())


def test_schneller_klon_konvertiert_piper_und_entfernt_nur_die_zwischenablage(
    tmp_path: Path, monkeypatch
) -> None:
    reference = tmp_path / "reference.wav"
    _write_wav(reference)
    engine = OpenVoiceCloneEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference), "tau": 0.3},
    )
    converter = _FakeConverter()
    monkeypatch.setattr(engine, "_load", lambda: converter)
    engine._piper = _FakePiper()  # type: ignore[assignment]
    engine._source_se = "quelle"
    engine._target_se = "ziel"

    target = tmp_path / "antwort.wav"
    result = engine.synthesize_blocking(SpeechRequest(text="Hallo."), target)

    assert result.succeeded
    assert result.engine == "openvoice_clone"
    assert result.context["local"] is True
    assert not (tmp_path / "antwort-source.wav").exists()


def test_klon_cache_beruecksichtigt_referenz_und_basisstimme(tmp_path: Path) -> None:
    reference = tmp_path / "reference.wav"
    _write_wav(reference)
    request = SpeechRequest(text="Gleicher Satz.")
    high = OpenVoiceCloneEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference), "base_voice": "high"},
    )
    medium = OpenVoiceCloneEngine(
        output_directory=tmp_path,
        options={"reference_audio": str(reference), "base_voice": "medium"},
    )

    high_path = high.target_path(request)
    assert high_path != medium.target_path(request)
    reference.write_bytes(reference.read_bytes() + b"veraendert")
    assert high_path != high.target_path(request)


def test_die_stimmreihe_endet_lokal() -> None:
    """Vorne die beste Stimme, hinten eine, die immer da ist.

    Der Test hing frueher an einem Namen fest und war nach jedem Wechsel
    rot, ohne dass etwas kaputt war. Gemeint ist die Ordnung: Die erste
    Stimme darf aus der Cloud kommen (seit 01.09.2026 OpenAI 'cedar', die
    Stimme, fuer die die Persona-Anweisung in der config.yaml geschrieben
    wurde). Die letzte muss lokal sein, sonst bedeutet ein Netzausfall
    Stille - und der Wechsel dorthin muss erlaubt sein.
    """

    manager = TtsManager()
    names = [engine.name for engine in manager._engines]
    lokal = {"pocket_tts", "supertonic", "piper", "openvoice_clone", "kokoro", "sapi"}

    assert names, "es ist keine Stimme eingerichtet"
    assert names[-1] in lokal, "die letzte Stimme muss ohne Netz sprechen koennen"
    assert manager._offline_engine_names
    assert set(manager._offline_engine_names) <= lokal
    assert manager._allow_voice_fallback is True
