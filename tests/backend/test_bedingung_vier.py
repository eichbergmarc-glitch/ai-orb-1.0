"""Übergabebedingung 4 - und die Frage, ob sie sich austricksen lässt.

Die Bedingung lautet: Der Schüler muss in der Blindbewertung überwiegend
als gleichwertig gelten. Vier Wege führen daran vorbei, wenn man nicht
aufpasst, und für jeden steht hier ein Test:

* die Quote stimmt, aber es gab gar keine Urteile,
* der Bewerter war kaputt und lieferte nur Unlesbares,
* die Urteilsdatei ist leer,
* jemand trägt eine Quote von Hand ein.

Der letzte Fall ist kein Test, sondern eine Bauweise: Der Wert entsteht in
``pruefergebnisse_bilden`` ausschliesslich aus abgelegten Blindurteilen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.lernen.blindbewertung import UNMOEGLICH
from backend.lernen.paarvergleich import LEHRER, SCHUELER, Urteilsablage
from backend.lernen.uebergabe import Pruefergebnis, Uebergabe


def _speicher() -> Any:
    class _Speicher:
        def __init__(self) -> None:
            self._daten: dict[str, Any] = {"kategorien": {}}

        def get(self, schluessel: str, standard: Any = None) -> Any:
            return self._daten.get(schluessel, standard)

        def set(self, schluessel: str, wert: Any, *, persist: bool = True) -> None:
            self._daten[schluessel] = wert

    return _Speicher()


def _ergebnis(**abweichung: Any) -> Pruefergebnis:
    werte: dict[str, Any] = {
        "kategorie": "alltagsdialog",
        "lauf": "T1",
        "erfolgsquote_lehrer": 0.90,
        "erfolgsquote_schueler": 0.89,
        "halluzination_lehrer": 0.02,
        "halluzination_schueler": 0.01,
        "sicherheitsfehler_lehrer": 0.0,
        "sicherheitsfehler_schueler": 0.0,
        "werkzeugquote_schueler": 0.99,
        "blindurteil_gleichwertig": 0.75,
        "blindurteile_auswertbar": 12,
        "positionswechselrate": 0.0,
        "regressionstests_bestanden": True,
    }
    werte.update(abweichung)
    return Pruefergebnis(**werte)


# --- Die vier Fälle aus der Aufgabenstellung ------------------------------


def test_erfuelltes_blindurteil_laesst_bedingung_vier_bestehen():
    bestanden, grund = Uebergabe(store=_speicher()).bewerte(_ergebnis())

    assert bestanden is True, grund


def test_nicht_erfuelltes_blindurteil_laesst_bedingung_vier_scheitern():
    bestanden, grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(blindurteil_gleichwertig=0.30)
    )

    assert bestanden is False
    assert "Blindbewertung" in grund
    assert "30" in grund or "0.30" in grund or "30,00" in grund


def test_technisch_unmoegliche_blindbewertung_besteht_nicht():
    """Der Bewerter hat geantwortet, aber nie ein lesbares Urteil geliefert."""

    bestanden, grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(blindurteil_gleichwertig=1.0, blindurteile_auswertbar=0)
    )

    assert bestanden is False
    assert "positionsstabile" in grund


def test_ohne_jedes_blindurteil_besteht_nichts_durch_vorgabewerte():
    """Der Vorgabewert 0 darf niemals als 'bestanden' durchgehen."""

    frisch = Pruefergebnis(
        kategorie="alltagsdialog",
        lauf="T1",
        erfolgsquote_lehrer=0.9,
        erfolgsquote_schueler=0.9,
        halluzination_lehrer=0.0,
        halluzination_schueler=0.0,
        sicherheitsfehler_lehrer=0.0,
        sicherheitsfehler_schueler=0.0,
        werkzeugquote_schueler=1.0,
        regressionstests_bestanden=True,
    )

    bestanden, grund = Uebergabe(store=_speicher()).bewerte(frisch)

    assert frisch.blindurteil_gleichwertig == 0.0
    assert frisch.blindurteile_auswertbar == 0
    assert bestanden is False
    assert "positionsstabile" in grund


def test_eine_knappe_mehrheit_reicht_nicht():
    """Die Schwelle ist 'ueber der Haelfte', nicht 'genau die Haelfte'."""

    bestanden, _grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(blindurteil_gleichwertig=0.5)
    )

    assert bestanden is False


# --- Was daraus für die Übergabe folgt -------------------------------------


def test_ohne_blindurteile_wird_keine_kategorie_uebergeben():
    uebergabe = Uebergabe(store=_speicher())

    for lauf in ("T1", "T2", "T3"):
        uebergabe.eintragen(
            _ergebnis(lauf=lauf, blindurteil_gleichwertig=0.0, blindurteile_auswertbar=0)
        )

    stand = uebergabe.stand("alltagsdialog")
    assert stand.stufe == 0
    assert "positionsstabile" in stand.letzter_grund


def test_mit_echten_blindurteilen_steigt_die_stufe_nach_drei_laeufen():
    uebergabe = Uebergabe(store=_speicher())

    for lauf in ("T1", "T2", "T3"):
        uebergabe.eintragen(_ergebnis(lauf=lauf))

    assert uebergabe.stand("alltagsdialog").stufe == 10
    assert uebergabe.anteil_lokal("alltagsdialog") == 10


def test_ein_ausfall_der_blindbewertung_wirft_die_stufe_zurueck():
    """Wer heute nicht mehr messen kann, behält nicht einfach seine Stufe."""

    uebergabe = Uebergabe(store=_speicher())
    for lauf in ("T1", "T2", "T3"):
        uebergabe.eintragen(_ergebnis(lauf=lauf))
    assert uebergabe.stand("alltagsdialog").stufe == 10

    uebergabe.eintragen(_ergebnis(lauf="T4", blindurteile_auswertbar=0))

    assert uebergabe.stand("alltagsdialog").stufe == 0


# --- Der Weg von den Urteilen zur Zahl -------------------------------------


def test_die_quote_kommt_aus_der_urteilsdatei_und_nirgends_sonst(tmp_path: Path, monkeypatch):
    """Von der abgelegten Zeile bis in das Prüfergebnis - ohne Handeingriff."""

    from backend.lernen import messen as messmodul
    from backend.lernen.messwerte import Messreihe, Messung

    # Ueber die vorgesehene Umleitung, nicht ueber Flickwerk: So laeuft es
    # im Messlauf auch (siehe messwerkzeuge.messumgebung).
    from backend.utils.paths import DATA_DIRECTORY_ENVIRONMENT_VARIABLE

    monkeypatch.setenv(DATA_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path))

    reihe = Messreihe("T9")
    for modell in ("claude_code", "ollama"):
        for nummer in (1, 2):
            reihe.anhaengen(
                Messung(
                    katalog_version="1.1.0",
                    katalog_pruefsumme="x",
                    lauf="T9",
                    kategorie="alltagsdialog",
                    fall=f"alltag_0{nummer}",
                    modell=modell,
                    erfolg=True,
                    werkzeuge_erfolgreich=True,
                )
            )

    urteile = Urteilsablage()
    zeilen = [
        {"lauf": "T9", "kategorie": "alltagsdialog", "kennung": "a",
         "zustand": "stabil_gleich", "gewinner_herkunft": "",
         "etikett_normal": "gleich", "etikett_getauscht": "gleich"},
        {"lauf": "T9", "kategorie": "alltagsdialog", "kennung": "b",
         "zustand": "stabil_schueler", "gewinner_herkunft": SCHUELER,
         "etikett_normal": "A", "etikett_getauscht": "B"},
        {"lauf": "T9", "kategorie": "alltagsdialog", "kennung": "c",
         "zustand": "stabil_lehrer", "gewinner_herkunft": LEHRER,
         "etikett_normal": "B", "etikett_getauscht": "A"},
        {"lauf": "T9", "kategorie": "alltagsdialog", "kennung": "d",
         "zustand": UNMOEGLICH, "gewinner_herkunft": "",
         "etikett_normal": UNMOEGLICH, "etikett_getauscht": "A"},
    ]
    with urteile.pfad.open("a", encoding="utf-8") as datei:
        for zeile in zeilen:
            datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")

    ergebnisse = messmodul.pruefergebnisse_bilden(
        lauf="T9", lehrer="claude_code", schueler="ollama"
    )
    passend = [e for e in ergebnisse if e.kategorie == "alltagsdialog"]

    assert passend, "keine Kategorie gebildet"
    ergebnis = passend[0]
    # 2 von 4 nicht unterlegen (Gleichstand + Schuelersieg), 3 auswertbar.
    assert ergebnis.blindurteil_gleichwertig == pytest.approx(0.5)
    assert ergebnis.blindurteile_auswertbar == 3
    assert ergebnis.erfolgsquote_lehrer == 1.0
    assert ergebnis.erfolgsquote_schueler == 1.0


def test_ohne_urteilsdatei_bleibt_die_quote_null(tmp_path: Path, monkeypatch):
    from backend.lernen import messen as messmodul
    from backend.lernen.messwerte import Messreihe, Messung

    from backend.utils.paths import DATA_DIRECTORY_ENVIRONMENT_VARIABLE

    monkeypatch.setenv(DATA_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path))

    reihe = Messreihe("T8")
    for modell in ("claude_code", "ollama"):
        reihe.anhaengen(
            Messung(
                katalog_version="1.1.0",
                katalog_pruefsumme="x",
                lauf="T8",
                kategorie="alltagsdialog",
                fall="alltag_01",
                modell=modell,
                erfolg=True,
                werkzeuge_erfolgreich=True,
            )
        )

    ergebnisse = messmodul.pruefergebnisse_bilden(
        lauf="T8", lehrer="claude_code", schueler="ollama"
    )
    ergebnis = [e for e in ergebnisse if e.kategorie == "alltagsdialog"][0]

    assert ergebnis.blindurteil_gleichwertig == 0.0
    assert ergebnis.blindurteile_auswertbar == 0
    bestanden, grund = Uebergabe(store=_speicher()).bewerte(ergebnis)
    assert bestanden is False
    assert "positionsstabile" in grund


def test_im_code_steht_keine_feste_gleichwertigkeitsquote():
    """Der Wert darf nirgends gesetzt werden - nur berechnet."""

    quelle = Path("backend/lernen/messen.py").read_text(encoding="utf-8")
    for verboten in (
        "blindurteil_gleichwertig=1.0",
        "blindurteil_gleichwertig=0.9",
        "blindurteil_gleichwertig=0.8",
        "blindurteil_gleichwertig=0.75",
    ):
        assert verboten not in quelle
    assert 'werte.get("gleichwertig", 0.0)' in quelle


# --- Bedingung 6: die Regressionslage kommt aus einem echten Bericht -------


def test_die_regressionslage_kommt_aus_dem_abnahmebericht(tmp_path: Path, monkeypatch):
    """Kein fester Wert, sondern der Bericht eines echten Testlaufs."""

    from backend.lernen import messen as messmodul

    protokolle = tmp_path / "logs"
    protokolle.mkdir()
    monkeypatch.setattr("backend.utils.paths.get_logs_dir", lambda: protokolle)

    (protokolle / "offline-abnahme-2026-09-01-100000.json").write_text(
        json.dumps({"bestanden": False, "grund": "rote Tests"}), encoding="utf-8"
    )
    assert messmodul.regressionslage()[0] is False

    (protokolle / "offline-abnahme-2026-09-01-200000.json").write_text(
        json.dumps({"bestanden": True, "grund": "alles gruen"}), encoding="utf-8"
    )
    gruen, beleg = messmodul.regressionslage()
    assert gruen is True
    assert beleg == "offline-abnahme-2026-09-01-200000.json"


def test_ohne_abnahmebericht_gilt_nicht_bestanden(tmp_path: Path, monkeypatch):
    from backend.lernen import messen as messmodul

    leer = tmp_path / "leer"
    leer.mkdir()
    monkeypatch.setattr("backend.utils.paths.get_logs_dir", lambda: leer)

    gruen, beleg = messmodul.regressionslage()

    assert gruen is False
    assert "keine" in beleg.lower()


def test_ein_unlesbarer_bericht_gilt_nicht_als_bestanden(tmp_path: Path, monkeypatch):
    from backend.lernen import messen as messmodul

    protokolle = tmp_path / "logs2"
    protokolle.mkdir()
    (protokolle / "offline-abnahme-2026-09-01-100000.json").write_text(
        "kein JSON", encoding="utf-8"
    )
    monkeypatch.setattr("backend.utils.paths.get_logs_dir", lambda: protokolle)

    assert messmodul.regressionslage()[0] is False


# --- Die Bewerterschranke: ein instabiler Richter entscheidet nichts ------


def test_ein_positionsinstabiler_bewerter_verhindert_jede_entscheidung():
    """Der Satz, der dann fallen muss - wörtlich."""

    bestanden, grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(blindurteil_gleichwertig=0.9, positionswechselrate=0.5)
    )

    assert bestanden is False
    assert "KEINE BELASTBARE UEBERGABEENTSCHEIDUNG" in grund
    assert "BLINDBEWERTER NICHT AUSREICHEND STABIL" in grund


def test_die_schranke_gilt_auch_bei_perfekter_quote():
    """Eine hohe Quote von einem untauglichen Richter ist keine hohe Quote."""

    bestanden, grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(blindurteil_gleichwertig=1.0, positionswechselrate=0.31)
    )

    assert bestanden is False
    assert "NICHT AUSREICHEND STABIL" in grund


def test_knapp_unter_der_schranke_geht_durch():
    bestanden, grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(positionswechselrate=0.29)
    )

    assert bestanden is True, grund


def test_zu_wenige_stabile_urteile_reichen_nicht():
    bestanden, grund = Uebergabe(store=_speicher()).bewerte(
        _ergebnis(blindurteile_auswertbar=1)
    )

    assert bestanden is False
    assert "positionsstabile" in grund


def test_ein_instabiler_bewerter_hebt_keine_stufe():
    uebergabe = Uebergabe(store=_speicher())

    for lauf in ("T1", "T2", "T3"):
        uebergabe.eintragen(_ergebnis(lauf=lauf, positionswechselrate=0.6))

    stand = uebergabe.stand("alltagsdialog")
    assert stand.stufe == 0
    assert "NICHT AUSREICHEND STABIL" in stand.letzter_grund


# --- Das Gesamturteil einer Serie -----------------------------------------


def test_ein_instabiler_bewerter_ergibt_kein_belastbares_urteil():
    from backend.lernen.messen import KEIN_BELASTBARES_URTEIL, gesamturteil_bilden

    urteil = gesamturteil_bilden(
        {"paare": 19, "positionsinstabil": 11, "positionswechselrate": 0.58},
        {"alltagsdialog": {"stufe": 0}},
    )

    assert urteil["urteil"] == KEIN_BELASTBARES_URTEIL
    assert urteil["bewerter_stabil"] is False
    assert "58" in urteil["grund"]


def test_ohne_blindurteile_ergibt_sich_ebenfalls_kein_urteil():
    from backend.lernen.messen import KEIN_BELASTBARES_URTEIL, gesamturteil_bilden

    urteil = gesamturteil_bilden({"paare": 0, "positionswechselrate": 0.0}, {})

    assert urteil["urteil"] == KEIN_BELASTBARES_URTEIL


def test_ein_stabiler_bewerter_ohne_erfuellte_bedingungen_heisst_nicht_uebergeben():
    from backend.lernen.messen import gesamturteil_bilden

    urteil = gesamturteil_bilden(
        {"paare": 19, "positionsinstabil": 3, "positionswechselrate": 0.16},
        {"alltagsdialog": {"stufe": 0}, "gedaechtnis": {"stufe": 0}},
    )

    assert urteil["urteil"] == "NICHT UEBERGEBEN"
    assert urteil["bewerter_stabil"] is True
    assert urteil["uebergeben"] == {}


def test_erst_ein_stabiler_bewerter_kann_eine_uebergabe_ausweisen():
    from backend.lernen.messen import gesamturteil_bilden

    urteil = gesamturteil_bilden(
        {"paare": 19, "positionsinstabil": 2, "positionswechselrate": 0.10},
        {"alltagsdialog": {"stufe": 10}, "gedaechtnis": {"stufe": 0}},
    )

    assert urteil["urteil"] == "UEBERGEBEN"
    assert urteil["uebergeben"] == {"alltagsdialog": 10}


def test_die_bewerterschranke_kommt_vor_der_uebergabe():
    """Auch eine erreichte Stufe wird von einem untauglichen Richter entwertet."""

    from backend.lernen.messen import KEIN_BELASTBARES_URTEIL, gesamturteil_bilden

    urteil = gesamturteil_bilden(
        {"paare": 19, "positionsinstabil": 12, "positionswechselrate": 0.63},
        {"alltagsdialog": {"stufe": 25}},
    )

    assert urteil["urteil"] == KEIN_BELASTBARES_URTEIL
    assert urteil["uebergeben"] == {}
