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
                    if "kaputtes-json" in frage.get("query", [""])[0]:
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
        oq.gdelt_suchen("kaputtes-json")


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


def test_finden_die_offenen_quellen_nichts_bleibt_der_alte_weg(monkeypatch):
    from backend.tools import web_tools

    gerufen: list[str] = []

    monkeypatch.setattr(
        "backend.research.offene_quellen.offene_suche",
        lambda query, *, limit=6: ([], []),
    )

    def _maschine(maschine, query, limit):
        gerufen.append(maschine.name)
        return [{"titel": "Alter Weg", "url": "https://example.org/alt",
                 "beschreibung": "Bismarck Otto von"}]

    monkeypatch.setattr(web_tools, "_einmal_suchen", _maschine)
    treffer = web_tools.search_web("Otto von Bismarck", limit=3)
    assert treffer[0]["url"] == "https://example.org/alt"
    assert gerufen, "der alte Weg muss noch erreichbar sein"


def test_ein_fehler_in_den_offenen_quellen_verhindert_die_suche_nicht(monkeypatch):
    from backend.tools import web_tools

    def _kaputt(query, *, limit=6):
        raise RuntimeError("etwas ganz Unerwartetes")

    monkeypatch.setattr("backend.research.offene_quellen.offene_suche", _kaputt)
    monkeypatch.setattr(
        web_tools, "_einmal_suchen",
        lambda m, q, l: [{"titel": "Alter Weg", "url": "https://example.org/alt",
                          "beschreibung": "Bismarck Otto"}],
    )
    treffer = web_tools.search_web("Otto von Bismarck", limit=3)
    assert treffer and treffer[0]["url"] == "https://example.org/alt"
