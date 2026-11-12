"""Handy-Werkzeuge (12.11.2026): anrufen, Nachrichten, Apps, Dokumente."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.tools import handy_tools as h

PERSONEN = {
    "connections": [
        {"names": [{"displayName": "Peter Muster"}],
         "phoneNumbers": [{"value": "031 123 45 67", "formattedType": "Privat"},
                          {"value": "079 555 66 77", "formattedType": "Mobil"}]},
        {"names": [{"displayName": "Peter Keller"}],
         "phoneNumbers": [{"value": "+41 78 111 22 33"}]},
        {"names": [{"displayName": "Mama"}], "phoneNumbers": [{"value": "062 900 00 00"}]},
        {"names": [{"displayName": "Ohne Nummer"}]},
    ]
}


class Auth:
    def access_token(self):
        return "t"


@pytest.fixture
def buch():
    return h.Kontaktbuch(Auth(), abrufen=lambda url, token: PERSONEN)


@pytest.fixture(autouse=True)
def handy():
    h.geraet_aktiv(True)
    yield
    h.geraet_aktiv(False)
    h.aktionen_abholen()


def lauf(tool, **args):
    return asyncio.run(tool.execute(args))


def test_nummern():
    assert h.nummer_normalisieren("079 555 66 77") == "+41795556677"
    assert h.nummer_normalisieren("0049 170 1234567") == "+491701234567"
    assert h.nummer_normalisieren("+41 31 123 45 67") == "+41311234567"
    assert h.nummer_normalisieren("Peter") == ""


def test_anrufen_mit_name(buch):
    ergebnis = lauf(h.AnrufenTool(buch), wen="Mama")
    assert ergebnis.ok
    assert h.aktionen_abholen() == [
        {"art": "anruf", "url": "tel:+41629000000", "titel": "Mama anrufen"}]


def test_mehrdeutig_fragt_nach(buch):
    ergebnis = lauf(h.AnrufenTool(buch), wen="Peter")
    assert not ergebnis.ok and "Peter Muster" in ergebnis.error and "Peter Keller" in ergebnis.error


def test_whatsapp_nimmt_handynummer(buch):
    ergebnis = lauf(h.NachrichtSendenTool(buch), wen="peter muster", text="Bin um 5 da")
    assert ergebnis.ok, ergebnis.error
    (aktion,) = h.aktionen_abholen()
    assert aktion["url"] == "https://wa.me/41795556677?text=Bin%20um%205%20da"


def test_sms_und_direkte_nummer():
    ergebnis = lauf(h.NachrichtSendenTool(None), wen="079 555 66 77", text="Hallo", kanal="sms")
    assert ergebnis.ok
    assert h.aktionen_abholen()[0]["url"] == "sms:+41795556677&body=Hallo"


def test_unbekannt(buch):
    assert "nicht" in lauf(h.AnrufenTool(buch), wen="Zorro").error


def test_nur_vom_handy(buch):
    h.geraet_aktiv(False)
    assert not lauf(h.AnrufenTool(buch), wen="Mama").ok


def test_apps_und_kurzbefehl():
    assert lauf(h.AppOeffnenTool(), app="Karten", ziel="Bern Bahnhof").ok
    assert lauf(h.KurzbefehlStartenTool(), name="Licht aus").ok
    assert lauf(h.AppOeffnenTool(), app="WhatsApp").ok
    urls = [a["url"] for a in h.aktionen_abholen()]
    assert urls == ["maps://?daddr=Bern%20Bahnhof",
                    "shortcuts://run-shortcut?name=Licht%20aus", "whatsapp://"]
    assert not lauf(h.AppOeffnenTool(), app="Gibtsnicht").ok


def test_dokument_freigabe(tmp_path: Path):
    datei = tmp_path / "reiseplan.pdf"
    datei.write_bytes(b"%PDF-1.4")
    kennung = h.dokument_freigeben(datei, "Reiseplan")
    assert h.dokument_pfad(kennung) == datei
    assert h.dokument_pfad("falsch") is None
    (aktion,) = h.aktionen_abholen()
    assert aktion == {"art": "dokument", "url": "/dokument?id=" + kennung,
                      "titel": "Reiseplan öffnen"}


def test_kontakte_fehlende_freigabe():
    def abweisen(url, token):
        raise h.KontaktFehler("Synapse darf die Kontakte noch nicht lesen.")

    ergebnis = lauf(h.AnrufenTool(h.Kontaktbuch(Auth(), abrufen=abweisen)), wen="Mama")
    assert not ergebnis.ok and "Kontakte" in ergebnis.error


def test_oauth_fragt_kontakte_an(monkeypatch):
    from backend.integrations.gmail.oauth import CONTACTS_SCOPE, OAuthConfig

    monkeypatch.delenv("GMAIL_SCOPE", raising=False)
    assert CONTACTS_SCOPE in OAuthConfig.from_env().scope
