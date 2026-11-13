"""OpenAI-TTS als Strom (13.11.2026): erste Silbe ohne auf die ganze Datei zu warten."""

from __future__ import annotations

import io
import wave

from backend.tts import openai_tts_engine as o
from backend.tts.base_engine import DATEI_NOETIG, SpeechRequest


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _engine(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    e = o.OpenAITtsEngine(output_directory=tmp_path, options={"api_key_env": "OPENAI_API_KEY"})
    return e


def test_strom_und_datei(tmp_path, monkeypatch):
    pcm = (b"\x10\x00\xf0\xff" * 12000)  # 1 s Ton
    gesehen = []

    def urlopen(anfrage, timeout=0):
        import json
        nutz = json.loads(anfrage.data.decode())
        gesehen.append(nutz["response_format"])
        if nutz["response_format"] == "pcm":
            return _Antwort(pcm)
        puffer = io.BytesIO()
        with wave.open(puffer, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        return _Antwort(puffer.getvalue())

    monkeypatch.setattr(o.urllib.request, "urlopen", urlopen)
    e = _engine(tmp_path, monkeypatch)
    ziel = tmp_path / "a.wav"
    r = e.synthesize_blocking(SpeechRequest(text="Hallo Marc."), ziel)
    strom = r.context.get("pcm_stream")
    assert strom is not None and gesehen == ["pcm"]
    assert b"".join(strom.iter_chunks()) == pcm
    strom.wait_until_done(5)
    with wave.open(str(ziel)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == len(pcm) // 2

    marke = DATEI_NOETIG.set(True)
    try:
        r2 = e.synthesize_blocking(SpeechRequest(text="Hallo Marc."), tmp_path / "b.wav")
    finally:
        DATEI_NOETIG.reset(marke)
    assert "pcm_stream" not in r2.context and gesehen[-1] == "wav" and r2.audio_path.exists()
