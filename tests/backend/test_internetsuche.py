"""Tests der Internetsuche.

Der Benutzer meldete: "orb kann nicht mehr aufs internet."

Im Protokoll stand davon nichts. Es stand darin, welche Strategie gewaehlt
wurde und dass eine Antwort kam - ob dazwischen gesucht wurde, ob die Suche
scheiterte oder ob sie nie versucht wurde, war nicht zu sehen. Drei sehr
verschiedene Fehler, ein einziges Bild.

Die Suche haengte an EINEM Zugang und darin an EINER CSS-Klasse
(``result__a``), die DuckDuckGo vergibt und jederzeit umbenennen kann.
Passt das Muster nicht mehr, ist die Trefferliste leer - und leer bedeutete
im alten Code "keine Treffer". Aus "die Seite hat sich geaendert" wurde
damit "es gibt nichts", und daraus im Gespraech "ich komme nicht ins
Internet".

Geprueft wird deshalb nicht, ob die Suche gerade funktioniert - das haengt
an einem fremden Rechner und waere ein Test, der mal so und mal so
ausgeht. Geprueft wird, dass sie NICHT MEHR AN EINER EINZIGEN KLASSE
HAENGT und dass sie die drei Fehlerarten auseinanderhaelt.
"""

from __future__ import annotations

import urllib.error

from backend.tools import web_tools


# --- Zwei Seitenformen, wie sie wirklich aussehen ------------------------------------

#: Die HTML-Fassung mit den bekannten Klassen - der feine Weg.
_MIT_KLASSEN = """
<html><body>
<div class="result results_links">
  <a class="result__a" href="/l/?uddg=https%3A%2F%2Ftagesschau.de%2Fausland">
    Lage im Nahen Osten
  </a>
  <a class="result__snippet">Die Nachrichtenlage von heute Abend.</a>
</div>
<div class="result results_links">
  <a class="result__a" href="/l/?uddg=https%3A%2F%2Fnzz.ch%2Finternational">
    Analyse der Woche
  </a>
  <a class="result__snippet">Einordnung der juengsten Ereignisse.</a>
</div>
</body></html>
"""

#: Dieselbe Seite, nachdem die Klassen umbenannt wurden - der grobe Weg.
#: Genau dieser Fall machte den Orb blind.
_OHNE_KLASSEN = """
<html><body>
<a href="/settings">Einstellungen</a>
<a href="https://duckduckgo.com/about">Ueber uns</a>
<table>
  <tr><td><a rel="nofollow" href="https://tagesschau.de/ausland">Lage im Nahen Osten</a></td></tr>
  <tr><td><a rel="nofollow" href="https://nzz.ch/international">Analyse der Woche</a></td></tr>
</table>
<a href="/help">Hilfe</a>
</body></html>
"""


def test_der_feine_weg_liest_titel_und_beschreibung():
    treffer = web_tools._treffer_aus_seite(_MIT_KLASSEN, 6)
    assert len(treffer) == 2
    assert treffer[0]["url"] == "https://tagesschau.de/ausland"
    assert treffer[0]["titel"] == "Lage im Nahen Osten"
    assert "Nachrichtenlage" in treffer[0]["beschreibung"]


def test_der_grobe_weg_greift_wenn_die_klassen_fehlen():
    """Der Fall, in dem der Orb bisher blind wurde."""

    treffer = web_tools._treffer_aus_seite(_OHNE_KLASSEN, 6)
    adressen = [t["url"] for t in treffer]
    assert "https://tagesschau.de/ausland" in adressen, (
        "Ohne die bekannten CSS-Klassen wird kein einziger Treffer gefunden - "
        "dann ist der Orb blind, sobald die Suchmaschine ihre Seite aendert."
    )
    assert "https://nzz.ch/international" in adressen


def test_der_grobe_weg_nimmt_keine_navigationslinks():
    """Sonst waere der erste Treffer die Einstellungsseite."""

    treffer = web_tools._treffer_aus_seite(_OHNE_KLASSEN, 6)
    adressen = " ".join(t["url"] for t in treffer)
    assert "duckduckgo.com" not in adressen, "Die Suchmaschine steht in ihrer eigenen Trefferliste."
    assert "/settings" not in adressen
    assert "/help" not in adressen


def test_rss_weg_liefert_echte_treffer_mit_beschreibung_und_datum():
    rss = """<?xml version="1.0"?><rss><channel><item>
      <title>Neue Entwicklung bei OpenAI</title>
      <link>https://beispiel.de/news/openai</link>
      <description>Das neue Modell wurde heute vorgestellt.</description>
      <pubDate>Thu, 13 Aug 2026 08:00:00 GMT</pubDate>
    </item></channel></rss>"""
    treffer = web_tools._rss_treffer(rss, 5)
    assert treffer == [{
        "titel": "Neue Entwicklung bei OpenAI",
        "url": "https://beispiel.de/news/openai",
        "beschreibung": (
            "Das neue Modell wurde heute vorgestellt. "
            "[Thu, 13 Aug 2026 08:00:00 GMT]"
        ),
    }]


def test_bing_news_rss_umleitung_wird_zur_quelladresse():
    link = (
        "http://www.bing.com/news/apiclick.aspx?ref=FexRss&"
        "url=https%3A%2F%2Ftagesschau.de%2Fwirtschaft%2Fopenai-100.html"
    )
    assert web_tools._zieladresse(link) == (
        "https://tagesschau.de/wirtschaft/openai-100.html"
    )


def test_die_hoechstzahl_wird_eingehalten():
    assert len(web_tools._treffer_aus_seite(_OHNE_KLASSEN, 1)) == 1
    assert len(web_tools._treffer_aus_seite(_MIT_KLASSEN, 1)) == 1


# --- Die drei Fehlerarten -------------------------------------------------------------


def _mit_antwort(antwort, monkeypatch):
    """Ersetzt das Holen der Seite durch eine feste Antwort."""

    def _hol(url, *, data=None, timeout=12.0):
        if isinstance(antwort, Exception):
            raise antwort
        return antwort.encode("utf-8")

    monkeypatch.setattr(web_tools, "_fetch", _hol)


def test_keine_leitung_heisst_kein_netz(monkeypatch):
    _mit_antwort(urllib.error.URLError("getaddrinfo failed"), monkeypatch)
    try:
        web_tools.search_web("irgendwas")
    except web_tools._Suchfehler as fehler:
        assert fehler.art == "kein_netz"
    else:
        raise AssertionError("Kein Fehler, obwohl keine Leitung da war.")


def test_abweisung_wird_nicht_mit_leerer_trefferliste_verwechselt(monkeypatch):
    """Der wichtigste der drei Unterschiede.

    Abgewiesen zu werden heisst: Die Leitung steht, die Suchmaschine mag
    nur nicht. Das ist etwas voellig anderes als "kein Internet", und der
    Benutzer soll es auch verschieden zu hoeren bekommen.
    """

    _mit_antwort("<html><body>Our systems detected unusual traffic.</body></html>",
                 monkeypatch)
    try:
        web_tools.search_web("irgendwas")
    except web_tools._Suchfehler as fehler:
        assert fehler.art == "abgewiesen"
    else:
        raise AssertionError("Eine Abweisung ging als Erfolg durch.")


def test_geaenderter_seitenaufbau_heisst_unlesbar_und_nicht_leer(monkeypatch):
    """Genau der Fall, der als "kein Internet" ankam."""

    _mit_antwort("<html><body><p>" + "x" * 900 + "</p></body></html>", monkeypatch)
    try:
        web_tools.search_web("irgendwas")
    except web_tools._Suchfehler as fehler:
        assert fehler.art == "unlesbar"
        assert "geaendert" in str(fehler) or "kein" in str(fehler).lower()
    else:
        raise AssertionError(
            "Eine unlesbare Seite ging als Erfolg durch - dann meldet der Orb "
            "wieder 'keine Treffer', wo in Wahrheit der Aufbau kaputt ist."
        )


def test_der_zweite_zugang_rettet_die_suche(monkeypatch):
    """Ein einziger Zugang war die eigentliche Schwaeche."""

    versuche: list[str] = []

    def _hol(url, *, data=None, timeout=12.0):
        versuche.append(url)
        if len(versuche) == 1:
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return _MIT_KLASSEN.encode("utf-8")

    monkeypatch.setattr(web_tools, "_fetch", _hol)
    treffer = web_tools.search_web("irgendwas")
    assert len(versuche) == 2, "Nach dem ersten Fehlschlag wurde nichts mehr versucht."
    assert treffer, "Der zweite Zugang lieferte Treffer, sie kamen aber nicht an."


def test_es_gibt_mehrere_unabhaengige_maschinen():
    """Der Kern der Behebung von "DuckDuckGo weist den Orb ab".

    Nicht nur mehrere Zugaenge, sondern mehrere UNABHAENGIGE Indizes.
    Zuvor standen hier zwei DuckDuckGo-Adressen - blockt DuckDuckGo die
    Adresse des Benutzers, fallen beide zugleich aus.
    """

    maschinen = web_tools._SUCHMASCHINEN
    assert len(maschinen) >= 3
    # Mindestens eine, die NICHT DuckDuckGo ist, muss vorn stehen.
    erste = maschinen[0]
    assert "duckduckgo" not in erste.adresse.lower(), (
        "Vorn steht wieder DuckDuckGo - bei einer Sperre wartet der Orb "
        "erst dessen Fehlschlag ab, bevor er woandershin ausweicht."
    )
    # Es muss echte Vielfalt geben, nicht nur DuckDuckGo-Spiegel.
    fremd = [m for m in maschinen if "duckduckgo" not in m.adresse.lower()]
    assert len(fremd) >= 2, "Zu wenig unabhaengige Suchmaschinen."


def test_eine_abgewiesene_maschine_reicht_die_suche_weiter(monkeypatch):
    """Genau der gemeldete Fall: die erste Maschine weist ab."""

    versuche: list[str] = []

    def _hol(url, *, data=None, timeout=12.0):
        versuche.append(url)
        if len(versuche) == 1:
            # Erste Maschine: abgewiesen.
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return _OHNE_KLASSEN.encode("utf-8")

    monkeypatch.setattr(web_tools, "_fetch", _hol)
    treffer = web_tools.search_web("irgendwas")
    assert len(versuche) == 2, "Nach der Abweisung wurde keine zweite Maschine versucht."
    assert treffer, "Die zweite Maschine lieferte Treffer, sie kamen aber nicht an."


def test_themenfremde_rss_treffer_werden_nicht_als_erfolg_akzeptiert(monkeypatch):
    """Das reale Fehlerbild: Toyota statt intuitivem Bogenschiessen."""

    calls: list[str] = []

    def _search(machine, query, limit):  # noqa: ANN001
        calls.append(machine.name)
        if len(calls) == 1:
            return [{
                "titel": "Used Toyota Camry Cars For Sale",
                "url": "https://cars.example/camry",
                "beschreibung": "Find your next used vehicle.",
            }]
        return [{
            "titel": "Intuitives Bogenschiessen mit dem Reiterbogen",
            "url": "https://archery.example/reiterbogen",
            "beschreibung": "Anleitung zu Technik, Daumenablass und Sicherheit.",
        }]

    monkeypatch.setattr(web_tools, "_einmal_suchen", _search)
    results = web_tools.search_web(
        "Suche eine Anleitung zum intuitiven Bogenschiessen und erstelle eine PDF",
        limit=5,
    )

    assert len(calls) == 2
    assert results[0]["url"] == "https://archery.example/reiterbogen"


def test_ausgabeformat_verschmutzt_den_suchbegriff_nicht():
    query = web_tools.suchbegriff_aus(
        "Suche nach einer Anleitung zum intuitiven Bogenschießen und erstelle "
        "daraus eine PDF-Datei mit Grafiken."
    )

    assert "bogenschießen" in query
    for noise in ("erstelle", "pdf", "grafiken", "daraus"):
        assert noise not in query


# --- Und das Protokoll ----------------------------------------------------------------


def test_werkzeugeinsaetze_stehen_im_protokoll():
    """Ohne das war die Stoerung nicht einzukreisen.

    Die erste Frage bei jeder Meldung dieser Art lautet: Hat der Orb das
    Werkzeug ueberhaupt benutzt? Sie war nicht zu beantworten, weil
    Werkzeugaufrufe nur auf DEBUG standen.
    """

    from backend.utils.paths import get_project_root

    quelle = (get_project_root() / "backend" / "tools" / "tool_engine.py").read_text(
        encoding="utf-8"
    )
    assert "logger.info(\n                \"Werkzeug '%s' ausgefuehrt" in quelle, (
        "Erfolgreiche Werkzeugeinsaetze stehen nicht im Protokoll."
    )
    assert "logger.warning(\n                \"Werkzeug '%s' fehlgeschlagen" in quelle, (
        "Fehlgeschlagene Werkzeugeinsaetze stehen nicht im Protokoll."
    )


# --- Was 'webseite_lesen' zurueckgibt --------------------------------------------------
#
# Der Benutzer meldete einen Werkzeugfehler. Im Protokoll stand kein
# Absturz - das Werkzeug meldete Erfolg. Es hatte auch Erfolg: Es hat eine
# Seite geholt und Text zurueckgegeben. Nur war es dieser Text:
#
#     Werkzeug 'webseite_lesen' ausgefuehrt (0.2 s):
#     Hauptnavigation | Nebennavigation | Inhalt | Fussszeile |
#     Suchbegriff | InlandUntermenue Inland einblenden | Ausland...
#
# Also die Navigationsleiste. Der Artikel stand im Quelltext weiter unten
# und fiel der Kuerzung bei viertausend Zeichen zum Opfer. Der Orb bekam
# ein Inhaltsverzeichnis statt einer Nachricht - und das ist der Sache
# nach ein kaputtes Werkzeug, auch wenn nichts abgestuerzt ist.

#: Eine Nachrichtenseite, gebaut wie die echten: erst das Beiwerk.
_NACHRICHTENSEITE = """
<html><head><title>Nachrichten</title><script>var x=1;</script></head>
<body>
  <header>Hauptnavigation</header>
  <nav>Inland Untermenü Inland einblenden Ausland Wirtschaft Sport</nav>
  <div role="navigation">Nebennavigation</div>
  <form><label>Suchbegriff</label><button>Suchen</button></form>
  <main>
    <h1>Lage im Nahen Osten spitzt sich zu</h1>
    <p>Nach Angaben der Regierung sind in der Nacht mehrere Anlagen
    getroffen worden. Die Behoerden sprechen von erheblichen Schaeden an
    der Infrastruktur und haben die Bevoelkerung aufgerufen, die Gebiete
    zu meiden.</p>
    <p>Beobachter halten eine weitere Eskalation fuer wahrscheinlich. Die
    Vereinten Nationen haben fuer den Nachmittag eine Sitzung des
    Sicherheitsrats angesetzt, in der ueber das weitere Vorgehen beraten
    werden soll.</p>
  </main>
  <aside>Meistgelesen: Zehn Rezepte fuer den Sommer</aside>
  <footer>Impressum Datenschutz Kontakt</footer>
</body></html>
"""


def _gelesen(seite: str) -> str:
    leser = web_tools._TextExtractor()
    leser.feed(seite)
    return leser.text()


def test_der_artikel_steht_vorn_und_nicht_das_menue():
    """Genau der Fall aus dem Protokoll."""

    text = _gelesen(_NACHRICHTENSEITE)
    assert text.startswith("Lage im Nahen Osten"), (
        "Der Text beginnt nicht mit der Ueberschrift, sondern mit: "
        + text[:80]
    )
    assert "Sicherheitsrats" in text


def test_das_beiwerk_faellt_weg():
    text = _gelesen(_NACHRICHTENSEITE)
    for beiwerk in ("Hauptnavigation", "Nebennavigation", "Suchbegriff",
                    "Impressum", "Meistgelesen"):
        assert beiwerk not in text, f"'{beiwerk}' steht noch im gelesenen Text."


def test_ohne_hauptteil_wird_trotzdem_gelesen():
    """Nicht jede Seite hat ein <main> - dann gilt der alte Weg."""

    seite = ("<html><body><nav>Menue</nav><p>" + "Ein Satz ueber das Thema. " * 30
             + "</p></body></html>")
    text = _gelesen(seite)
    assert "Ein Satz ueber das Thema." in text
    assert "Menue" not in text


def test_ein_leerer_hauptteil_verwirft_die_seite_nicht():
    """Manche Seiten laden den Inhalt erst nachtraeglich.

    Dann waere der Hauptteil zwar vorhanden, aber leer - und ein leeres
    Ergebnis waere schlechter als das alte Verhalten.
    """

    seite = ("<html><body><main></main><p>" + "Der eigentliche Inhalt steht hier. " * 20
             + "</p></body></html>")
    assert "Der eigentliche Inhalt steht hier." in _gelesen(seite)


def test_skripte_und_stile_kommen_nicht_durch():
    seite = "<html><body><main><style>.a{color:red}</style>" \
            "<p>" + "Wirklicher Inhalt in Sätzen. " * 20 + "</p></main></body></html>"
    text = _gelesen(seite)
    assert "color:red" not in text
    assert "Wirklicher Inhalt" in text


# =============================================================================
#  Bing: die Umleitung, an der die ganze Suche haengenblieb
# =============================================================================
# Im Protokoll des Benutzers ("alle suchmaschinen werden abgelehnt") stand
# der wahre Hergang: Mojeek und Ecosia antworteten mit 403, DuckDuckGo wies
# ab - aber Bing ANTWORTETE, mit 74000 Zeichen. Nur wurde daraus kein
# Treffer gelesen. Der Grund: Bing schickt jeden Treffer ueber eine eigene
# Umleitung  www.bing.com/ck/a?...&u=a1<base64>&... . Jeder Link hatte damit
# den Wirt bing.com und wurde als "die Suchmaschine selbst" verworfen. Die
# Trefferliste war voll und galt doch als leer.


def _bing_umleitung(ziel: str) -> str:
    import base64

    kern = base64.urlsafe_b64encode(ziel.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=1a2b&u=a1{kern}&ntb=1"


def test_bing_umleitung_wird_aufgeloest():
    ziel = "https://www.tagesschau.de/ausland/nahost-100.html"
    assert web_tools._resolve_bing_url(_bing_umleitung(ziel)) == ziel


def test_bing_umleitung_ohne_a1_bleibt_unveraendert():
    # Nur echte ck/a-Umleitungen mit dem a1-Vorsatz werden angefasst.
    fremd = "https://www.bing.com/images/search?q=katze"
    assert web_tools._resolve_bing_url(fremd) == fremd


def test_bing_ergebnisseite_wird_endlich_gelesen():
    """Der Kern der Behebung: aus 'antwortete, kein Treffer' wird 'Treffer'."""

    seite = f"""
    <html><body>
    <header><a href="https://www.bing.com/">Bing Startseite Menue</a></header>
    <ol id="b_results">
      <li class="b_algo"><h2><a href="{_bing_umleitung('https://www.tagesschau.de/ausland/nahost-100.html')}">
        Lage im Nahen Osten ausfuehrlich</a></h2></li>
      <li class="b_algo"><h2><a href="{_bing_umleitung('https://www.aljazeera.com/news/lage')}">
        Al Jazeera zur selben Lage</a></h2></li>
    </ol>
    <footer><a href="https://go.microsoft.com/datenschutz">Datenschutz Hinweise</a></footer>
    </body></html>
    """
    eigene = ("bing.com", "microsoft.com", "msn.com", "microsofttranslator.com")
    treffer = web_tools._treffer_aus_seite(seite, 6, eigene)
    adressen = [t["url"] for t in treffer]
    assert "https://www.tagesschau.de/ausland/nahost-100.html" in adressen
    assert "https://www.aljazeera.com/news/lage" in adressen
    assert not any("bing.com" in u for u in adressen), (
        "Die Bing-eigenen Umleitungslinks duerfen nicht als Treffer erscheinen."
    )


def test_bing_steht_als_erste_maschine():
    """Bing ist der einzige Zugang, der im Protokoll antwortete - also zuerst."""

    assert web_tools._SUCHMASCHINEN[0].name == "Bing"


# =============================================================================
#  webseite_erkunden: scrollen und Links folgen
# =============================================================================


def _stub_fetch(seiten: dict[str, str]):
    def fetch(url, data=None, timeout=12.0):
        if url not in seiten:
            raise urllib.error.HTTPError(url, 404, "nicht da", None, None)
        return seiten[url].encode("utf-8")
    return fetch


def _explorer(monkeypatch, seiten):
    monkeypatch.setattr(web_tools, "_fetch", _stub_fetch(seiten))
    return web_tools.WebseiteErkundenTool()


import asyncio  # noqa: E402


def test_erkunden_oeffnet_blaettert_und_folgt_link(monkeypatch):
    seiten = {
        "https://start.example/": (
            "<html><body><main><h1>Startseite</h1><p>"
            + ("Lorem ipsum dolor sit amet. " * 120)
            + "</p><a href='/artikel/eins.html'>Der erste ausfuehrliche Artikel</a>"
            + "</main></body></html>"
        ),
        "https://start.example/artikel/eins.html": (
            "<html><body><article><p>Der vollstaendige Text des Artikels.</p>"
            "</article></body></html>"
        ),
    }
    t = _explorer(monkeypatch, seiten)

    auf = asyncio.run(t.execute({"aktion": "oeffnen", "ziel": "https://start.example/"}))
    assert auf.ok and "Startseite" in auf.output

    vorher = t._offset
    asyncio.run(t.execute({"aktion": "weiter"}))
    assert t._offset > vorher, "aktion='weiter' muss im Text nach unten blaettern."

    liste = asyncio.run(t.execute({"aktion": "links"}))
    assert "artikel/eins.html" in liste.output

    nummer = next(i + 1 for i, (u, _) in enumerate(t._links) if "artikel/eins" in u)
    gefolgt = asyncio.run(t.execute({"aktion": "oeffnen", "ziel": str(nummer)}))
    assert "artikel/eins.html" in t._url
    assert "vollstaendige Text" in gefolgt.output


def test_erkunden_folgt_link_per_stichwort(monkeypatch):
    seiten = {
        "https://start.example/": (
            "<html><body><main><p>Text.</p>"
            "<a href='https://www.aljazeera.com/news/lage'>Al Jazeera zur Lage</a>"
            "</main></body></html>"
        ),
        "https://www.aljazeera.com/news/lage": (
            "<html><body><article><p>Bericht zur Lage.</p></article></body></html>"
        ),
    }
    t = _explorer(monkeypatch, seiten)
    asyncio.run(t.execute({"aktion": "oeffnen", "ziel": "https://start.example/"}))
    asyncio.run(t.execute({"aktion": "oeffnen", "ziel": "Jazeera"}))
    assert "aljazeera.com" in t._url


def test_erkunden_ohne_offene_seite_meldet_das(monkeypatch):
    t = _explorer(monkeypatch, {})
    r = asyncio.run(t.execute({"aktion": "weiter"}))
    assert not r.ok
    assert "keine seite" in r.error.lower()
