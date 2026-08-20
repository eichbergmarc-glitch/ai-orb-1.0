"""Ein 429 ist kein Nein.

Am 18.08.2026 um 11:08 bat der Benutzer um Bilder zu den Nachrichten.
Die Bildsuche fand vier Treffer. Drei davon scheiterten innerhalb von
1.4 Sekunden am selben Grund::

    11:08:17  Bild nicht ladbar (.../Robots_in_Robot_Dream_): 429
    11:08:17  Bild nicht ladbar (.../Robot_Dream_Exhibition_Hong_): 429
    11:08:17  Bild nicht ladbar (.../CyberpunkHumanoidChef_): 429

429 heisst "zu schnell", nicht "gibt es nicht". Wikimedia drosselt
Stossbetrieb pro Adresse; die Bilder waren da und frei. Der Orb sagte
dem Benutzer trotzdem, es gebe keine - und der fragte danach zweimal
nach ("Ich warte immer noch auf die Bilder").

Geprüft wird mit einem echten HTTP-Server, der genau so drosselt.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.grafik import bildquellen


class _Drossel(BaseHTTPRequestHandler):
    """Antwortet die ersten Male mit 429, danach mit dem Bild."""

    absagen = 2
    zaehler = 0
    retry_after = ""

    def do_GET(self):  # noqa: N802
        type(self).zaehler += 1
        if type(self).zaehler <= type(self).absagen:
            self.send_response(429)
            if type(self).retry_after:
                self.send_header("Retry-After", type(self).retry_after)
            self.end_headers()
            return
        nutzlast = b"\x89PNG\r\n\x1a\n" + b"x" * 64
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(nutzlast)))
        self.end_headers()
        self.wfile.write(nutzlast)

    def log_message(self, *_args):  # Stille im Testlauf.
        return


@pytest.fixture
def drossel():
    _Drossel.zaehler = 0
    _Drossel.absagen = 2
    _Drossel.retry_after = ""
    server = HTTPServer(("127.0.0.1", 0), _Drossel)
    faden = threading.Thread(target=server.serve_forever, daemon=True)
    faden.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/bild.png"
    server.shutdown()
    server.server_close()


def test_nach_zwei_absagen_kommt_das_bild_doch(drossel, monkeypatch):
    # Die echten Wartezeiten wuerden den Testlauf um Sekunden verlaengern;
    # geprueft wird das Verhalten, nicht die Uhr.
    monkeypatch.setattr(bildquellen, "_WARTEN", (0.01, 0.01))

    daten = bildquellen._abrufen(drossel)

    assert daten.startswith(b"\x89PNG")
    assert _Drossel.zaehler == 3, "es haette zweimal wiederholt werden muessen"


def test_die_angabe_des_dienstes_wird_beachtet(drossel, monkeypatch):
    _Drossel.retry_after = "0.5"
    monkeypatch.setattr(bildquellen, "_WARTEN", (9.0, 9.0))
    gewartet: list[float] = []
    monkeypatch.setattr(bildquellen.time, "sleep", gewartet.append)

    bildquellen._abrufen(drossel)

    assert gewartet == [0.5, 0.5], gewartet


def test_irgendwann_wird_aufgegeben(drossel, monkeypatch):
    # Sonst haengt der Orb an einem Dienst, der dauerhaft drosselt.
    _Drossel.absagen = 99
    monkeypatch.setattr(bildquellen, "_WARTEN", (0.01, 0.01))

    with pytest.raises(bildquellen.BildquelleFehler) as fehler:
        bildquellen._abrufen(drossel)

    assert "429" in str(fehler.value)
    assert _Drossel.zaehler == bildquellen._WIEDERHOLUNGEN + 1


def test_ein_echtes_nein_wird_nicht_wiederholt(monkeypatch):
    # Bei 404 hilft Warten nicht - dann waere jeder Versuch verlorene Zeit.
    class _Weg(BaseHTTPRequestHandler):
        zaehler = 0

        def do_GET(self):  # noqa: N802
            type(self).zaehler += 1
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), _Weg)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(bildquellen.BildquelleFehler):
            bildquellen._abrufen(f"http://127.0.0.1:{server.server_address[1]}/x.png")
        assert _Weg.zaehler == 1
    finally:
        server.shutdown()
        server.server_close()
