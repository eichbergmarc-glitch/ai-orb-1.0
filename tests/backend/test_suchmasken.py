"""Die Fachportale werden über ihre EIGENE Suchmaske bedient.

Der Benutzer hat es mehrfach verlangt: Der Orb soll die Suchmaschinen aus
seiner Favoritenleiste (JSTOR, BASE, Semantic Scholar, Wikipedia …)
wirklich benutzen und nicht nur ihre Domäne mit ``site:`` von aussen
abklopfen. Diese Tests sichern drei Dinge:

* Eine Favoritendomäne wird der richtigen Suchmaske zugeordnet.
* Die Leser machen aus der rohen Portal-Antwort saubere Treffer.
* ``favoriten_suche`` bedient bekannte Portale direkt, unbekannte über
  ``site:``, und Wikipedia ist immer als Auffangquelle dabei.
"""

from __future__ import annotations

import asyncio
import json

import backend.research.suchmasken as sm
from backend.research.suchmasken import (
    _WIKIPEDIA,
    direkt_suchen,
    favoriten_suche,
    maske_fuer,
)


# --- Zuordnung Domäne -> Maske ---------------------------------------------


def test_bekannte_domaenen_finden_ihre_maske():
    paare = {
        "jstor.org": "JSTOR",
        "www.jstor.org": "JSTOR",
        "scholar.google.de": "Google Scholar",
        "scholar.google.com": "Google Scholar",
        "base-search.net": "BASE",
        "semanticscholar.org": "Semantic Scholar",
        "de.wikipedia.org": "Wikipedia",
        "archive.org": "Internet Archive",
        "regesta-imperii.de": "Regesta Imperii",
    }
    for domaene, name in paare.items():
        maske = maske_fuer(domaene)
        assert maske is not None, domaene
        assert maske.name == name


def test_unbekannte_domaene_hat_keine_maske():
    assert maske_fuer("irgendein-blog.example.com") is None
    assert maske_fuer("") is None


# --- Die Leser --------------------------------------------------------------


def test_semantic_scholar_leser():
    roh = json.dumps({"data": [
        {"title": "Investiture Controversy", "abstract": "Ein Abstract.",
         "url": "https://semanticscholar.org/p/1", "year": 1998},
    ]}).encode("utf-8")
    treffer = sm._lese_semantic_scholar(roh, 3)
    assert treffer[0]["titel"] == "Investiture Controversy"
    assert "1998" in treffer[0]["beschreibung"]
    assert treffer[0]["url"].startswith("https://")


def test_archive_org_leser_baut_details_adresse():
    roh = json.dumps({"response": {"docs": [
        {"identifier": "meinbuch", "title": "Ein Buch",
         "description": ["Teil eins", "Teil zwei"]},
    ]}}).encode("utf-8")
    treffer = sm._lese_archive_org(roh, 3)
    assert treffer[0]["url"] == "https://archive.org/details/meinbuch"
    assert "Teil eins" in treffer[0]["beschreibung"]


def test_wikipedia_leser_entfernt_hervorhebung():
    roh = json.dumps({"query": {"search": [
        {"title": "Investiturstreit",
         "snippet": 'Der <span class="searchmatch">Investiturstreit</span> war'},
    ]}}).encode("utf-8")
    treffer = sm._lese_wikipedia(roh, 3)
    assert treffer[0]["titel"] == "Investiturstreit"
    assert "<span" not in treffer[0]["beschreibung"]
    assert treffer[0]["url"] == "https://de.wikipedia.org/wiki/Investiturstreit"


def test_leser_ueberleben_muell():
    for leser in (sm._lese_semantic_scholar, sm._lese_archive_org,
                  sm._lese_wikipedia, sm._lese_wikidata):
        assert leser(b"kein json", 3) == []


# --- direkt_suchen ist wehrhaft --------------------------------------------


def test_direkt_suchen_faengt_netzfehler_ab(monkeypatch):
    def _explodiert(*a, **k):
        raise OSError("kein Netz")

    monkeypatch.setattr(sm, "_fetch", _explodiert)
    # Kein Absturz, nur eine leere Liste.
    assert direkt_suchen(_WIKIPEDIA, "Investiturstreit", treffer=2) == []


def test_direkt_suchen_liest_gefetchte_antwort(monkeypatch):
    roh = json.dumps({"query": {"search": [
        {"title": "Sattelzeit", "snippet": "Begriff von Koselleck"},
    ]}}).encode("utf-8")
    monkeypatch.setattr(sm, "_fetch", lambda url, timeout=12.0: roh)
    treffer = direkt_suchen(_WIKIPEDIA, "Sattelzeit", treffer=2)
    assert treffer and treffer[0]["titel"] == "Sattelzeit"


# --- favoriten_suche: Maske vor site:, Wikipedia immer dabei ---------------


def test_favoriten_suche_bedient_maske_direkt_und_site_fuer_rest(monkeypatch):
    # Semantic Scholar hat eine Maske -> direkt_suchen wird benutzt.
    # meinblog.example.com hat keine -> search_web mit site: wird benutzt.
    masken_aufrufe: list[str] = []
    websuchen: list[str] = []

    def _falsche_maske(maske, begriff, *, treffer=3):
        masken_aufrufe.append(maske.name)
        return [{"titel": f"{maske.name}-Treffer", "url": "http://x", "beschreibung": ""}]

    def _falsche_websuche(anfrage, *, limit=6):
        websuchen.append(anfrage)
        return [{"titel": "Site-Treffer", "url": "http://y", "beschreibung": ""}]

    monkeypatch.setattr(sm, "direkt_suchen", _falsche_maske)
    monkeypatch.setattr("backend.tools.web_tools.search_web", _falsche_websuche)

    gesammelt = asyncio.run(favoriten_suche(
        "Investiturstreit",
        ["semanticscholar.org", "meinblog.example.com"],
        je_quelle=2,
    ))

    # Die Maske wurde direkt bedient ...
    assert "Semantic Scholar" in masken_aufrufe
    # ... und der Rest über site:.
    assert any("site:meinblog.example.com" in a for a in websuchen)
    # Jede Quelle taucht getrennt auf.
    namen = " ".join(gesammelt)
    assert "Semantic Scholar" in namen
    assert "meinblog.example.com" in namen


def test_favoriten_suche_haengt_wikipedia_als_auffang_an(monkeypatch):
    # Keine der Domänen ist Wikipedia -> die Auffangquelle muss ergänzt werden.
    benutzt: list[str] = []

    def _falsche_maske(maske, begriff, *, treffer=3):
        benutzt.append(maske.name)
        return [{"titel": maske.name, "url": "http://x", "beschreibung": ""}]

    monkeypatch.setattr(sm, "direkt_suchen", _falsche_maske)

    gesammelt = asyncio.run(favoriten_suche(
        "Sattelzeit", ["archive.org"], je_quelle=1,
    ))
    assert "Wikipedia" in benutzt
    assert any("Auffangquelle" in name for name in gesammelt)


def test_favoriten_suche_doppelt_wikipedia_wird_vermieden(monkeypatch):
    # Ist Wikipedia schon als Favorit dabei, darf die Auffangquelle NICHT
    # zusätzlich Wikipedia noch einmal abfragen.
    benutzt: list[str] = []

    def _falsche_maske(maske, begriff, *, treffer=3):
        benutzt.append(maske.name)
        return [{"titel": maske.name, "url": "http://x", "beschreibung": ""}]

    monkeypatch.setattr(sm, "direkt_suchen", _falsche_maske)

    asyncio.run(favoriten_suche("Sattelzeit", ["de.wikipedia.org"], je_quelle=1))
    assert benutzt.count("Wikipedia") == 1
