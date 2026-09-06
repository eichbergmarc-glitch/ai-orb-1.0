"""Das Aktuellhalten der Wissenslandkarte.

Der Auftrag des Benutzers vom 20.08.2026, wörtlich: „Der Orb muss sich
regelmässig auf dem aktuellen Wissensstand aller Themenbereiche halten,
aktuelle Publikationen kennen und ebenfalls in sein Gedächtnis aufnehmen.
Nur so wird er ein richtiger Professor."

Geprüft wird ohne Netz - die Sandbox hat keines. Die Quellen sind darum
austauschbar gebaut, und die Tests stecken eigene hinein, die sich wie
OpenAlex und Crossref verhalten: mit Funden, mit Wiederholungen, mit
Ausfällen. Das Auswahlverfahren, die Ablage und der Weg ins Gedächtnis
sind damit vollständig prüfbar; ob die echten Adressen antworten, zeigt
im Zweifel SUCHE-PRUEFEN.bat auf dem Rechner des Benutzers.
"""

from __future__ import annotations

import time
import uuid

import pytest

from backend.studium.aktualisierung import Aktualisierung, suchbegriff_fuer
from backend.studium.landkarte import feld
from backend.utils.paths import get_data_dir


def _quelle(*funde):
    """Baut eine Quelle, die feste Funde liefert und Aufrufe zählt."""

    def suchen(query, *, seit, limit=5):
        suchen.aufrufe.append({"query": query, "seit": seit})
        return [dict(f) for f in funde][:limit]

    suchen.aufrufe = []
    return suchen


def _kaputt(query, *, seit, limit=5):
    raise OSError("Tunnel connection failed: 403 Forbidden")


@pytest.fixture
def ablage():
    name = f"studium/test-aktuell-{uuid.uuid4().hex}.json"
    yield name
    (get_data_dir() / name).unlink(missing_ok=True)


FUND_A = {"titel": "Neue Arbeit zur Benrather Linie",
          "url": "https://doi.org/10.1/abc",
          "beschreibung": "Zeitschrift für Dialektologie · 2026-07-01"}
FUND_B = {"titel": "Corpus study of German sound shift",
          "url": "https://doi.org/10.1/xyz",
          "beschreibung": "Journal of Linguistics · 2026-06-12"}


# --- Der Suchbegriff ---------------------------------------------------------


def test_der_suchbegriff_nimmt_kern_und_fachbegriffe():
    thema = feld("sprachwissenschaft").thema("swi-lautverschiebung")
    begriff = suchbegriff_fuer(thema)
    assert "Lautverschiebung" in begriff
    assert "Affrikate" in begriff
    # Und keine Ueberschriften-Floskeln.
    thema2 = feld("sprachwissenschaft").thema("swi-was-ist-das")
    assert "nicht ist" not in suchbegriff_fuer(thema2)


# --- Auffrischen -------------------------------------------------------------


def test_neue_funde_werden_abgelegt_und_wiedergefunden(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A), _quelle(FUND_B)))
    lauf = ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")

    assert len(lauf.neue) == 2
    funde = ak.neues_zu("sprachwissenschaft", "swi-lautverschiebung")
    assert {f["url"] for f in funde} == {FUND_A["url"], FUND_B["url"]}
    assert all(f.get("gefunden_am") for f in funde)


def test_bekanntes_wird_nicht_doppelt_gezaehlt(ablage):
    # Beim zweiten Lauf liefern die Quellen dieselben Arbeiten - das ist
    # der Normalfall, denn Kataloge vergessen nichts. Neu ist daran nichts.
    ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A),), abstand_tage=0.25)
    erster = ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    zweiter = ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    assert len(erster.neue) == 1
    assert zweiter.neue == []
    assert len(ak.neues_zu("sprachwissenschaft", "swi-lautverschiebung")) == 1


def test_der_erste_blick_reicht_ein_jahr_zurueck_danach_nur_bis_zuletzt(ablage):
    quelle = _quelle()
    ak = Aktualisierung(ablage, quellen=(quelle,))
    ak.auffrischen("sprachwissenschaft", "swi-morphem")

    erster_seit = quelle.aufrufe[0]["seit"]
    vor_jahr = time.strftime("%Y", time.gmtime(time.time() - 300 * 86400))
    assert erster_seit.startswith(vor_jahr) or erster_seit < time.strftime("%Y-%m-%d")

    ak2 = Aktualisierung(ablage, quellen=(quelle,), abstand_tage=0.25)
    ak2.auffrischen("sprachwissenschaft", "swi-morphem")
    zweiter_seit = quelle.aufrufe[-1]["seit"]
    assert zweiter_seit == time.strftime("%Y-%m-%d", time.gmtime())


def test_ein_quellenausfall_stoppt_die_andere_nicht(ablage):
    ak = Aktualisierung(ablage, quellen=(_kaputt, _quelle(FUND_B)))
    lauf = ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    assert [f["url"] for f in lauf.neue] == [FUND_B["url"]]
    assert lauf.fehler == ""


def test_bei_totalausfall_geht_der_kreislauf_trotzdem_weiter(ablage):
    # Sonst haemmerte er bei einer Netzstoerung im Takt auf dasselbe
    # Thema ein, statt es spaeter wieder zu versuchen.
    ak = Aktualisierung(ablage, quellen=(_kaputt, _kaputt))
    lauf = ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    assert "403" in lauf.fehler
    assert ak.naechstes() != ("sprachwissenschaft", "swi-lautverschiebung") or \
        ak.naechstes() is None or ak.naechstes()[1] != "swi-lautverschiebung"


def test_ein_unbekanntes_thema_bricht_nichts(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A),))
    lauf = ak.auffrischen("sprachwissenschaft", "gibtsnicht")
    assert lauf.fehler == "unbekanntes Thema"


# --- Die Auswahl -------------------------------------------------------------


def test_die_beruehrten_themen_kommen_zuerst(ablage):
    # Aktuell gehalten wird vor allem, woran der Benutzer arbeitet - sein
    # Fossilien-Thema vor einem, das er nie angefasst hat.
    ak = Aktualisierung(ablage, quellen=(_quelle(),))
    ziel = ak.naechstes({"geografie": {"geo-gesteine"}})
    assert ziel == ("geografie", "geo-gesteine")


def test_nach_der_pruefung_kommt_das_naechste_dran(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(),))
    beruehrte = {"geografie": {"geo-gesteine"}}
    erstes = ak.naechstes(beruehrte)
    ak.auffrischen(*erstes)
    zweites = ak.naechstes(beruehrte)
    assert zweites is not None and zweites != erstes


def test_ohne_faelliges_thema_ist_ruhe(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(),), abstand_tage=7)
    while (ziel := ak.naechstes()) is not None:
        ak.auffrischen(*ziel)
    assert ak.naechstes() is None
    assert ak.status()["themen_geprueft"] >= 45


# --- Ins Gedächtnis ----------------------------------------------------------


def test_neue_funde_landen_im_gedaechtnis(ablage):
    # Woertlich verlangt: "aktuelle Publikationen kennen und ebenfalls in
    # sein Gedaechtnis aufnehmen."
    gemerkt = []
    ak = Aktualisierung(
        ablage, quellen=(_quelle(FUND_A, FUND_B),),
        merken=lambda text, quelle: gemerkt.append((text, quelle)),
    )
    ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    assert len(gemerkt) == 2
    assert "Benrather Linie" in gemerkt[0][0]
    assert gemerkt[0][1] == FUND_A["url"]


def test_hoechstens_zwei_je_lauf_ins_gedaechtnis(ablage):
    viele = [
        {"titel": f"Arbeit {i}", "url": f"https://doi.org/10.1/{i}",
         "beschreibung": "X · 2026"}
        for i in range(5)
    ]
    gemerkt = []
    ak = Aktualisierung(
        ablage, quellen=(_quelle(*viele),),
        merken=lambda text, quelle: gemerkt.append(text),
    )
    ak.auffrischen("sprachwissenschaft", "swi-morphem")
    assert len(gemerkt) == 2


def test_ein_kaputtes_gedaechtnis_verhindert_keine_ablage(ablage):
    def _reisst(text, quelle):
        raise RuntimeError("Gedächtnis nicht erreichbar")

    ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A),), merken=_reisst)
    lauf = ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    assert len(lauf.neue) == 1


# --- Der Hinweis ans Modell --------------------------------------------------


def test_der_hinweis_sagt_dass_die_funde_ungeprueft_sind(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A),))
    ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    hinweis = ak.hinweis("sprachwissenschaft", "swi-lautverschiebung")
    assert "UNGEPRÜFT" in hinweis
    assert FUND_A["titel"] in hinweis
    assert FUND_A["url"] in hinweis


def test_ohne_funde_kein_hinweis(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(),))
    ak.auffrischen("sprachwissenschaft", "swi-morphem")
    assert ak.hinweis("sprachwissenschaft", "swi-morphem") == ""


def test_der_stand_ueberlebt_einen_neustart(ablage):
    ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A),))
    ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
    wieder = Aktualisierung(ablage, quellen=(_quelle(),))
    assert wieder.neues_zu("sprachwissenschaft", "swi-lautverschiebung")


# --- Die Anschlüsse ----------------------------------------------------------


def test_die_laufzeit_startet_den_kreislauf():
    from pathlib import Path

    quelle = Path("backend/runtime.py").read_text(encoding="utf-8")
    assert "_aktualisierungsschleife" in quelle
    assert "studium.aktualisierung" in quelle
    assert "asyncio.to_thread" in quelle  # urllib gehoert nicht in die Loop
    # Und der Weg ins Gedaechtnis ist verdrahtet.
    assert "merken=lambda text, quelle: self.memory.remember(" in quelle


def test_das_werkzeug_forschung_aktuell_existiert():
    from backend.studium.lernstand import Lernstand
    from backend.tools.studium_tools import build_studium_tools

    name = f"studium/test-{uuid.uuid4().hex}.json"
    aktuell = f"studium/test-aktuell-{uuid.uuid4().hex}.json"
    try:
        werkzeuge = build_studium_tools(
            Lernstand(dateiname=name),
            Aktualisierung(aktuell, quellen=(_quelle(),)),
        )
        namen = {t.name for t in werkzeuge}
        assert "forschung_aktuell" in namen
    finally:
        (get_data_dir() / name).unlink(missing_ok=True)
        (get_data_dir() / aktuell).unlink(missing_ok=True)


def test_wissen_nachsehen_zeigt_die_funde(ablage):
    import asyncio

    from backend.studium.lernstand import Lernstand
    from backend.tools.studium_tools import Nachsehen

    name = f"studium/test-{uuid.uuid4().hex}.json"
    try:
        ak = Aktualisierung(ablage, quellen=(_quelle(FUND_A),))
        ak.auffrischen("sprachwissenschaft", "swi-lautverschiebung")
        werkzeug = Nachsehen(Lernstand(dateiname=name), ak)
        ergebnis = asyncio.run(
            werkzeug.execute({"thema": "Zweite Lautverschiebung"})
        )
        assert "NEUES AUS DER FORSCHUNG" in str(ergebnis.output)
        assert FUND_A["titel"] in str(ergebnis.output)
    finally:
        (get_data_dir() / name).unlink(missing_ok=True)
