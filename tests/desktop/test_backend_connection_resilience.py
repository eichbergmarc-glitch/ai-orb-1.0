"""Regressionstests fuer die dauerhafte Verbindung zwischen Orb und Kern."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_kurzer_sse_fehler_schaltet_den_orb_nicht_sofort_offline():
    api = (ROOT / "desktop" / "renderer" / "api.ts").read_text(encoding="utf-8")

    error_handler = api.split("source.onerror = () => {", 1)[1].split("};", 1)[0]
    assert "setConnected(false)" not in error_handler
    assert "scheduleDisconnectCheck()" in error_handler
    assert "scheduleReconnect()" in error_handler
    assert "4500" in api
    assert "`${this.baseUrl}/health`" in api
    assert 'payload.status === "ok"' in api
    assert "readyState === EventSource.OPEN" in api


def test_alte_wiederverbindung_kann_keinen_neuen_kanal_schliessen():
    api = (ROOT / "desktop" / "renderer" / "api.ts").read_text(encoding="utf-8")

    assert "this.eventSource !== source" in api
    assert "private reconnectTimer" in api
    assert "this.clearReconnectTimer()" in api
    assert "this.stopped" in api


def test_reconnect_ueberschreibt_keinen_laufenden_orb_zustand():
    main = (ROOT / "desktop" / "renderer" / "main.ts").read_text(encoding="utf-8")

    connection = main.split("backend.onConnectionChange", 1)[1].split("backend.connect", 1)[0]
    assert 'states.setState("offline")' in connection
    assert 'states.current === "offline"' in connection
    assert 'states.setState(connected ? "idle" : "offline")' not in connection


def test_sse_server_sendet_sofort_und_bleibt_aktiv():
    server = (ROOT / "backend" / "api" / "http_server.py").read_text(encoding="utf-8")

    assert 'protocol_version = "HTTP/1.1"' in server
    assert 'self.send_header("X-Accel-Buffering", "no")' in server
    assert 'b"retry: 1000\\n: connected\\n\\n"' in server
    assert "client.queue.get(timeout=5.0)" in server
