"""Tests für die TIDAL-Anbindung - ohne einen einzigen echten Netzaufruf."""

from __future__ import annotations

import asyncio
import time
import urllib.parse
from typing import Any

from backend.integrations.gmail.oauth import Token
from backend.integrations.tidal.client import TidalClient
from backend.integrations.tidal.oauth import TidalAuth, TidalOAuthConfig
from backend.security.permissions import KNOWN_PERMISSIONS
from backend.tools.tidal_tools import TidalDienst, _songs_lesen, build_tidal_tools


class AttrappeTransport:
    def __init__(self) -> None:
        self.aufrufe: list[tuple[str, str, str, Any]] = []

    def request(self, method: str, url: str, *, token: str, body: Any) -> dict[str, Any]:
        self.aufrufe.append((method, url, token, body))
        pfad = urllib.parse.urlparse(url).path
        if "/searchResults/" in pfad:
            return {"data": [{"id": "111", "type": "tracks"}, {"id": "222", "type": "tracks"}]}
        if pfad.endswith("/tracks"):
            return {
                "data": [
                    {"id": "111", "type": "tracks", "attributes": {"title": "Yellow", "duration": "PT4M26S"},
                     "relationships": {"artists": {"data": [{"id": "9", "type": "artists"}]}}},
                ],
                "included": [{"id": "9", "type": "artists", "attributes": {"name": "Coldplay"}}],
            }
        if pfad.endswith("/playlists") and method == "POST":
            return {"data": {"id": "pl-1", "type": "playlists", "attributes": {"name": body["data"]["attributes"]["name"]}}}
        if pfad.endswith("/relationships/items") and method == "POST":
            return {}
        if "userCollectionPlaylists" in pfad:
            return {
                "data": [{"id": "pl-1", "type": "playlists"}, {"id": "pl-2", "type": "playlists"}],
                "included": [
                    {"id": "pl-1", "type": "playlists", "attributes": {"name": "Waldrunde", "numberOfItems": 3}},
                    {"id": "pl-2", "type": "playlists", "attributes": {"name": "Sport"}},
                ],
            }
        return {}


def _auth(tmp_path, *, angemeldet: bool = True) -> TidalAuth:
    def post(url: str, felder: dict[str, str], *, basic=None) -> dict[str, Any]:
        assert felder["grant_type"] in ("client_credentials", "authorization_code", "refresh_token")
        return {"access_token": "tok-" + felder["grant_type"], "expires_in": 3600, "refresh_token": "r"}

    auth = TidalAuth(
        TidalOAuthConfig(client_id="id", client_secret="geheim"),
        token_path=tmp_path / "token.json",
        post=post,
    )
    if angemeldet:
        auth._save_token(Token(access_token="user", refresh_token="r", expires_at=time.time() + 3600))
    return auth


def _werkzeuge(tmp_path, *, angemeldet: bool = True):
    transport = AttrappeTransport()
    geoeffnet: list[str] = []
    client = TidalClient(_auth(tmp_path, angemeldet=angemeldet), land="CH", transport=transport)
    dienst = TidalDienst(client, oeffner=lambda app, web, **_: geoeffnet.append(app) or "app")
    return {t.name: t for t in build_tidal_tools(dienst)}, transport, geoeffnet


def test_berechtigung_ist_bekannt():
    assert "music" in KNOWN_PERMISSIONS


def test_songs_lesen():
    assert _songs_lesen("1. Hello von Adele; - Yellow\nCreep") == ["Hello von Adele", "Yellow", "Creep"]


def test_suche_ohne_anmeldung_nutzt_anwendungstoken(tmp_path):
    werkzeuge, transport, _ = _werkzeuge(tmp_path, angemeldet=False)
    ergebnis = asyncio.run(werkzeuge["musik_suchen"].execute({"suche": "Yellow", "anzahl": 1}))
    assert ergebnis.ok
    assert "Coldplay" in ergebnis.output
    assert transport.aufrufe[0][2] == "tok-client_credentials"
    assert "countryCode=CH" in transport.aufrufe[0][1]


def test_abspielen_oeffnet_app(tmp_path):
    werkzeuge, _, geoeffnet = _werkzeuge(tmp_path)
    ergebnis = asyncio.run(werkzeuge["musik_abspielen"].execute({"suche": "Yellow von Coldplay"}))
    assert ergebnis.ok
    assert geoeffnet == ["tidal://track/111"]


def test_playlist_erstellen(tmp_path):
    werkzeuge, transport, _ = _werkzeuge(tmp_path)
    ergebnis = asyncio.run(
        werkzeuge["playlist_erstellen"].execute({"name": "Waldrunde", "songs": "Yellow von Coldplay"})
    )
    assert ergebnis.ok, ergebnis.error
    anlegen = [a for a in transport.aufrufe if a[0] == "POST" and a[1].split("?")[0].endswith("/playlists")]
    assert anlegen and anlegen[0][2] == "user"
    items = [a for a in transport.aufrufe if "relationships/items" in a[1] and a[0] == "POST"]
    assert items[0][3] == {"data": [{"id": "111", "type": "tracks"}]}


def test_playlist_ohne_anmeldung_sagt_wie(tmp_path):
    werkzeuge, transport, _ = _werkzeuge(tmp_path, angemeldet=False)
    ergebnis = asyncio.run(werkzeuge["playlist_erstellen"].execute({"name": "X", "songs": "Yellow"}))
    assert not ergebnis.ok
    assert "anmelden" in ergebnis.error.lower() or "angemeldet" in ergebnis.error.lower()
    assert not transport.aufrufe


def test_eigene_playlist_abspielen(tmp_path):
    werkzeuge, _, geoeffnet = _werkzeuge(tmp_path)
    ergebnis = asyncio.run(werkzeuge["musik_abspielen"].execute({"suche": "sport", "art": "playlist"}))
    assert ergebnis.ok
    assert geoeffnet == ["tidal://playlist/pl-2"]


def test_anmeldung_prueft_state(tmp_path):
    auth = _auth(tmp_path, angemeldet=False)
    url = auth.anmelde_url()
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["code_challenge_method"] == ["S256"]
    try:
        auth.anmeldung_abschliessen("code", "falsch")
        raise AssertionError("falscher state wurde angenommen")
    except Exception as fehler:  # noqa: BLE001
        assert "passt nicht" in str(fehler)
    auth.anmeldung_abschliessen("code", params["state"][0])
    assert auth.user_token() == "tok-authorization_code"
