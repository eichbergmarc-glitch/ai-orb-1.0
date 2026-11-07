"""Spracherkennung ueber OpenAI mit lokalem Rueckfall (06.11.2026)."""

from __future__ import annotations

import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from backend.whisper.transcriber import Transcriber

GESEHEN: list[bytes] = []
ZUSTAND = {"ablehnen": False}


class _Server(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        GESEHEN.append(body)
        if ZUSTAND["ablehnen"] and b"gpt-4o-mini-transcribe" in body:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"unbekannt"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"text": "Fasse die Nachrichten zusammen."}).encode())


def _wav(tmp_path):
    pfad = tmp_path / "a.wav"
    with wave.open(str(pfad), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 1600)
    return pfad


def _mit_server(tmp_path, monkeypatch, **cloud):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        t = Transcriber(cloud={
            "enabled": True,
            "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
            "models": ["gpt-4o-mini-transcribe", "whisper-1"],
            **cloud,
        })
        return t._transcribe_cloud(_wav(tmp_path), None)
    finally:
        server.shutdown()


def test_cloud_liefert_text_mit_sprache(tmp_path, monkeypatch):
    ergebnis = _mit_server(tmp_path, monkeypatch)
    assert ergebnis.text == "Fasse die Nachrichten zusammen."
    assert ergebnis.confidence >= 0.8
    assert b'name="language"' in GESEHEN[-1]


def test_unbekanntes_modell_nimmt_das_naechste(tmp_path, monkeypatch):
    ZUSTAND["ablehnen"] = True
    try:
        ergebnis = _mit_server(tmp_path, monkeypatch)
    finally:
        ZUSTAND["ablehnen"] = False
    assert ergebnis.text
    assert b"whisper-1" in GESEHEN[-1]


def test_ohne_netz_faellt_auf_lokal_zurueck(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    t = Transcriber(cloud={"enabled": True, "base_url": "http://127.0.0.1:9/v1", "timeout": 1})
    assert t._transcribe_cloud(_wav(tmp_path), None) is None
    # und versucht es nicht bei jedem Satz sofort wieder
    assert t._transcribe_cloud(_wav(tmp_path), None) is None


def test_ohne_schluessel_bleibt_alles_lokal(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    t = Transcriber(cloud={"enabled": True})
    assert t._transcribe_cloud(_wav(tmp_path), None) is None
