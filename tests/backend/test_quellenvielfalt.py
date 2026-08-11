"""Tests der Quellenvielfalt und der eigenen Favoriten als Rechercheziel.

Der Benutzer stellte zwei Fragen und traf damit zwei echte Luecken:

  "sind die Suchmaschinen aus der Edge Favoritenleiste fuer
   geschichtswissenschaftliche Fragen verlinkt?"

Halb. Der Orb durchsuchte die LESEZEICHEN - Titel, Adresse, Ordnername.
Was auf diesen Seiten steht, blieb ihm verschlossen. Aus einem Archivportal
in der Leiste wurde ein Link und keine Quelle.

  "nutzt er fuer allgemeine Fragen auch andere Suchmaschinen und
   verschiedene Quellen, zum Beispiel Al Jazeera?"

Nein. Eine Suchmaschine, und gelesen wurde, was oben stand - bei deutschen
Fragen fast immer tagesschau oder zdfheute.

Und danach, unmissverstaendlich:

  "er soll aber die Suchmaschinen die verlinkt sind auch wirklich nutzen
   sonst bringt die funktion nichts"

Genau das ist der Kern. Eine Anweisung im Systemprompt, die Favoriten zu
befragen, stand seit Wochen da - und in keinem Protokoll taucht ein Aufruf
auf. Diese Tests sichern deshalb nicht, dass es MOEGLICH ist, sondern dass
es GESCHIEHT.
"""

from __future__ import annotations

import asyncio

from backend.orchestrator.orchestrator import Orchestrator, braucht_aktuelles
from backend.research.eigene_quellen import _domaene, eigene_domaenen
from backend.tools import web_tools


_PROFESSOR = "Du bist der persoenliche Geschichtsprofessor des Benutzers."


def _regel(text: str, kontext: str | None = None) -> bool:
    return Orchestrator._ist_fachfrage(Orchestrator.__new__(Orchestrator), text, kontext)


# --- Wann in den eigenen Quellen gesucht wird ----------------------------------------


def test_eine_fachfrage_loest_die_eigenen_quellen_aus():
    assert _regel("Wie bewertet die Forschung die Dekolonisation?")
    assert _regel("Was sagt die Quellenlage zum Westfaelischen Frieden?")


def test_ein_eigenname_reicht_nicht_aber_der_professor_schon():
    """Die Luecke, die keine Wortliste schliessen kann.

    "Welche Ursachen hatte der Investiturstreit?" enthaelt kein einziges
    Merkmal der Fachwortliste - Eigennamen fehlen dort naturgemaess. Eine
    Liste, die auch "Sattelzeit" und
    "Reichsdeputationshauptschluss" kennt, ist nicht zu schreiben.

    Statt sie zu erweitern, wird die Entscheidung des Professors gelesen:
    Ist er im Dienst, IST es eine Fachfrage. Er hat mehr Wissen als eine
    Wortliste - laufender Vorgang, verlangter Modus, Lernprofil.
    """

    frage = "Welche Ursachen hatte der Investiturstreit?"
    assert not _regel(frage), "Die Wortliste faengt den Eigennamen wider Erwarten."
    assert _regel(frage, _PROFESSOR), (
        "Der Professor ist im Dienst, und trotzdem werden die eigenen "
        "Quellen nicht befragt - dann bringt die Funktion nichts."
    )


def test_bei_nachrichten_gelten_die_nachrichtenhaeuser():
    """Ein Archivportal beantwortet keine Frage nach den News von heute."""

    assert not _regel("Gib mir die aktuellen News aus dem Iran-Krieg", _PROFESSOR)
    assert braucht_aktuelles("Gib mir die aktuellen News aus dem Iran-Krieg")


def test_ein_befehl_loest_gar_nichts_aus():
    assert not _regel("Oeffne den Browser")


# --- Die Domaenen aus den Favoriten ---------------------------------------------------


def test_aus_einer_adresse_wird_eine_domaene():
    assert _domaene("https://www.dhi-roma.it/de/bibliothek.html") == "dhi-roma.it"
    assert _domaene("http://kvk.bibliothek.kit.edu:8080/such") == "kvk.bibliothek.kit.edu"


def test_alltagsseiten_zaehlen_nicht_als_fachquelle(monkeypatch):
    """Sonst recherchiert der Orb im Videodienst."""

    from backend.research import eigene_quellen as modul

    class _F:
        def __init__(self, url, ordner=""):
            self.url = url
            self.folder_path = ordner

    monkeypatch.setattr(
        modul, "read_bookmarks", lambda **_: [], raising=False
    )
    import backend.research.browser_bookmarks as bb

    monkeypatch.setattr(
        bb,
        "read_bookmarks",
        lambda **_: [
            _F("https://youtube.com/watch?v=1", "Videos"),
            _F("https://www.google.com/", "Sonstiges"),
            _F("https://www.dhi-roma.it/a", "Wissenschaft"),
            _F("https://www.dhi-roma.it/b", "Wissenschaft"),
            _F("https://kvk.bibliothek.kit.edu/x", "Wissenschaft"),
        ],
    )
    domaenen = eigene_domaenen(hoechstens=5)
    assert "youtube.com" not in domaenen
    assert "google.com" not in domaenen
    assert domaenen[0] == "dhi-roma.it", (
        "Die haeufigste Fachdomaene steht nicht vorn: " + str(domaenen)
    )
    assert "kvk.bibliothek.kit.edu" in domaenen


def test_ein_ordner_grenzt_ein(monkeypatch):
    import backend.research.browser_bookmarks as bb

    class _F:
        def __init__(self, url, ordner):
            self.url = url
            self.folder_path = ordner

    monkeypatch.setattr(
        bb,
        "read_bookmarks",
        lambda **_: [
            _F("https://shop.example.com/a", "Einkauf"),
            _F("https://archiv.example.org/b", "Wissenschaft / Archive"),
        ],
    )
    assert eigene_domaenen(ordner="Wissenschaft") == ["archiv.example.org"]


# --- Mehrere Haeuser ------------------------------------------------------------------


def test_die_haeuser_werden_getrennt_gehalten(monkeypatch):
    """Zusammengeworfen waere die Herkunft weg - und darum geht es hier."""

    def _suche(anfrage, limit=6):
        wirt = anfrage.split("site:")[-1]
        return [{"titel": f"Meldung von {wirt}", "url": f"https://{wirt}/1",
                 "beschreibung": ""}]

    monkeypatch.setattr(web_tools, "search_web", _suche)
    quellen = [
        {"name": "BBC", "einschraenkung": "site:bbc.com"},
        {"name": "Al Jazeera", "einschraenkung": "site:aljazeera.com"},
    ]
    gesammelt = asyncio.run(web_tools.mehrquellensuche("Nahost", quellen))
    assert set(gesammelt) == {"BBC", "Al Jazeera"}
    assert "bbc.com" in gesammelt["BBC"][0]["url"]
    assert "aljazeera.com" in gesammelt["Al Jazeera"][0]["url"]


def test_eine_stumme_quelle_reisst_die_anderen_nicht_mit(monkeypatch):
    def _suche(anfrage, limit=6):
        if "aljazeera" in anfrage:
            raise RuntimeError("abgewiesen")
        return [{"titel": "Da", "url": "https://bbc.com/1", "beschreibung": ""}]

    monkeypatch.setattr(web_tools, "search_web", _suche)
    gesammelt = asyncio.run(
        web_tools.mehrquellensuche(
            "Nahost",
            [
                {"name": "BBC", "einschraenkung": "site:bbc.com"},
                {"name": "Al Jazeera", "einschraenkung": "site:aljazeera.com"},
            ],
        )
    )
    assert list(gesammelt) == ["BBC"]


def test_die_herkunft_steht_in_der_gegenueberstellung():
    gegenueber = web_tools.quellen_gegenueberstellen(
        {
            "Al Jazeera (QA)": [
                {"titel": "Eine Meldung", "url": "https://aljazeera.com/1",
                 "beschreibung": "Kurz."}
            ]
        }
    )
    assert "[Al Jazeera (QA)]" in gegenueber
    assert "aljazeera.com" in gegenueber


def test_der_orb_wird_zum_vergleichen_aufgefordert():
    """Nebeneinanderstellen genuegt nicht - der Unterschied ist die Auskunft."""

    import inspect

    quelle = inspect.getsource(Orchestrator._vorab_mehrquellen)
    assert "unterscheiden" in quelle
    assert "Nenne die Häuser" in quelle or "Haeuser" in quelle


def test_eine_einzige_quelle_wird_nicht_als_vergleich_ausgegeben():
    """Sonst hiesse "Gegenueberstellung", was gar keine ist."""

    import inspect

    quelle = inspect.getsource(Orchestrator._vorab_mehrquellen)
    assert "len(gesammelt) < 2" in quelle
