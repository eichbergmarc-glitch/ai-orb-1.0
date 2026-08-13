"""Tests der Browsersteuerung.

Playwright und ein echter Browser lassen sich in der Testumgebung nicht
starten - und muessen es auch nicht. Was hier zaehlt, ist zweierlei, und
beides geht ohne Browser:

1. Die UEBERSETZUNG der rohen Element-Daten in das, was der Orb dem Benutzer
   vorliest (Nummer, Art, Beschriftung). Das ist reine Logik.
2. Das WERKZEUG: dass jede Aktion an die richtige Methode geht, dass fehlende
   Angaben sauber gemeldet werden und dass eine fehlende Einrichtung
   (Playwright nicht installiert) nicht den Kern reisst, sondern eine ruhige
   Auskunft ergibt.

Der Browser selbst wird durch eine Attrappe ersetzt, die mitschreibt, was
aufgerufen wurde.
"""

from __future__ import annotations

import asyncio

from backend.browser.steuerung import (
    BrowserNichtBereit,
    Element,
    elemente_aus_roh,
)
from backend.tools.browser_tools import BrowserBedienenTool


# --- Die reine Uebersetzung -----------------------------------------------------


def test_elemente_bekommen_art_und_beschriftung():
    roh = [
        {"idx": 0, "tag": "a", "text": "Zur Startseite", "href": "https://x.de/"},
        {"idx": 1, "tag": "button", "typ": "submit", "text": "Anmelden"},
        {"idx": 2, "tag": "input", "typ": "text", "platzhalter": "Suchbegriff"},
        {"idx": 3, "tag": "select", "aria": "Sprache waehlen"},
        {"idx": 4, "tag": "input", "typ": "checkbox", "name": "agb"},
    ]
    els = elemente_aus_roh(roh)
    assert [e.art for e in els] == ["link", "knopf", "feld", "auswahl", "haken"]
    # Beste sichtbare Beschriftung: Text vor Aria vor Platzhalter.
    assert els[2].beschriftung == "Suchbegriff"
    assert els[3].beschriftung == "Sprache waehlen"
    # Nur Links tragen eine Adresse.
    assert els[0].adresse == "https://x.de/"
    assert els[1].adresse == ""


def test_kaputte_nummer_wird_uebersprungen():
    assert elemente_aus_roh([{"idx": "keine zahl"}]) == []
    assert elemente_aus_roh([{}]) == []


def test_zeile_zeigt_nummer_art_und_adresse():
    el = Element(nummer=3, art="link", beschriftung="Mehr", adresse="https://y.de")
    zeile = el.zeile()
    assert zeile.startswith("3. [link] Mehr")
    assert "https://y.de" in zeile


# --- Das Werkzeug mit einer Attrappe -------------------------------------------


class _Attrappe:
    """Ein Browser, der nur mitschreibt - ohne echten Browser zu starten."""

    def __init__(self) -> None:
        self.aufrufe: list[tuple] = []
        self._stand = {"titel": "Beispielseite", "url": "https://beispiel.de/"}

    async def oeffnen(self, url):
        self.aufrufe.append(("oeffnen", url))
        self._stand = {"titel": "Beispielseite", "url": url}
        return self._stand

    async def elemente(self, grenze=40):
        self.aufrufe.append(("elemente",))
        return [
            Element(0, "feld", "Suche"),
            Element(1, "knopf", "Los"),
        ]

    async def klicken(self, ziel):
        self.aufrufe.append(("klicken", ziel))
        return self._stand

    async def tippen(self, ziel, text, absenden=False):
        self.aufrufe.append(("tippen", ziel, text, absenden))
        return self._stand

    async def scrollen(self, richtung="runter", betrag=0):
        self.aufrufe.append(("scrollen", richtung))
        return self._stand

    async def taste(self, name):
        self.aufrufe.append(("taste", name))
        return self._stand

    async def zurueck(self):
        self.aufrufe.append(("zurueck",))
        return self._stand

    async def stand(self):
        return self._stand

    async def lesen(self, grenze=4000):
        self.aufrufe.append(("lesen",))
        return "Der sichtbare Text der Seite."

    async def schliessen(self):
        self.aufrufe.append(("schliessen",))
        return "Browser geschlossen."


def _werkzeug():
    attrappe = _Attrappe()
    return BrowserBedienenTool(attrappe), attrappe


def test_oeffnen_ruft_die_steuerung():
    werkzeug, attrappe = _werkzeug()
    r = asyncio.run(werkzeug.execute({"aktion": "oeffnen", "ziel": "beispiel.de"}))
    assert r.ok
    assert ("oeffnen", "beispiel.de") in attrappe.aufrufe


def test_oeffnen_ohne_ziel_meldet_das():
    werkzeug, _ = _werkzeug()
    r = asyncio.run(werkzeug.execute({"aktion": "oeffnen"}))
    assert not r.ok
    assert "Adresse" in r.error


def test_elemente_werden_nummeriert_aufgelistet():
    werkzeug, _ = _werkzeug()
    r = asyncio.run(werkzeug.execute({"aktion": "elemente"}))
    assert r.ok
    assert "0. [feld] Suche" in r.output
    assert "1. [knopf] Los" in r.output


def test_tippen_reicht_text_und_absenden_durch():
    werkzeug, attrappe = _werkzeug()
    r = asyncio.run(werkzeug.execute(
        {"aktion": "tippen", "ziel": "0", "text": "Katzen", "absenden": True}
    ))
    assert r.ok
    assert ("tippen", "0", "Katzen", True) in attrappe.aufrufe


def test_tippen_ohne_feld_oder_text_meldet_das():
    werkzeug, _ = _werkzeug()
    r = asyncio.run(werkzeug.execute({"aktion": "tippen", "ziel": "0"}))
    assert not r.ok


def test_klicken_ohne_ziel_meldet_das():
    werkzeug, _ = _werkzeug()
    r = asyncio.run(werkzeug.execute({"aktion": "klicken"}))
    assert not r.ok


def test_unbekannte_aktion_wird_abgewiesen():
    werkzeug, _ = _werkzeug()
    r = asyncio.run(werkzeug.execute({"aktion": "tanzen"}))
    assert not r.ok
    assert "Unbekannte Aktion" in r.error


def test_fehlende_einrichtung_oeffnet_den_standardbrowser(monkeypatch):
    """Ohne Playwright bleibt wenigstens das reine Oeffnen nutzbar."""

    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda _url: True)

    class _Streikt:
        async def oeffnen(self, url):
            raise BrowserNichtBereit(
                "Die Browsersteuerung ist noch nicht eingerichtet. Fuehre "
                "einmal 'BROWSER-EINRICHTEN.bat' aus."
            )

    werkzeug = BrowserBedienenTool(_Streikt())
    r = asyncio.run(werkzeug.execute({"aktion": "oeffnen", "ziel": "x.de"}))
    assert r.ok
    assert r.context.get("steuerung") is False
    assert "BROWSER-EINRICHTEN.bat" in r.output
