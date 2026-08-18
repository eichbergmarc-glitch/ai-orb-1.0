"""Suchen, die nicht abgewiesen werden können.

Am 15.08.2026 stand im Protokoll des Benutzers fünfmal dasselbe: Mojeek 403,
Ecosia 403, DuckDuckGo Lite abgewiesen, DuckDuckGo HTML abgewiesen, Bing eine
Sperrseite von 1356 Zeichen. Fünf von fünf Suchmaschinen hielten den Orb für
einen Automaten - zu Recht.

Diese Tests sichern den Ausweg: Dienste, die von Programmen abgefragt werden
WOLLEN. Geprüft wird an nachgebauten Antworten mit den echten Feldnamen -
``articles[].seendate`` bei GDELT, ``query.search[].snippet`` bei Wikipedia,
``results[].display_name`` bei OpenAlex. Ein Test gegen den echten Dienst
würde dessen Verfügbarkeit prüfen und nicht diesen Code, und er ginge in
einer Umgebung ohne Netz gar nicht erst.

Der wichtigste Test steht ganz unten: dass die Suche die offenen Quellen
ZUERST fragt. Steht die Reihenfolge falsch herum, läuft der Orb weiter in
die fünf Sperren und dieser ganze Umbau war umsonst.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from pathlib import Path

from backend.research import offene_quellen as oq


# ---------------------------------------------------------------------------
#  Ein Dienst aus Papier, mit den echten Feldnamen
# ---------------------------------------------------------------------------


_GDELT_ANTWORT = {
    "articles": [
        {
            "url": "https://www.tagesschau.de/ausland/gipfel-102.html",
            "url_mobile": "",
            "title": "Gipfeltreffen in Genf beendet",
            "seendate": "20260815T143000Z",
            "socialimage": "https://x/y.jpg",
            "domain": "tagesschau.de",
            "language": "German",
            "sourcecountry": "Germany",
        },
        {
            "url": "https://www.bbc.com/news/world-123",
            "title": "Summit ends without agreement",
            "seendate": "20260815T120000Z",
            "domain": "bbc.com",
            "language": "English",
            "sourcecountry": "United Kingdom",
        },
        # Zweimal dieselbe Adresse - GDELT liefert das bei Syndikaten.
        {
            "url": "https://www.tagesschau.de/ausland/gipfel-102.html",
            "title": "Gipfeltreffen in Genf beendet",
            "seendate": "20260815T143000Z",
            "domain": "tagesschau.de",
        },
        {"url": "", "title": "Ohne Adresse", "seendate": ""},
    ]
}

_WIKIPEDIA_ANTWORT = {
    "query": {
        "search": [
            {
                "ns": 0,
                "title": "Julikrise",
                "pageid": 12345,
                "snippet": 'Die <span class="searchmatch">Julikrise</span> 1914 gilt als …',
            },
            {"ns": 0, "title": "Fritz Fischer (Historiker)", "pageid": 999,
             "snippet": "Kontroverse um die Kriegsschuld"},
        ]
    }
}

_OPENALEX_ANTWORT = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1000/xyz",
            "display_name": "Germany's Aims in the First World War",
            "publication_year": 1961,
            "primary_location": {
                "landing_page_url": "https://example.org/fischer",
                "source": {"display_name": "Historische Zeitschrift"},
            },
        }
    ]
}

_CROSSREF_ANTWORT = {
    "message": {
        "items": [
            {
                "title": ["Der Griff nach der Weltmacht"],
                "URL": "https://doi.org/10.1000/abc",
                "container-title": ["Historische Zeitschrift"],
                "issued": {"date-parts": [[1961, 5]]},
            }
        ]
    }
}

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>tagesschau</title>
  <item>
    <title>Bundestag beschliesst Haushalt</title>
    <link>https://www.tagesschau.de/inland/haushalt-1.html</link>
    <description>Nach langer Debatte &amp; knapper Mehrheit.</description>
    <pubDate>Sat, 15 Aug 2026 14:00:00 +0200</pubDate>
  </item>
  <item>
    <title>Wetter bleibt wechselhaft</title>
    <link>https://www.tagesschau.de/wetter-2.html</link>
    <description>Schauer im Norden.</description>
  </item>
</channel></rss>"""

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Ein Atom-Beitrag</title>
    <link href="https://example.org/atom-1"/>
    <summary>Kurz zusammengefasst.</summary>
    <updated>2026-08-15T12:00:00Z</updated>
  </entry>
</feed>"""

_GOOGLE_ANTWORT = {
    "items": [
        {
            "title": "Julikrise 1914",
            "link": "https://example.org/julikrise",
            "snippet": "Der Weg in den Krieg",
            "displayLink": "example.org",
        }
    ]
}


class _Dienst:
    """Bildet GDELT, Wikipedia, OpenAlex, Crossref, Google und RSS nach."""

    def __init__(self):
        self.pfade: list[str] = []
        self.kennungen: list[str] = []
        self.kaputt: set[str] = set()
        gegenstand = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _senden(self, koerper: bytes, typ="application/json", code=200):
                self.send_response(code)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Length", str(len(koerper)))
                self.end_headers()
                self.wfile.write(koerper)

            def do_GET(self):
                gegenstand.pfade.append(self.path)
                gegenstand.kennungen.append(self.headers.get("User-Agent", ""))
                weg = urlparse(self.path).path

                if weg.lstrip("/").split("/")[0] in gegenstand.kaputt:
                    self._senden(b"nein", "text/plain", 503)
                    return

                if weg.startswith("/gdelt"):
                    frage = parse_qs(urlparse(self.path).query)
                    if "kaputtesjson" in frage.get("query", [""])[0].replace(" ", ""):
                        # So antwortet GDELT wirklich, wenn die Anfrage
                        # unbrauchbar ist: HTTP 200 und ein Satz Klartext.
                        self._senden(b"Your query was too short.", "text/html")
                        return
                    self._senden(json.dumps(_GDELT_ANTWORT).encode())
                    return
                if weg.startswith("/wikipedia"):
                    self._senden(json.dumps(_WIKIPEDIA_ANTWORT).encode())
                    return
                if weg.startswith("/openalex"):
                    self._senden(json.dumps(_OPENALEX_ANTWORT).encode())
                    return
                if weg.startswith("/crossref"):
                    self._senden(json.dumps(_CROSSREF_ANTWORT).encode())
                    return
                if weg.startswith("/google"):
                    self._senden(json.dumps(_GOOGLE_ANTWORT).encode())
                    return
                if weg.startswith("/rss"):
                    self._senden(_RSS.encode(), "application/rss+xml")
                    return
                if weg.startswith("/atom"):
                    self._senden(_ATOM.encode(), "application/atom+xml")
                    return
                self._senden(b"?", "text/plain", 404)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def adresse(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def schliessen(self):
        self._server.shutdown()


@pytest.fixture(autouse=True)
def _frischer_zustand():
    """Setzt Anfragetakt und Kurzgedächtnis vor jedem Test zurück.

    Beides ist bewusst modulweit - der Takt gilt für den ganzen Orb, nicht
    je Aufruf. In Tests führt genau das dazu, dass der zweite Test von der
    Bremse des ersten ausgebremst wird.
    """

    oq._gdelt_zuletzt = 0.0
    oq._gdelt_pause_bis = 0.0
    oq._speicher.clear()
    yield


@pytest.fixture
def dienst(monkeypatch):
    laufend = _Dienst()
    monkeypatch.setattr(oq, "_GDELT", f"{laufend.adresse}/gdelt")
    monkeypatch.setattr(oq, "_WIKIPEDIA", laufend.adresse + "/wikipedia/{sprache}")
    monkeypatch.setattr(oq, "_OPENALEX", f"{laufend.adresse}/openalex")
    monkeypatch.setattr(oq, "_CROSSREF", f"{laufend.adresse}/crossref")
    monkeypatch.setattr(oq, "_GOOGLE_CSE", f"{laufend.adresse}/google")
    monkeypatch.delenv("GOOGLE_CSE_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_ID", raising=False)
    yield laufend
    laufend.schliessen()


# ---------------------------------------------------------------------------
#  Die einzelnen Quellen
# ---------------------------------------------------------------------------


def test_gdelt_liest_die_echten_feldnamen(dienst):
    treffer = oq.gdelt_suchen("Gipfel Genf", limit=5)
    assert len(treffer) == 2, "die doppelte Adresse muss wegfallen"
    assert treffer[0]["titel"] == "Gipfeltreffen in Genf beendet"
    assert treffer[0]["url"].startswith("https://www.tagesschau.de/")
    # Aus 20260815T143000Z muss ein lesbares Datum werden - niemand hoert
    # sich einen Zeitstempel an.
    assert "15.08.2026" in treffer[0]["beschreibung"]
    assert "tagesschau.de" in treffer[0]["beschreibung"]


def test_gdelt_nimmt_sprache_und_domain_entgegen(dienst):
    oq.gdelt_suchen("Haushalt", sprache="german", domain="tagesschau.de")
    frage = parse_qs(urlparse(dienst.pfade[-1]).query)["query"][0]
    assert "sourcelang:german" in frage
    assert "domain:tagesschau.de" in frage


def test_gdelt_klartext_statt_json_ergibt_einen_lesbaren_fehler(dienst):
    # Ohne diesen Zweig saehe eine unbrauchbare Anfrage wie ein Netzfehler
    # aus, und man suchte an der voellig falschen Stelle.
    with pytest.raises(oq.OffeneQuelleFehler, match="kein JSON"):
        oq.gdelt_suchen("kaputtes json")


def test_wikipedia_baut_adresse_und_entfernt_die_treffermarkierung(dienst):
    treffer = oq.wikipedia_suchen("Julikrise", limit=2)
    assert treffer[0]["url"] == "https://de.wikipedia.org/wiki/Julikrise"
    # Das <span class="searchmatch"> darf nicht im gesprochenen Text landen.
    assert "<span" not in treffer[0]["beschreibung"]
    assert "Julikrise" in treffer[0]["beschreibung"]
    # Klammern und Leerzeichen im Titel muessen kodiert werden.
    assert treffer[1]["url"].endswith("Fritz_Fischer_%28Historiker%29")


def test_openalex_nimmt_display_name_und_landeseite(dienst):
    treffer = oq.openalex_suchen("Fischer Kriegsziele")
    assert treffer[0]["titel"] == "Germany's Aims in the First World War"
    assert treffer[0]["url"] == "https://example.org/fischer"
    assert "Historische Zeitschrift" in treffer[0]["beschreibung"]
    assert "1961" in treffer[0]["beschreibung"]


def test_crossref_liest_titel_zeitschrift_und_jahr(dienst):
    treffer = oq.crossref_suchen("Griff nach der Weltmacht")
    assert treffer[0]["titel"] == "Der Griff nach der Weltmacht"
    assert treffer[0]["url"] == "https://doi.org/10.1000/abc"
    assert "1961" in treffer[0]["beschreibung"]


def test_rss_liest_eine_zeitung_direkt(dienst):
    treffer = oq.rss_lesen(f"{dienst.adresse}/rss")
    assert len(treffer) == 2
    assert treffer[0]["titel"] == "Bundestag beschliesst Haushalt"
    assert "&" in treffer[0]["beschreibung"], "Entities muessen aufgeloest sein"
    assert "2026" in treffer[0]["beschreibung"]


def test_rss_laesst_sich_auf_ein_thema_eingrenzen(dienst):
    treffer = oq.rss_lesen(f"{dienst.adresse}/rss", filter_text="Haushalt Bundestag")
    assert len(treffer) == 1 and "Haushalt" in treffer[0]["titel"]


def test_auch_atom_feeds_werden_gelesen(dienst):
    treffer = oq.rss_lesen(f"{dienst.adresse}/atom")
    assert treffer and treffer[0]["url"] == "https://example.org/atom-1"


def test_ohne_schluessel_wird_google_gar_nicht_erst_gefragt(dienst):
    assert not oq.google_verfuegbar()
    with pytest.raises(oq.OffeneQuelleFehler, match="kein Google-Schluessel"):
        oq.google_suchen("egal")
    assert not any("/google" in p for p in dienst.pfade)


def test_mit_schluessel_sucht_google_ueber_den_vorgesehenen_weg(dienst, monkeypatch):
    monkeypatch.setenv("GOOGLE_CSE_KEY", "k123")
    monkeypatch.setenv("GOOGLE_CSE_ID", "cx456")
    treffer = oq.google_suchen("Julikrise", limit=3)
    assert treffer[0]["url"] == "https://example.org/julikrise"
    frage = parse_qs(urlparse(dienst.pfade[-1]).query)
    assert frage["key"] == ["k123"] and frage["cx"] == ["cx456"]


def test_die_kennung_ist_ehrlich_und_nicht_getarnt(dienst):
    # Der ganze Umbau beruht darauf, sich NICHT als Browser auszugeben.
    # Wikimedia weist Zugriffe ohne sprechende Kennung ausdruecklich ab.
    oq.wikipedia_suchen("Test")
    kennung = dienst.kennungen[-1]
    assert "AI-Orb" in kennung
    assert "Mozilla" not in kennung and "Chrome" not in kennung


# ---------------------------------------------------------------------------
#  Die Wahl der Quelle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "frage, art",
    [
        ("Was gibt es Neues aus Berlin?", "nachricht"),
        ("aktuelle Lage in Genf", "nachricht"),
        ("Wie ist der Forschungsstand zur Julikrise?", "wissenschaft"),
        ("Gibt es neuere Studien zu Fritz Fischer?", "wissenschaft"),
        ("Wer war Otto von Bismarck?", "sache"),
        ("Wie funktioniert ein Dieselmotor?", "sache"),
    ],
)
def test_die_art_der_frage_bestimmt_die_quelle(frage, art):
    assert oq._art_der_frage(frage) == art


def test_ein_site_vorwort_wird_abgetrennt():
    domain, rest = oq._domain_aus("site:tagesschau.de Bundestag Haushalt")
    assert domain == "tagesschau.de"
    assert "site:" not in rest and "Bundestag" in rest


def test_eine_sachfrage_geht_zuerst_an_wikipedia(dienst):
    treffer, benutzt = oq.offene_suche("Wer war Otto von Bismarck?", limit=3)
    assert treffer and benutzt[0] == "Wikipedia"


def test_eine_nachrichtenfrage_geht_zuerst_an_gdelt(dienst):
    treffer, benutzt = oq.offene_suche("Was gibt es Neues aus Genf?", limit=3)
    assert treffer and benutzt[0] == "GDELT"


def test_eine_literaturfrage_geht_zuerst_an_openalex(dienst):
    treffer, benutzt = oq.offene_suche("Forschungsstand zur Julikrise", limit=3)
    assert treffer and benutzt[0] == "OpenAlex"


def test_eine_site_suche_braucht_keine_suchmaschine(dienst):
    # Genau der Fall aus dem Protokoll: Der Orb suchte 'site:tagesschau.de'
    # ueber Bing und wurde abgewiesen. GDELT kennt den Domainfilter selbst.
    treffer, benutzt = oq.offene_suche("site:tagesschau.de Gipfel", limit=3)
    assert treffer and benutzt == ["GDELT"]
    assert "domain%3Atagesschau.de" in dienst.pfade[-1] or "domain:tagesschau.de" in dienst.pfade[-1]


def test_dieselbe_adresse_kommt_nur_einmal(dienst):
    treffer, _ = oq.offene_suche("Gipfel Genf aktuell", limit=10)
    adressen = [t["url"].rstrip("/").lower() for t in treffer]
    assert len(adressen) == len(set(adressen))


def test_eine_ausgefallene_quelle_reisst_die_anderen_nicht_mit(dienst):
    dienst.kaputt.add("gdelt")
    treffer, benutzt = oq.offene_suche("Was gibt es Neues aus Genf?", limit=5)
    # GDELT faellt aus, Wikipedia traegt trotzdem etwas bei.
    assert treffer, "es muss trotzdem etwas herauskommen"
    assert "GDELT" not in benutzt


def test_faellt_alles_aus_kommt_eine_leere_liste_kein_absturz(dienst):
    dienst.kaputt.update({"gdelt", "wikipedia", "openalex", "crossref"})
    treffer, benutzt = oq.offene_suche("irgendetwas", limit=5)
    assert treffer == [] and benutzt == []


def test_eine_leere_anfrage_ruft_niemanden(dienst):
    assert oq.offene_suche("   ", limit=5) == ([], [])
    assert dienst.pfade == []


# ---------------------------------------------------------------------------
#  Der Anschluss an die Suche des Orbs
# ---------------------------------------------------------------------------


def test_die_suche_fragt_die_offenen_quellen_ZUERST(monkeypatch):
    """Der wichtigste Test dieser Datei.

    Steht die Reihenfolge falsch herum, laeuft der Orb weiter zuerst in die
    fuenf Sperren - und dieser ganze Umbau waere umsonst gewesen.
    """

    from backend.tools import web_tools

    gerufen: list[str] = []

    def _offene(query, *, limit=6):
        gerufen.append("offen")
        return ([{"titel": "Treffer", "url": "https://example.org/x",
                  "beschreibung": "aus einer offenen Quelle"}], ["Wikipedia"])

    def _maschine(*args, **kwargs):
        gerufen.append("suchmaschine")
        raise AssertionError("die Suchmaschinen duerfen gar nicht drankommen")

    monkeypatch.setattr("backend.research.offene_quellen.offene_suche", _offene)
    monkeypatch.setattr(web_tools, "_einmal_suchen", _maschine)

    treffer = web_tools.search_web("Wer war Bismarck?", limit=3)
    assert treffer and treffer[0]["url"] == "https://example.org/x"
    assert gerufen == ["offen"]


def test_finden_die_offenen_quellen_nichts_kommt_der_fehler_SCHNELL(monkeypatch):
    # Stufe 3 der Bestandsaufnahme: Die fuenf Trefferseiten-Maschinen haben
    # seit dem 15.08. keinen einzigen Treffer geliefert, aber jede leere
    # Suche um zehn und mehr Sekunden verlaengert. Sie sind abgeschaltet -
    # eine leere Suche scheitert jetzt ehrlich und sofort.
    import time as _t

    from backend.tools import web_tools

    monkeypatch.setattr(
        "backend.research.offene_quellen.offene_suche",
        lambda query, *, limit=6: ([], []),
    )

    def _verboten(maschine, query, limit):
        raise AssertionError("die abgeschalteten Maschinen duerfen nicht laufen")

    monkeypatch.setattr(web_tools, "_einmal_suchen", _verboten)

    begonnen = _t.monotonic()
    with pytest.raises(web_tools._Suchfehler, match="SUCHE-PRUEFEN"):
        web_tools.search_web("Otto von Bismarck", limit=3)
    assert _t.monotonic() - begonnen < 3.0, "der Fehlschlag muss schnell sein"


def test_der_diagnoseschalter_holt_die_altmaschinen_zurueck(monkeypatch):
    # Abgeschaltet heisst nicht abgerissen: Fuer die Fehlersuche laesst
    # sich die alte Kette gezielt wieder einschalten.
    from backend.tools import web_tools

    monkeypatch.setattr(
        "backend.research.offene_quellen.offene_suche",
        lambda query, *, limit=6: ([], []),
    )
    monkeypatch.setattr(web_tools, "ALTMASCHINEN_AKTIV", True)
    monkeypatch.setattr(
        web_tools, "_einmal_suchen",
        lambda m, q, l: [{"titel": "Alter Weg", "url": "https://example.org/alt",
                          "beschreibung": "Bismarck Otto von"}],
    )
    treffer = web_tools.search_web("Otto von Bismarck", limit=3)
    assert treffer[0]["url"] == "https://example.org/alt"


def test_ein_fehler_in_den_offenen_quellen_ergibt_einen_klaren_fehler(monkeypatch):
    # Stuerzen die offenen Quellen ab (ein Programmfehler, kein Netzproblem),
    # soll die Suche nicht heimlich in eine tote Kette weiterlaufen, sondern
    # den Fehler benennen.
    from backend.tools import web_tools

    def _kaputt(query, *, limit=6):
        raise RuntimeError("etwas ganz Unerwartetes")

    monkeypatch.setattr("backend.research.offene_quellen.offene_suche", _kaputt)
    with pytest.raises(web_tools._Suchfehler):
        web_tools.search_web("Otto von Bismarck", limit=3)


# ---------------------------------------------------------------------------
#  Tempo
# ---------------------------------------------------------------------------
#
# Die Messung vom 16.08.2026 war eindeutig: Die Zeit bis zur ersten Frage
# ans Sprachmodell stieg von 6,2 auf 22,5 Sekunden im Median, im
# schlimmsten Fall auf 77. Nicht das Modell war langsam - die Suche davor
# war es, weil sie ihre Quellen NACHEINANDER fragte und jeder fünfzehn
# Sekunden Geduld schenkte. Diese Tests halten das Gegenteil fest.


import time as _zeit


def _langsame_quelle(sekunden: float, treffer: list | None = None):
    def _tun():
        _zeit.sleep(sekunden)
        return treffer if treffer is not None else [
            {"titel": "spät", "url": f"https://example.org/{sekunden}", "beschreibung": ""}
        ]
    return _tun


def test_die_quellen_werden_gleichzeitig_gefragt_nicht_nacheinander(monkeypatch):
    # Drei Quellen zu je 0,6 Sekunden. Nacheinander wären das 1,8 - und
    # genau diese Addition hat den Orb langsam gemacht.
    monkeypatch.setattr(oq, "wikipedia_suchen", lambda *a, **k: _langsame_quelle(0.6)())
    monkeypatch.setattr(oq, "openalex_suchen", lambda *a, **k: _langsame_quelle(0.6)())
    oq._speicher.clear()

    begonnen = _zeit.monotonic()
    treffer, _ = oq.offene_suche("Wer war Otto von Bismarck?", limit=6)
    gedauert = _zeit.monotonic() - begonnen

    assert treffer
    assert gedauert < 1.3, f"lief nacheinander statt gleichzeitig ({gedauert:.2f} s)"


def test_eine_haengende_quelle_haelt_die_antwort_nicht_auf(monkeypatch):
    monkeypatch.setattr(oq, "_GESAMTBUDGET", 1.0)
    monkeypatch.setattr(oq, "wikipedia_suchen", lambda *a, **k: _langsame_quelle(30)())
    monkeypatch.setattr(
        oq, "openalex_suchen",
        lambda *a, **k: [{"titel": "schnell", "url": "https://example.org/s",
                          "beschreibung": ""}],
    )
    oq._speicher.clear()

    begonnen = _zeit.monotonic()
    treffer, benutzt = oq.offene_suche("Wer war Otto von Bismarck?", limit=6)
    gedauert = _zeit.monotonic() - begonnen

    assert gedauert < 3.0, f"das Zeitbudget wurde nicht eingehalten ({gedauert:.2f} s)"
    assert treffer and benutzt == ["OpenAlex"], "das Schnelle muss trotzdem ankommen"


def test_die_rangfolge_bleibt_erhalten_auch_wenn_das_langsamere_besser_ist(monkeypatch):
    # Gleichzeitig fragen heisst nicht: wer zuerst kommt, steht vorn. Sonst
    # entschiede die Tagesform des Netzes ueber die Reihenfolge der Quellen.
    monkeypatch.setattr(
        oq, "wikipedia_suchen",
        lambda *a, **k: _langsame_quelle(
            0.5, [{"titel": "Wikipedia", "url": "https://example.org/w", "beschreibung": ""}]
        )(),
    )
    monkeypatch.setattr(
        oq, "openalex_suchen",
        lambda *a, **k: [{"titel": "OpenAlex", "url": "https://example.org/o",
                          "beschreibung": ""}],
    )
    oq._speicher.clear()
    treffer, benutzt = oq.offene_suche("Wer war Otto von Bismarck?", limit=6)
    assert treffer[0]["titel"] == "Wikipedia"
    assert benutzt[0] == "Wikipedia"


def test_dieselbe_frage_wird_kein_zweites_mal_bezahlt(monkeypatch):
    rufe = []

    def _zaehlen(*a, **k):
        rufe.append(1)
        return [{"titel": "x", "url": "https://example.org/x", "beschreibung": ""}]

    monkeypatch.setattr(oq, "wikipedia_suchen", _zaehlen)
    monkeypatch.setattr(oq, "openalex_suchen", lambda *a, **k: [])
    oq._speicher.clear()

    oq.offene_suche("Wer war Otto von Bismarck?", limit=3)
    vorher = len(rufe)
    oq.offene_suche("Wer war Otto von Bismarck?", limit=3)
    assert len(rufe) == vorher, "die zweite gleiche Frage muss aus dem Gedächtnis kommen"


def test_gdelt_wird_hoechstens_einmal_je_frage_gerufen(monkeypatch):
    rufe = []
    monkeypatch.setattr(
        oq, "gdelt_suchen",
        lambda *a, **k: (rufe.append(k), [
            {"titel": "n", "url": "https://example.org/n", "beschreibung": ""}
        ])[1],
    )
    monkeypatch.setattr(oq, "wikipedia_suchen", lambda *a, **k: [])
    oq._speicher.clear()
    oq.offene_suche("Was gibt es Neues aus Genf?", limit=6)
    assert len(rufe) == 1, "zwei GDELT-Anfragen kosten die halbe Sperrfrist umsonst"


def test_eine_sachfrage_ruft_gdelt_gar_nicht(monkeypatch):
    rufe = []
    monkeypatch.setattr(oq, "gdelt_suchen", lambda *a, **k: rufe.append(1) or [])
    monkeypatch.setattr(oq, "wikipedia_suchen", lambda *a, **k: [])
    monkeypatch.setattr(oq, "openalex_suchen", lambda *a, **k: [])
    oq._speicher.clear()
    oq.offene_suche("Wer war Otto von Bismarck?", limit=6)
    assert rufe == [], "zu einer Sachfrage liefert eine Nachrichtensuche nur Rauschen"


# --- Die Eigenheiten von GDELT --------------------------------------------


@pytest.mark.parametrize(
    "gesagt, erwartet_ohne",
    [
        ("Oral-History-Berichten", "-"),
        ('Suche nach "Zitat" und (Klammer)', '"'),
        ("F-16 Lieferung", "-"),
    ],
)
def test_bindestriche_und_zeichen_die_gdelt_ablehnt_fliegen_raus(gesagt, erwartet_ohne):
    # GDELT antwortet darauf im Klartext: "One or more of your keywords
    # contained an illegal character." Im Protokoll stand genau das.
    sauber = oq._gdelt_begriffe(gesagt)
    assert erwartet_ohne not in sauber
    assert sauber.strip()


def test_zu_kurze_woerter_fliegen_aus_der_gdelt_anfrage():
    assert oq._gdelt_begriffe("Wer ist es in DE") == "Wer ist"


def test_nach_einem_429_wird_gdelt_eine_weile_in_ruhe_gelassen(dienst, monkeypatch):
    # Weiter gegen eine geschlossene Tuer zu laufen kostet nur Zeit, die
    # der Benutzer als Wartezeit erlebt.
    monkeypatch.setattr(oq, "_gdelt_pause_bis", 0.0)
    monkeypatch.setattr(oq, "_gdelt_zuletzt", 0.0)
    dienst.kaputt.add("gdelt")
    with pytest.raises(oq.OffeneQuelleFehler):
        oq.gdelt_suchen("Bundestag")

    monkeypatch.setattr(oq, "_gdelt_pause_bis", _zeit.monotonic() + 60)
    vorher = len(dienst.pfade)
    with pytest.raises(oq.OffeneQuelleFehler, match="gesperrt"):
        oq.gdelt_suchen("Bundestag")
    assert len(dienst.pfade) == vorher, "in der Pause darf gar nicht erst gefragt werden"


def test_der_anfragetakt_von_gdelt_wird_eingehalten(monkeypatch):
    monkeypatch.setattr(oq, "_gdelt_pause_bis", 0.0)
    monkeypatch.setattr(oq, "_gdelt_zuletzt", _zeit.monotonic())
    # Direkt nach einer Anfrage ist der naechste Platz erst in gut fuenf
    # Sekunden frei - mit einem Budget von einer halben Sekunde also nicht.
    assert oq._gdelt_slot(0.5) is False


def test_eine_nachrichtenrunde_wartet_nicht_sechsmal_die_sperrfrist_ab(monkeypatch):
    # Sechs Quellen auf einmal, jede mit einer GDELT-Anfrage: Wuerde jede
    # die volle Sperrfrist abwarten, dauerte allein das eine halbe Minute.
    monkeypatch.setattr(oq, "_gdelt_pause_bis", 0.0)
    monkeypatch.setattr(oq, "_gdelt_zuletzt", _zeit.monotonic())
    begonnen = _zeit.monotonic()
    frei = oq._gdelt_slot(oq._GDELT_WARTEN)
    gewartet = _zeit.monotonic() - begonnen
    assert frei is False
    assert gewartet < 2.5, f"zu lange auf GDELT gewartet ({gewartet:.2f} s)"


# ---------------------------------------------------------------------------
#  Schlagzeilen direkt von den Zeitungen
# ---------------------------------------------------------------------------
#
# Am 16.08. um 21:26 zeigte das Protokoll, wie die Nachrichtensuche an
# GDELT allein zugrunde ging: Taktsperre, SSL-Timeout, Rueckfall in fuenf
# gesperrte Suchmaschinen. Feeds kennen das alles nicht - sie sind zum
# Abholen gebaut. Diese Tests halten fest, dass Nachrichten jetzt zuerst
# dort geholt werden.


def test_fuellwoerter_benennen_kein_thema():
    assert oq._inhaltsworte("Was gibt es Neues aus aller Welt?") == []
    assert oq._inhaltsworte("Erzähl mir die aktuellen Nachrichten") == []
    assert oq._inhaltsworte("Was gibt es Neues zum Haushalt im Bundestag?") == [
        "haushalt", "bundestag",
    ]


def test_schlagzeilen_ohne_thema_sind_die_titelseite(dienst):
    feeds = (("tagesschau (DE)", f"{dienst.adresse}/rss"),)
    treffer = oq.schlagzeilen_suchen("Was gibt es Neues?", limit=5, feeds=feeds)
    assert len(treffer) == 2, "ohne Thema zaehlt die Titelseite selbst"
    assert treffer[0]["beschreibung"].startswith("tagesschau (DE):")


def test_schlagzeilen_mit_thema_werden_gefiltert(dienst):
    feeds = (("tagesschau (DE)", f"{dienst.adresse}/rss"),)
    treffer = oq.schlagzeilen_suchen("Neues zum Haushalt?", limit=5, feeds=feeds)
    assert len(treffer) == 1
    assert "Haushalt" in treffer[0]["titel"]


def test_schlagzeilen_mischen_die_haeuser_reihum(dienst):
    # Sonst besteht die ganze Liste aus dem ersten Haus, und der Grund fuer
    # mehrere Feeds - die Vielfalt - waere wieder weg.
    feeds = (
        ("A", f"{dienst.adresse}/rss"),
        ("B", f"{dienst.adresse}/rss"),
    )
    treffer = oq.schlagzeilen_suchen("Was gibt es Neues?", limit=4, feeds=feeds)
    haeuser = [t["beschreibung"].split(":")[0] for t in treffer]
    assert haeuser[:2] in (["A", "B"], ["B", "A"]), f"nicht gemischt: {haeuser}"


def test_ein_toter_feed_reisst_die_anderen_nicht_mit(dienst):
    feeds = (
        ("Tot", "http://127.0.0.1:9/rss"),
        ("Lebt", f"{dienst.adresse}/rss"),
    )
    treffer = oq.schlagzeilen_suchen("Was gibt es Neues?", limit=4, feeds=feeds)
    assert treffer and all(t["beschreibung"].startswith("Lebt:") for t in treffer)


def test_eine_nachrichtenfrage_geht_zuerst_an_die_schlagzeilen(dienst, monkeypatch):
    monkeypatch.setattr(
        oq, "schlagzeilen_suchen",
        lambda *a, **k: [{"titel": "Schlagzeile", "url": "https://example.org/s",
                          "beschreibung": "tagesschau (DE)"}],
    )
    treffer, benutzt = oq.offene_suche("Was gibt es Neues aus Genf?", limit=3)
    assert benutzt[0] == "Schlagzeilen"
    assert treffer[0]["titel"] == "Schlagzeile"


def test_die_nachrichtenrunde_liest_den_feed_statt_der_suchmaschine(dienst, monkeypatch):
    # DER Fehlerfall vom 16.08.: sechs site:-Suchen liefen gleichzeitig in
    # Taktsperre und 403. Mit Feed darf search_web gar nicht drankommen.
    import asyncio

    from backend.tools import web_tools

    def _verboten(*a, **k):
        raise AssertionError("search_web darf bei einem Feed nicht gerufen werden")

    monkeypatch.setattr(web_tools, "search_web", _verboten)
    gesammelt = asyncio.run(web_tools.mehrquellensuche(
        "Haushalt",
        [{"name": "tagesschau (DE)", "einschraenkung": "site:tagesschau.de",
          "feed": f"{dienst.adresse}/rss"}],
        je_quelle=3,
    ))
    assert "tagesschau (DE)" in gesammelt
    assert "Haushalt" in gesammelt["tagesschau (DE)"][0]["titel"]


def test_ohne_feed_bleibt_die_nachrichtenrunde_beim_alten_weg(monkeypatch):
    import asyncio

    from backend.tools import web_tools

    monkeypatch.setattr(
        web_tools, "search_web",
        lambda anfrage, *, limit=6: [{"titel": "Alt", "url": "https://example.org/a",
                                      "beschreibung": ""}],
    )
    gesammelt = asyncio.run(web_tools.mehrquellensuche(
        "Haushalt",
        [{"name": "Reuters", "einschraenkung": "site:reuters.com"}],
        je_quelle=3,
    ))
    assert gesammelt["Reuters"][0]["titel"] == "Alt"


# ---------------------------------------------------------------------------
#  Gegen das Erfinden (17.08.2026)
# ---------------------------------------------------------------------------
#
# Der Orb hat Nachrichten erfunden. Der Weg dorthin stand im Protokoll:
# "Ja, bitte suche gezielt danach" wurde woertlich gesucht ('gezielt
# danach', fuenf beliebige Wikipedia-Treffer als frische Ergebnisse
# vorgelegt), und die Feeds trugen nichts bei, weil deutsche Suchwoerter
# englische Schlagzeilen auf null filtern. Ein Modell, dem man Zufall oder
# Leere als frische Suche vorlegt, erfindet den Rest.


def test_verweiswoerter_benennen_kein_thema():
    # Diese Saetze zeigen auf ein Thema, sie benennen keins.
    assert oq._inhaltsworte("Ja, bitte suche gezielt danach") == []
    assert oq._inhaltsworte("Such genauer danach") == []
    assert oq._inhaltsworte("Erzähl mir mehr dazu") == []
    # Ein echtes Thema bleibt erhalten.
    assert oq._inhaltsworte("Suche gezielt nach Nahost") == ["nahost"]


def test_neuigkeiten_zu_etwas_ist_eine_nachrichtenfrage():
    # Am 17.08. lief das als Sachfrage zu OpenAlex - Fachaufsaetze statt
    # Meldungen, dem Modell als Antwortgrundlage vorgelegt.
    assert oq._art_der_frage("Neuigkeiten zu neuen AI-Modellen") == "nachricht"


def test_filtert_das_thema_alles_weg_kommen_die_echten_schlagzeilen(dienst):
    # Deutsch gefragt, englisch getitelt: "Nahen Osten" findet "Middle
    # East" nie. Dann lieber die echten obersten Schlagzeilen als gar
    # nichts - aus nichts erfindet ein Modell etwas.
    feeds = (("BBC (UK)", f"{dienst.adresse}/rss"),)
    treffer = oq.schlagzeilen_suchen(
        "Was gibt es Neues aus dem Nahen Osten?", limit=4, feeds=feeds
    )
    assert treffer, "die Titelseite muss als Rueckhalt kommen"
    assert all(t["beschreibung"].startswith("BBC (UK):") for t in treffer)


def test_auch_die_nachrichtenrunde_faellt_auf_die_titelseite_zurueck(dienst, monkeypatch):
    import asyncio

    from backend.tools import web_tools

    def _verboten(*a, **k):
        raise AssertionError("die Suchmaschinen waeren nur die fuenf Abweisungen")

    monkeypatch.setattr(web_tools, "search_web", _verboten)
    gesammelt = asyncio.run(web_tools.mehrquellensuche(
        "Lage im Nahen Osten",
        [{"name": "BBC (UK)", "einschraenkung": "site:bbc.com",
          "feed": f"{dienst.adresse}/rss"}],
        je_quelle=3,
    ))
    eintraege = gesammelt.get("BBC (UK)", [])
    assert eintraege, "die Titelseite muss kommen, nicht die Suchmaschinen"
    # Und sie muss als ungefiltert gekennzeichnet sein - das Modell soll
    # wissen, dass dies die Titelseite ist, nicht die Antwort aufs Suchwort.
    assert eintraege[0]["beschreibung"].startswith("[Titelseite")


# ---------------------------------------------------------------------------
#  Stufe 2: Handeln statt reden - der Wissensauftrag (Bestandsaufnahme S2)
# ---------------------------------------------------------------------------
#
# Belegt am 17.08.2026, 21:36: "Suche nach Markus Gabriel und eigne dir
# sein Wissen an." Das Werkzeug existierte, das Modell nannte es - und rief
# es nicht. Auf "ja, mach das" stritt es den Auftrag ab. Jetzt nimmt der
# Ablauf den Auftrag selbst an, wie bei Suche und Bildschirm.


@pytest.mark.parametrize(
    "satz, thema",
    [
        ("Suche einmal nach dem Philosophen Markus Gabriel und eigne dir sein Wissen an",
         "Philosophen Markus Gabriel"),
        ("Merke dir das Wissen über die Julikrise", "Julikrise"),
        ("Arbeite dich in die Quantenmechanik ein", "Quantenmechanik"),
        ("Lerne alles über Fritz Fischer", "Fritz Fischer"),
        ("Eigne dir Grundwissen zum Dreissigjaehrigen Krieg an", "Dreissigjaehrigen Krieg"),
    ],
)
def test_wissensauftraege_werden_erkannt_und_das_thema_gezogen(satz, thema):
    from backend.orchestrator.orchestrator import will_wissensauftrag, wissensthema_aus

    assert will_wissensauftrag(satz)
    assert wissensthema_aus(satz) == thema


@pytest.mark.parametrize(
    "satz",
    [
        "Wer war Otto von Bismarck?",
        "Merke dir diesen Termin am Freitag",
        "Trag mir morgen den Zahnarzt ein",
        "Was gibt es Neues aus Berlin?",
        "Merk dir, dass ich Kaffee ohne Zucker trinke",
    ],
)
def test_kein_wissensauftrag_bei_gewoehnlichen_saetzen(satz):
    # Die Kehrseite: "Merk dir diesen Termin" ist ein Kalendereintrag und
    # "merk dir, dass ich..." eine Notiz - keine stundenlange Einarbeitung.
    from backend.orchestrator.orchestrator import will_wissensauftrag

    assert not will_wissensauftrag(satz)


def test_der_wissensauftrag_startet_das_werkzeug_selbst():
    # Der Kern von Stufe 2: kein Hoffen auf das Modell. Der Ablauf ruft
    # wissen_aneignen im Hintergrund und sagt dem Modell, dass es laeuft.
    import asyncio

    from backend.orchestrator.orchestrator import Orchestrator

    rufe = []

    class _Lauf:
        class result:
            ok = True
            error = ""
        seconds = 0.1

    class _Engine:
        async def direkt_ausfuehren(self, name, argumente):
            rufe.append((name, argumente))
            return _Lauf()

    orch = Orchestrator.__new__(Orchestrator)
    orch._tool_engine = _Engine()

    async def _lauf():
        zusage = await orch._vorab_wissen(
            "Lerne alles über Fritz Fischer"
        )
        # Die Hintergrundaufgabe zu Ende laufen lassen.
        for auftrag in list(getattr(orch, "_wissensauftraege", [])):
            await auftrag
        return zusage

    zusage = asyncio.run(_lauf())

    assert rufe == [("wissen_aneignen", {"thema": "Fritz Fischer", "max_quellen": 3})]
    assert "WISSENSAUFTRAG ANGENOMMEN" in zusage
    assert "NICHT" in zusage, "die Zusage muss dem Modell das Doppelstarten verbieten"


def test_der_wissensauftrag_ist_im_ablauf_verdrahtet():
    # Erkennung und Werkzeuglauf nuetzen nichts, wenn die Weiche im
    # handle() fehlt - genau da ist die Suche frueher einmal verhungert.
    quelle = Path("backend/orchestrator/orchestrator.py").read_text(encoding="utf-8")
    anker = quelle.index("will_wissensauftrag(text)")
    ausschnitt = quelle[anker:anker + 600]
    assert "_vorab_wissen" in ausschnitt
    assert "vorab_ergebnisse" in ausschnitt
