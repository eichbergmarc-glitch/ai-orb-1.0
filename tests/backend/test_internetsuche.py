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
import urllib.parse

from backend.tools import web_tools




import pytest


@pytest.fixture(autouse=True)
def _altmaschinen_und_stille_offene_quellen(monkeypatch):
    """Versetzt diese Tests in den Diagnosebetrieb der alten Suchkette.

    Seit Stufe 3 der Bestandsaufnahme (17.08.2026) sind die
    Trefferseiten-Maschinen im Normalbetrieb abgeschaltet - sie lieferten
    seit Tagen nur Abweisungen und kosteten jede leere Suche zehn und mehr
    Sekunden. Diese Tests pruefen die Kette selbst (Fehlerarten,
    Ausweichzugang, Lesbarkeit) und schalten sie dafuer gezielt wieder ein;
    die offenen Quellen werden stummgeschaltet, damit die Kette ueberhaupt
    drankommt.
    """

    monkeypatch.setattr(web_tools, "ALTMASCHINEN_AKTIV", True)
    monkeypatch.setattr(
        "backend.research.offene_quellen.offene_suche",
        lambda query, *, limit=6: ([], []),
    )
    yield


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
    # Die Produktionssuche verwirft inzwischen bewusst themenfremde Treffer.
    # Deshalb muss auch dieser Infrastrukturtest nach dem Thema fragen, das
    # seine feste HTML-Antwort tatsaechlich enthaelt.
    treffer = web_tools.search_web("Lage im Nahen Osten")
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
    treffer = web_tools.search_web("Lage im Nahen Osten")
    assert len(versuche) == 2, "Nach der Abweisung wurde keine zweite Maschine versucht."
    assert treffer, "Die zweite Maschine lieferte Treffer, sie kamen aber nicht an."


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
    # Geprueft wird die Eigenschaft, nicht der Wortlaut.
    #
    # Vorher stand hier die Log-Zeile Zeichen fuer Zeichen. Sie wurde am
    # 01.09.2026 um die Korrelations-Kennung ergaenzt, und der Test wurde
    # rot, obwohl genau das MEHR Protokoll ist, nicht weniger.
    assert "logger.info(" in quelle and "Werkzeug '%s' ausgefuehrt" in quelle, (
        "Erfolgreiche Werkzeugeinsaetze stehen nicht im Protokoll."
    )
    assert "logger.warning(" in quelle and "Werkzeug '%s' fehlgeschlagen" in quelle, (
        "Fehlgeschlagene Werkzeugeinsaetze stehen nicht im Protokoll."
    )
    assert "_kennung()" in quelle, (
        "Die Werkzeugzeilen tragen die Korrelations-Kennung nicht mit; "
        "ein Zug laesst sich dann im Protokoll nicht verfolgen."
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


def test_yahoo_weiterleitung_wird_aufgeloest():
    ziel = "https://www.comparis.ch/hausrat-versicherung/privathaftpflicht"
    kodiert = urllib.parse.quote(ziel, safe="")
    umleitung = (
        "https://r.search.yahoo.com/_ylt=abc/RV=2/RE=123/RO=10/"
        f"RU={kodiert}/RK=2/RS=abc"
    )
    assert web_tools._resolve_yahoo_url(umleitung) == ziel


def test_bing_rss_wird_ohne_html_heuristik_gelesen():
    seite = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel><item>
      <title>Haftpflichtversicherung Schweiz im Vergleich</title>
      <link>https://example.ch/versicherung</link>
      <description>Angebote, Preise und Leistungen vergleichen.</description>
      <pubDate>Tue, 25 Aug 2026 12:00:00 GMT</pubDate>
    </item></channel></rss>"""

    treffer = web_tools._rss_treffer(seite, 3)
    assert treffer == [{
        "titel": "Haftpflichtversicherung Schweiz im Vergleich",
        "url": "https://example.ch/versicherung",
        "beschreibung": (
            "Angebote, Preise und Leistungen vergleichen. "
            "[Tue, 25 Aug 2026 12:00:00 GMT]"
        ),
    }]


def test_deutsche_beugung_passt_auch_zu_englischem_suchtreffer():
    treffer = [{
        "titel": "OpenAI models",
        "url": "https://openai.com/models",
        "beschreibung": "Current model overview",
    }]
    assert web_tools._relevante_treffer("OpenAI aktuelle Modelle", treffer)


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


# ---------------------------------------------------------------------------
# Die Suche meldete jede Anfrage als "Bot erkannt" (26.08.2026)
# ---------------------------------------------------------------------------
#
# Das Protokoll des Benutzers zeigte bei JEDER Suche dieselbe Meldung:
# "Die Suchmaschine hat meine Anfrage abgewiesen; sie haelt sie fuer
# automatisiert." Danebenstand aber, dass Bing und Yahoo geantwortet und
# Treffer geliefert hatten. Zwei Fehler wirkten zusammen, und die folgenden
# Tests halten beide fest.


def test_relevanzfilter_verlangt_hoechstens_zwei_uebereinstimmungen():
    """Der Filter darf eine lange Anfrage nicht selbst erwuergen.

    Vorher verlangte er die HAELFTE aller tragenden Woerter. Bei dem echten
    Suchbegriff aus dem Protokoll waren das vier Woerter in EINER
    Trefferzeile - das schafft kein Treffer, und deshalb meldeten Bing und
    Yahoo gleichermassen "nur themenfremde Treffer".
    """

    frage = "markus gabriel nicht modellen gesprochen aktuell alle erhaelt"
    treffer = [
        {
            "titel": "Markus Gabriel im Gespraech",
            "url": "https://example.org/gabriel",
            "beschreibung": "Der Bonner Philosoph Markus Gabriel ueber den Neuen Realismus.",
        }
    ]
    assert web_tools._relevante_treffer(frage, treffer) == treffer


def test_relevanzfilter_siebt_voellig_fremde_treffer_weiterhin_aus():
    """Die Lockerung darf den Filter nicht wirkungslos machen."""

    frage = "markus gabriel neuer realismus philosophie"
    treffer = [
        {
            "titel": "VW Golf guenstig kaufen",
            "url": "https://example.org/auto",
            "beschreibung": "Jahreswagen und Neuwagen im Vergleich.",
        }
    ]
    assert web_tools._relevante_treffer(frage, treffer) == []


def test_die_echte_duckduckgo_sperrseite_wird_als_sperre_erkannt():
    """Die Sperrseite aus dem Protokoll muss weiterhin als Sperre gelten."""

    seite = (
        "<html><head><title>DuckDuckGo</title></head><body>"
        '<div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>'
        '<div class="anomaly-modal__description">Please complete the following '
        "challenge to confirm this search was made by a human.</div>"
        "</body></html>"
    ).lower()
    assert any(wort in seite for wort in web_tools._ABWEISUNGEN)


def test_ein_klassenname_allein_ist_keine_sperre():
    """Ein CSS-Name wie ``anomaly-modal`` darf keine Sperre bedeuten.

    Genau daran hing die falsche Meldung: Das blosse Wort "anomaly" stand
    in der Abweisungsliste und kommt auf jeder DuckDuckGo-Seite vor.
    """

    seite = (
        '<html><body><div class="anomaly-modal__mask"></div>'
        '<a href="https://example.org">Ein ganz normaler Treffer</a>'
        "<p>Werbung wurde adblocked.</p></body></html>"
    ).lower()
    assert not any(wort in seite for wort in web_tools._ABWEISUNGEN)


def test_eine_antwortende_maschine_schlaegt_die_gesperrte_letzte():
    """Nicht die zuletzt versuchte Maschine bestimmt die Diagnose.

    Bing und Yahoo antworten, DuckDuckGo Lite ist gesperrt und steht
    zuletzt. Gemeldet werden muss die weiteste erreichte Stelle - sonst
    hoert der Benutzer "Bot erkannt", obwohl zwei Maschinen geliefert haben.
    """

    fehler = [
        web_tools._Suchfehler("themenfremd", "Bing lieferte nur themenfremde Treffer."),
        web_tools._Suchfehler("themenfremd", "Yahoo lieferte nur themenfremde Treffer."),
        web_tools._Suchfehler("abgewiesen", "DuckDuckGo Lite hat die Anfrage abgewiesen."),
    ]
    assert web_tools._hauptursache(fehler) == "themenfremd"


def test_ohne_jede_leitung_bleibt_es_bei_kein_netz():
    fehler = [
        web_tools._Suchfehler("kein_netz", "Bing war nicht erreichbar."),
        web_tools._Suchfehler("kein_netz", "Yahoo war nicht erreichbar."),
    ]
    assert web_tools._hauptursache(fehler) == "kein_netz"


def test_nur_sperren_bleiben_eine_sperre():
    fehler = [
        web_tools._Suchfehler("abgewiesen", "Bing antwortete mit 403."),
        web_tools._Suchfehler("abgewiesen", "DuckDuckGo Lite hat abgewiesen."),
    ]
    assert web_tools._hauptursache(fehler) == "abgewiesen"


def test_verworfene_treffer_werden_als_notweg_zurueckgegeben(monkeypatch):
    """Lieber lose passende Treffer als eine gescheiterte Suche."""

    fremde = [
        {
            "titel": "Etwas ganz anderes",
            "url": "https://example.org/anderes",
            "beschreibung": "Passt nicht zur Anfrage.",
        }
    ]

    def nur_fremdes(maschine, query, limit):
        return list(fremde)

    monkeypatch.setattr(web_tools, "_einmal_suchen", nur_fremdes)
    monkeypatch.setattr(
        web_tools, "offene_suche", lambda *a, **k: ([], []), raising=False
    )

    ergebnis = web_tools.search_web("markus gabriel neuer realismus", limit=3)
    assert ergebnis == fremde


# ---------------------------------------------------------------------------
# Der Suchbegriff: aus einem gesprochenen Satz wurde Wortsalat (26.08.2026)
# ---------------------------------------------------------------------------


def test_wer_ist_ein_fragewort_und_kein_suchbegriff():
    """"Wer war Bismarck" darf nicht als "wer bismarck" gesucht werden."""

    assert web_tools.suchbegriff_aus("Wer war Bismarck") == "bismarck"


def test_fuellwoerter_verduennen_den_namen_nicht_mehr():
    """Aus dem Protokoll: "nicht", "alle" zaehlten als volle Suchwoerter."""

    frage = "Was hat Markus Gabriel nicht zu allen neuen Modellen gesagt?"
    begriff = web_tools.suchbegriff_aus(frage)
    assert "markus" in begriff and "gabriel" in begriff
    for fuellwort in ("nicht", "allen", "gesagt"):
        assert fuellwort not in begriff.split()


def test_die_anfrage_bleibt_kurz_genug_um_treffer_zu_haben():
    """Ein langer Satz darf keine zwoelfwoertrige Anfrage ergeben.

    Jedes zusaetzliche Wort verlangt eine Suchmaschine mit; ab etwa einem
    Dutzend findet sie nichts mehr, was alle erfuellt.
    """

    frage = (
        "Hallo Orb, kannst du mir bitte sagen, wann diese Zeit ist, wo ich "
        "die Frage mit Urkunden abgleichen kann, Startpunkt und Endpunkt "
        "und am besten auch noch die Jahreszahlen dazu"
    )
    begriff = web_tools.suchbegriff_aus(frage)
    assert len(begriff.split()) <= web_tools._HOECHSTENS_WOERTER


def test_eigennamen_ueberleben_die_kuerzung():
    """Grossgeschriebenes im Originalsatz ist das Thema - es muss bleiben."""

    frage = (
        "Sag mir bitte mal eben, ob Markus Gabriel in Bonn ueber den Neuen "
        "Realismus und ueber Bewusstsein und ueber Sinnfelder gesprochen hat"
    )
    begriff = web_tools.suchbegriff_aus(frage)
    assert "markus" in begriff and "gabriel" in begriff


def test_site_filter_bleibt_unangetastet():
    begriff = web_tools.suchbegriff_aus(
        "Finde Studien zum Realismus site:jstor.org bitte"
    )
    assert "site:jstor.org" in begriff


# ---------------------------------------------------------------------------
# Alltagssuche: der Abbruch machte einen Suchschluessel wirkungslos
# ---------------------------------------------------------------------------


def test_alltagssuche_bricht_ohne_echten_webindex_weiterhin_ab(monkeypatch):
    """Ohne Schluessel bleibt es beim ehrlichen Fehler statt Wikipedia."""

    monkeypatch.setattr(web_tools, "_echter_webindex_verfuegbar", lambda: False)
    monkeypatch.setattr(
        web_tools,
        "_einmal_suchen",
        lambda maschine, query, limit: (_ for _ in ()).throw(
            web_tools._Suchfehler("abgewiesen", f"{maschine.name} hat abgewiesen.")
        ),
    )
    with pytest.raises(web_tools._Suchfehler):
        web_tools.search_web("was kostet eine Hausratversicherung Preis", limit=3)


def test_alltagssuche_fragt_mit_schluessel_die_offenen_quellen(monkeypatch):
    """Mit Schluessel darf der Abbruch die beste Quelle nicht ueberspringen."""

    gefragt: list[str] = []

    def keine_maschine(maschine, query, limit):
        raise web_tools._Suchfehler("abgewiesen", f"{maschine.name} hat abgewiesen.")

    def offene(query, limit=6):
        gefragt.append(query)
        return (
            [
                {
                    "titel": "Hausratversicherung Preise 2026",
                    "url": "https://example.org/hausrat",
                    "beschreibung": "Was eine Hausratversicherung kostet.",
                }
            ],
            ["Google"],
        )

    monkeypatch.setattr(web_tools, "_echter_webindex_verfuegbar", lambda: True)
    monkeypatch.setattr(web_tools, "_einmal_suchen", keine_maschine)
    import backend.research.offene_quellen as oq

    monkeypatch.setattr(oq, "offene_suche", offene)

    treffer = web_tools.search_web("Hausratversicherung Preis kosten", limit=3)
    assert gefragt, "Die offenen Quellen wurden gar nicht erst gefragt."
    assert treffer and "hausrat" in treffer[0]["url"]


def test_duckduckgo_steht_nicht_mehr_in_der_normalrotation():
    """Eine Maschine, die zuverlaessig ein Bilderraetsel zeigt, kostet nur Zeit."""

    namen = {maschine.name for maschine in web_tools._SUCHMASCHINEN}
    assert "DuckDuckGo Lite" in namen, "Der Ausweichweg muss erhalten bleiben."
    assert "DuckDuckGo Lite" not in web_tools.NORMALE_MASCHINEN
    assert web_tools.NORMALE_MASCHINEN == frozenset({"Bing", "Yahoo"})
