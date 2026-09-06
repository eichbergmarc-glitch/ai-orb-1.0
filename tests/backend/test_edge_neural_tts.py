from __future__ import annotations

import wave
from pathlib import Path

from backend.tts.base_engine import SpeechRequest
from backend.tts.edge_neural_engine import EdgeNeuralEngine


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"\0\0" * 2400)


def test_edge_neural_variiert_tempo_und_tonhoehe_nur_behutsam(tmp_path: Path) -> None:
    engine = EdgeNeuralEngine(
        output_directory=tmp_path,
        options={
            "voice": "de-DE-FlorianMultilingualNeural",
            "rate_percent": 2,
        },
    )

    freundlich = engine._controls(
        SpeechRequest(text="Hallo.", speed=1.02, pitch=0.5, volume=1.0)
    )
    extrem = engine._controls(
        SpeechRequest(text="Achtung.", speed=2.0, pitch=20.0, volume=2.0)
    )

    assert freundlich == {"rate": "+4%", "pitch": "+4Hz", "volume": "+0%"}
    assert extrem == {"rate": "+15%", "pitch": "+25Hz", "volume": "+10%"}


def test_edge_neural_erzeugt_wav_und_entfernt_mp3_zwischenablage(
    tmp_path: Path, monkeypatch
) -> None:
    engine = EdgeNeuralEngine(output_directory=tmp_path)
    monkeypatch.setattr(engine, "is_available", lambda: True)
    gesehen: dict[str, object] = {}

    def _mp3(request, destination, controls):  # noqa: ANN001
        gesehen.update(text=request.text, controls=controls)
        destination.write_bytes(b"mp3")

    def _wav(source, destination):  # noqa: ANN001
        assert source.read_bytes() == b"mp3"
        _write_wav(destination)

    monkeypatch.setattr(engine, "_synthesize_mp3", _mp3)
    monkeypatch.setattr(engine, "_decode_mp3", _wav)
    request = SpeechRequest(
        text="Naja, schauen wir hin.",
        speed=0.98,
        pitch=0.5,
        emotion="freundlich",
    )
    target = engine.target_path(request)

    result = engine.synthesize_blocking(request, target)

    assert result.succeeded
    assert result.engine == "edge_neural"
    assert result.context["voice"] == "de-DE-FlorianMultilingualNeural"
    assert gesehen["text"] == request.text
    assert not target.with_name(f"{target.stem}-edge.mp3").exists()


def test_edge_neural_cache_beruecksichtigt_stimme_und_prosodie(tmp_path: Path) -> None:
    request = SpeechRequest(text="Gleicher Satz.", speed=0.98, pitch=0.0)
    florian = EdgeNeuralEngine(
        output_directory=tmp_path,
        options={"voice": "de-DE-FlorianMultilingualNeural"},
    )
    conrad = EdgeNeuralEngine(
        output_directory=tmp_path,
        options={"voice": "de-DE-ConradNeural"},
    )

    assert florian.target_path(request) != conrad.target_path(request)
    lebhafter = SpeechRequest(text=request.text, speed=1.08, pitch=0.8)
    assert florian.target_path(request) != florian.target_path(lebhafter)
