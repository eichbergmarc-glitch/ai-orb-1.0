"""Bei einer klaren Ansage liest/öffnet der Orb GARANTIERT die Seite.

Dasselbe Prinzip wie bei der erzwungenen Vorabsuche und dem erzwungenen
Bildschirm-Ansehen, nun ausgeweitet auf Browsersteuerung und
Webseite-Lesen. Der Benutzer nannte eine Adresse und bat, sie zu lesen -
und das Modell nannte 'webseite_lesen', ohne es zu rufen. Wo die
Entscheidung feststeht, gehört sie in den Ablauf. Diese Tests sichern die
Auslöser und die erzwungenen Aufrufe.
"""

from __future__ import annotations

import asyncio

from backend.orchestrator.orchestrator import (
    _url_aus,
    will_browser,
    will_webseite_lesen,
)


# --- Auslöser: Lesen -------------------------------------------------------


def test_lesebitten_mit_adresse_loesen_aus():
    ja = [
        "lies mir spiegel.de/politik vor",
        "worum geht es auf https://www.tagesschau.de/inland",
        "fasse den artikel auf zeit.de zusammen",
        "öffne wikipedia.de und lies mir den ersten absatz",
        "was steht auf regesta-imperii.de",
    ]
    for satz in ja:
        assert will_webseite_lesen(satz), f"sollte auslösen: {satz!r}"


def test_kein_fehlalarm_beim_lesen():
    nein = [
        "wie spät ist es",
        "ich war gestern um 20.30 uhr zuhause",   # Uhrzeit ist keine Adresse
        "erklär mir den investiturstreit",
        "spiegel.de",                              # Adresse ohne Leseabsicht
    ]
    for satz in nein:
        assert not will_webseite_lesen(satz), f"sollte NICHT auslösen: {satz!r}"


# --- Auslöser: Browser bedienen --------------------------------------------


def test_browserbedienung_loest_aus():
    ja = [
        "öffne den browser und melde mich bei github.com an",
        "geh im browser auf amazon.de und such nach einem buch",
        "klick auf der seite example.com auf anmelden",
        "scroll auf spiegel.de nach unten",
    ]
    for satz in ja:
        assert will_browser(satz), f"sollte auslösen: {satz!r}"


def test_reines_lesen_ist_keine_browserbedienung():
    # "lies mir x vor" ist Lesen, nicht Bedienen - sonst öffnete der Orb
    # unnötig ein echtes Browserfenster.
    assert will_webseite_lesen("lies mir spiegel.de vor")
    assert not will_browser("lies mir spiegel.de vor")


def test_url_erkennung():
    assert _url_aus("geh auf https://www.tagesschau.de/inland").startswith("https://")
    assert _url_aus("schau auf spiegel.de/politik") == "https://spiegel.de/politik"
    assert _url_aus("gegen 20.30 uhr") == ""
    assert _url_aus("das kostet u.a. viel") == ""


# --- Der erzwungene Aufruf -------------------------------------------------


class _FakeResult:
    def __init__(self, ok, output="", error=""):
        self.ok = ok
        self.output = output
        self.error = error


class _FakeRun:
    def __init__(self, result):
        self.result = result
        self.seconds = 0.1


class _FakeToolEngine:
    enabled = True

    def __init__(self, ergebnisse):
        # ergebnisse: dict aktion/name -> _FakeResult, oder ein einzelnes
        self._ergebnisse = ergebnisse
        self.aufrufe = []

    async def direkt_ausfuehren(self, name, arguments, *, actor="vorab"):
        self.aufrufe.append((name, dict(arguments)))
        if isinstance(self._ergebnisse, dict):
            schluessel = arguments.get("aktion", name)
            res = self._ergebnisse.get(schluessel) or self._ergebnisse.get(name)
        else:
            res = self._ergebnisse
        return _FakeRun(res or _FakeResult(False, error="nichts"))


def _orchestrator_mit(tool_engine):
    from backend.orchestrator.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)
    orch._tool_engine = tool_engine
    return orch


def test_vorab_webseite_ruft_das_werkzeug_und_reicht_den_text_durch():
    te = _FakeToolEngine(_FakeResult(True, output="Der Bundestag hat heute beschlossen …"))
    orch = _orchestrator_mit(te)

    block = asyncio.run(orch._vorab_webseite("https://tagesschau.de/inland"))

    assert te.aufrufe and te.aufrufe[0][0] == "webseite_lesen"
    assert te.aufrufe[0][1]["url"] == "https://tagesschau.de/inland"
    assert "Bundestag" in block
    assert "keine webseiten" in block.lower()  # weist die Ausrede ab


def test_vorab_webseite_meldet_fehler_ehrlich():
    te = _FakeToolEngine(_FakeResult(False, error="Die Seite meldete 404."))
    orch = _orchestrator_mit(te)
    block = asyncio.run(orch._vorab_webseite("https://example.com/weg"))
    assert "404" in block or "ging nicht" in block.lower()


def test_vorab_browser_oeffnet_und_listet_elemente():
    te = _FakeToolEngine({
        "oeffnen": _FakeResult(True, output="Geoeffnet: GitHub\nhttps://github.com"),
        "elemente": _FakeResult(True, output="1. [Feld] Suche\n2. [Knopf] Sign in"),
    })
    orch = _orchestrator_mit(te)

    block = asyncio.run(orch._vorab_browser("https://github.com"))

    aktionen = [a[1].get("aktion") for a in te.aufrufe]
    assert "oeffnen" in aktionen
    assert "elemente" in aktionen
    assert "Sign in" in block
    assert "geöffnet" in block.lower()
    assert "keinen browser" in block.lower()   # weist die Ausrede ab


def test_vorab_browser_meldet_fehler_wenn_oeffnen_scheitert():
    te = _FakeToolEngine({"oeffnen": _FakeResult(False, error="Playwright fehlt.")})
    orch = _orchestrator_mit(te)
    block = asyncio.run(orch._vorab_browser("https://github.com"))
    assert "playwright" in block.lower() or "ging nicht" in block.lower()
