"""Der Rückweg der Google-Anmeldung.

Was am 17.08.2026 geschah: Der Benutzer sagte „Melde mich bei Gmail an",
der Browser öffnete Google, er stimmte zu - und Google schickte ihn mit dem
Einmalcode auf ``http://127.0.0.1:8756/gmail/callback`` zurück. Dort stand:
``{"error": "not_found"}``. Die Route gab es nicht. Der Hinweg war fertig
gebaut, der Rückweg fehlte vollständig - der Code kam an und verschwand
ungelesen. (Der Beleg steht im Werkzeugprotokoll: Der Benutzer liess den
Orb sogar den Bildschirm ansehen, und der las ihm seine eigene
Callback-Adresse samt Code vor.)

Geprüft wird der ganze Rückweg über einen ECHTEN lokalen HTTP-Server:
Route vorhanden, Code wird angenommen, gegen das Token getauscht (mit dem
PKCE-Prüfwert aus Schritt eins), der Benutzer bekommt eine lesbare Seite,
der Orb erfährt davon. Und die Fehlwege: Ablehnung bei Google, kein
laufender Anmeldevorgang, kaputter Code.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from backend.agents.gmail_agent import GmailAgent
from backend.api.http_server import ApiRouter, LocalApiServer, SseBroker
from backend.integrations.gmail.oauth import GmailAuth, OAuthConfig


# --- Ein Google aus Papier --------------------------------------------------


class _GoogleAttrappe:
    """Nimmt den Token-Tausch entgegen wie das echte oauth2.googleapis.com."""

    def __init__(self):
        self.tausch_anfragen: list[dict[str, str]] = []
        gegenstand = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_POST(self):
                laenge = int(self.headers.get("Content-Length", 0))
                roh = self.rfile.read(laenge).decode("utf-8")
                from urllib.parse import parse_qs

                felder = {k: v[0] for k, v in parse_qs(roh).items()}
                gegenstand.tausch_anfragen.append(felder)

                if felder.get("code") == "guter-code":
                    antwort = json.dumps({
                        "access_token": "zt-123",
                        "refresh_token": "rt-456",
                        "expires_in": 3600,
                        "scope": ("https://www.googleapis.com/auth/gmail.modify "
                                  "https://www.googleapis.com/auth/calendar.events"),
                    }).encode()
                    self.send_response(200)
                else:
                    antwort = json.dumps({"error": "invalid_grant"}).encode()
                    self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(antwort)))
                self.end_headers()
                self.wfile.write(antwort)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def schliessen(self):
        self._server.shutdown()


class _RuntimeAttrappe:
    def __init__(self, agent):
        self.gmail = agent
        self.ereignisse: list[tuple[str, dict]] = []

    def publish(self, name, payload=None):
        self.ereignisse.append((name, payload or {}))


def _agent(tmp_path, google) -> GmailAgent:
    auth = GmailAuth(
        OAuthConfig(client_id="cid", client_secret="geheim"),
        token_path=tmp_path / "token.json",
    )
    # Den Token-Endpunkt auf die Attrappe biegen.
    import backend.integrations.gmail.oauth as oauth_modul

    oauth_modul._TOKEN_ENDPOINT = f"http://127.0.0.1:{google.port}/token"
    return GmailAgent(security=None, auth=auth)


@pytest.fixture
def umgebung(tmp_path):
    google = _GoogleAttrappe()
    agent = _agent(tmp_path, google)
    laufzeit = _RuntimeAttrappe(agent)

    # Den ECHTEN Router mit der echten Route bauen - aber nur diese eine.
    from backend.api.server import build_router

    router = ApiRouter()
    voll = build_router.__wrapped__ if hasattr(build_router, "__wrapped__") else None
    # build_router braucht die ganze Runtime; hier wird nur die
    # Callback-Route nachgebaut, mit demselben Handler-Code.
    import backend.api.server as server_modul

    ganzer_router = None
    try:
        ganzer_router = server_modul.build_router(laufzeit)  # type: ignore[arg-type]
    except AttributeError:
        pass

    if ganzer_router is not None and ganzer_router.resolve("GET", "/gmail/callback"):
        router = ganzer_router

    broker = SseBroker()
    server = LocalApiServer("127.0.0.1", 0, router, broker)
    server.start()

    yield agent, laufzeit, server, google

    server.stop()
    google.schliessen()


def _abrufen(server, weg: str) -> tuple[int, str]:
    adresse = f"http://127.0.0.1:{server.port}{weg}"
    try:
        with urllib.request.urlopen(adresse, timeout=10) as antwort:
            return antwort.status, antwort.read().decode("utf-8")
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read().decode("utf-8")


# --- Der Weg, der gefehlt hat ----------------------------------------------


def test_die_callback_route_existiert(umgebung):
    agent, _, server, _ = umgebung
    status, koerper = _abrufen(server, "/gmail/callback")
    # Kein not_found mehr. (400 ist in Ordnung - ohne Code UND ohne
    # laufende Anmeldung gibt es nichts abzuschliessen.)
    assert "not_found" not in koerper


def test_der_ganze_rueckweg_von_code_bis_token(umgebung):
    agent, laufzeit, server, google = umgebung

    bericht = agent.begin_login()
    assert bericht["ok"], bericht

    status, koerper = _abrufen(server, "/gmail/callback?code=guter-code&scope=x")

    assert status == 200
    assert "erfolgreich" in koerper.lower()
    assert "Kalender" in koerper

    # Der Tausch muss mit dem PKCE-Pruefwert aus Schritt eins laufen.
    assert google.tausch_anfragen, "Google wurde nie gefragt"
    tausch = google.tausch_anfragen[0]
    assert tausch["code"] == "guter-code"
    assert tausch["code_verifier"] == bericht["verifier"]
    assert tausch["redirect_uri"] == bericht["redirect_uri"]

    # Danach IST der Orb angemeldet - mit Kalender.
    assert agent._auth.is_authenticated
    assert "calendar" in agent._auth.granted_scopes()

    # Und der Orb hat es erfahren.
    assert ("gmail.login.completed", {"kalender": True}) in laufzeit.ereignisse


def test_eine_ablehnung_bei_google_wird_verstaendlich_gezeigt(umgebung):
    agent, _, server, google = umgebung
    agent.begin_login()
    status, koerper = _abrufen(server, "/gmail/callback?error=access_denied")
    assert status == 400
    assert "access_denied" in koerper
    assert not agent._auth.is_authenticated
    assert not google.tausch_anfragen, "ohne Code darf Google nicht gefragt werden"


def test_ein_code_ohne_laufende_anmeldung_wird_erklaert(umgebung):
    agent, _, server, _ = umgebung
    status, koerper = _abrufen(server, "/gmail/callback?code=guter-code")
    assert status == 400
    assert "Melde mich bei Gmail an" in koerper


def test_ein_abgelehnter_code_laesst_den_zweiten_versuch_zu(umgebung):
    agent, _, server, google = umgebung
    agent.begin_login()

    status, _ = _abrufen(server, "/gmail/callback?code=schlechter-code")
    assert status == 400
    assert not agent._auth.is_authenticated

    # Der Anmeldevorgang lebt noch: Ein zweiter Aufruf mit gutem Code
    # (etwa nach einem Neuladen der Seite) darf noch gelingen.
    status, _ = _abrufen(server, "/gmail/callback?code=guter-code")
    assert status == 200
    assert agent._auth.is_authenticated


def test_die_seite_ist_fuer_menschen_nicht_fuer_programme(umgebung):
    agent, _, server, _ = umgebung
    agent.begin_login()
    _, koerper = _abrufen(server, "/gmail/callback?code=guter-code")
    assert koerper.lstrip().startswith("<!DOCTYPE html"), (
        "der Benutzer sitzt im Browser - er soll einen Satz lesen, kein JSON"
    )
