"""Tests der Lehrer-Schüler-Architektur.

Der Kern dieser Datei ist eine einzige Behauptung, die überprüfbar sein
muss: **Eine Kategorie geht nicht an das lokale Modell, solange nicht alle
sechs Bedingungen in drei unabhängigen Läufen erfüllt sind.** Jede Bedingung
hat hier ihren eigenen Test, der sie einzeln verletzt.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from backend.lernen.bewertung import (
    Teilurteil,
    deterministisch_pruefen,
    rubrik_pruefen,
    werkzeuge_pruefen,
    zusammenfuehren,
)
from backend.lernen.faehigkeitskatalog import KATEGORIEN, Pruefstueck, katalog
from backend.lernen.kategorien import kategorie_fuer
from backend.lernen.messwerte import Messreihe, Messung, zusammenfassen
from backend.lernen.schattenlauf import (
    FEHLERKLASSEN,
    Lehre,
    Schattenbuch,
    anonymisieren,
    fehlerklasse_bestimmen,
)
from backend.lernen.uebergabe import STUFEN, Pruefergebnis, Uebergabe
from backend.utils.store import JsonStore


# --- Der Katalog ------------------------------------------------------------


def test_jede_kategorie_hat_pruefstuecke() -> None:
    """Eine Kategorie ohne Aufgaben koennte man nicht messen."""

    k = katalog()
    for kennung, titel in KATEGORIEN:
        assert k.fuer(kennung), f"'{titel}' hat kein einziges Pruefstueck"


def test_die_pruefsumme_haengt_am_inhalt() -> None:
    """Wer die Messlatte verschiebt, aendert diese Zahl - das ist der Sinn."""

    from backend.lernen.faehigkeitskatalog import Pruefkatalog

    k = katalog()
    verschoben = Pruefkatalog(
        version=k.version,
        stuecke=k.stuecke[:-1]
        + (
            Pruefstueck(
                "verschoben", "alltagsdialog", "Sag irgendwas.", "rubrik",
                kriterien=("sagt irgendwas",),
            ),
        ),
    )

    assert verschoben.pruefsumme != k.pruefsumme


def test_offline_untaugliche_stuecke_sind_gekennzeichnet() -> None:
    k = katalog()
    nicht_offline = [s for s in k.stuecke if not s.offline_loesbar]

    assert nicht_offline, "ohne Netz ist nicht alles loesbar - das muss dastehen"
    assert all(s.kennung for s in nicht_offline)


# --- Die Bewertung ----------------------------------------------------------


def test_deterministische_pruefung_braucht_kein_modell() -> None:
    stueck = Pruefstueck("t", "alltagsdialog", "17 mal 3?", "deterministisch",
                         erwartet=("51",))

    gut = deterministisch_pruefen(stueck, "Das ergibt 51.")
    schlecht = deterministisch_pruefen(stueck, "Das ergibt 53.")

    assert gut.anteil == 1.0
    assert schlecht.anteil < 1.0
    assert "fehlt" in schlecht.begruendung


def test_werkzeugpruefung_erkennt_ein_fehlendes_werkzeug() -> None:
    stueck = Pruefstueck("t", "werkzeugwahl", "Suche etwas.", "werkzeug",
                         werkzeuge=("internet_suchen",))

    ohne = werkzeuge_pruefen(stueck, [], False)
    mit = werkzeuge_pruefen(stueck, ["internet_suchen"], True)

    assert ohne.anteil < 1.0
    assert "nicht gelaufen" in ohne.begruendung
    assert mit.anteil == 1.0


def test_ein_befangenes_urteil_zaehlt_nicht_in_die_punkte() -> None:
    """Sonst waere die ganze Messung ein Selbstgespraech."""

    ehrlich = Teilurteil("deterministisch", "deterministisch", 1.0, 1.0, "")
    selbstlob = Teilurteil("schueler", "rubrik", 4.0, 4.0, "", befangen=True)

    gesamt = zusammenfuehren([ehrlich, selbstlob])

    assert gesamt.hoechstpunkte == pytest.approx(2.0)
    assert "2.0 von 2.0" in gesamt.begruendung


def test_ohne_bewerter_sagt_die_rubrik_das_auch() -> None:
    """Ein Ergebnis ohne Bewerter darf nicht wie ein Urteil aussehen."""

    stueck = Pruefstueck("t", "alltagsdialog", "Sag etwas.", "rubrik",
                         kriterien=("sagt etwas", "auf Deutsch"))

    urteil = rubrik_pruefen(stueck, "Ein hinreichend langer deutscher Satz.",
                            bewerter="keiner")

    assert urteil.bewerter == "ersatzpruefung"
    assert "keine fachliche Aussage" in urteil.begruendung


def test_eine_rubrik_mit_bewerter_zaehlt_kriterium_fuer_kriterium() -> None:
    stueck = Pruefstueck("t", "alltagsdialog", "Sag etwas.", "rubrik",
                         kriterien=("auf Deutsch", "hoechstens drei Saetze"))

    def _urteil(kriterium: str, antwort: str) -> tuple[bool, str]:
        return kriterium == "auf Deutsch", "geprueft"

    urteil = rubrik_pruefen(stueck, "Guten Tag.", bewerter="pruefer",
                            urteil=_urteil)

    assert urteil.punkte == 1.0
    assert urteil.hoechstpunkte == 2.0
    assert "+ auf Deutsch" in urteil.begruendung


# --- Die Uebergabe: jede Bedingung einzeln ---------------------------------


def _uebergabe(tmp_path: Path) -> Uebergabe:
    return Uebergabe(
        store=JsonStore.__new__(JsonStore)
        if False
        else _speicher(tmp_path)
    )


def _speicher(tmp_path: Path) -> Any:
    class _Speicher:
        def __init__(self) -> None:
            self._daten: dict[str, Any] = {"kategorien": {}}

        def get(self, schluessel: str, standard: Any = None) -> Any:
            return self._daten.get(schluessel, standard)

        def set(self, schluessel: str, wert: Any, *, persist: bool = True) -> None:
            self._daten[schluessel] = wert

    return _Speicher()


def _gutes_ergebnis(**abweichung: Any) -> Pruefergebnis:
    werte: dict[str, Any] = {
        "kategorie": "alltagsdialog",
        "lauf": "L1",
        "erfolgsquote_lehrer": 0.90,
        "erfolgsquote_schueler": 0.89,
        "halluzination_lehrer": 0.02,
        "halluzination_schueler": 0.01,
        "sicherheitsfehler_lehrer": 0.0,
        "sicherheitsfehler_schueler": 0.0,
        "werkzeugquote_schueler": 0.99,
        "blindurteil_gleichwertig": 0.6,
        # Ohne auswertbare Urteile faellt Bedingung 4 - und das ist richtig
        # so: Eine Quote ohne Urteile dahinter ist keine Quote.
        "blindurteile_auswertbar": 12,
        "regressionstests_bestanden": True,
    }
    werte.update(abweichung)
    return Pruefergebnis(**werte)


def test_ein_guter_lauf_besteht(tmp_path: Path) -> None:
    bestanden, grund = _uebergabe(tmp_path).bewerte(_gutes_ergebnis())

    assert bestanden is True, grund


@pytest.mark.parametrize(
    "abweichung, erwarteter_grund",
    [
        ({"erfolgsquote_schueler": 0.80}, "Rueckstand"),
        ({"halluzination_schueler": 0.10}, "Halluzinationen"),
        ({"sicherheitsfehler_schueler": 0.01}, "Sicherheitsfehler"),
        ({"werkzeugquote_schueler": 0.90}, "Werkzeugquote"),
        ({"blindurteil_gleichwertig": 0.40}, "Blindbewertung"),
        ({"regressionstests_bestanden": False}, "Regressionstests"),
    ],
)
def test_jede_einzelne_bedingung_kann_den_lauf_verhindern(
    tmp_path: Path, abweichung: dict[str, Any], erwarteter_grund: str
) -> None:
    """Sechs Bedingungen, sechs Wege, den Lauf zu verlieren."""

    bestanden, grund = _uebergabe(tmp_path).bewerte(_gutes_ergebnis(**abweichung))

    assert bestanden is False
    assert erwarteter_grund.lower() in grund.lower(), grund


def test_erst_drei_unabhaengige_laeufe_heben_die_stufe(tmp_path: Path) -> None:
    uebergabe = _uebergabe(tmp_path)

    for lauf in ("L1", "L2"):
        stand = uebergabe.eintragen(_gutes_ergebnis(lauf=lauf))
        assert stand.stufe == 0, "zwei Laeufe reichen nicht"

    stand = uebergabe.eintragen(_gutes_ergebnis(lauf="L3"))

    assert stand.stufe == STUFEN[1]
    assert stand.letzte_stabile_stufe == 0
    assert stand.bestandene_laeufe == []


def test_derselbe_lauf_zaehlt_nur_einmal(tmp_path: Path) -> None:
    """Sonst genuegte es, denselben Lauf dreimal einzutragen."""

    uebergabe = _uebergabe(tmp_path)
    for _ in range(3):
        stand = uebergabe.eintragen(_gutes_ergebnis(lauf="L1"))

    assert stand.stufe == 0


def test_eine_verschlechterung_faellt_auf_die_letzte_stabile_stufe(
    tmp_path: Path,
) -> None:
    uebergabe = _uebergabe(tmp_path)
    for lauf in ("L1", "L2", "L3"):
        uebergabe.eintragen(_gutes_ergebnis(lauf=lauf))
    assert uebergabe.stand("alltagsdialog").stufe == 10

    stand = uebergabe.eintragen(
        _gutes_ergebnis(lauf="L4", erfolgsquote_schueler=0.5)
    )

    assert stand.stufe == 0
    assert "nicht bestanden" in stand.letzter_grund


def test_manuelles_zuruecksetzen_wirkt_sofort(tmp_path: Path) -> None:
    uebergabe = _uebergabe(tmp_path)
    for lauf in ("L1", "L2", "L3"):
        uebergabe.eintragen(_gutes_ergebnis(lauf=lauf))

    stand = uebergabe.zuruecksetzen("alltagsdialog", "im Betrieb aufgefallen")

    assert stand.stufe == 0
    assert "im Betrieb aufgefallen" in stand.letzter_grund


def test_ohne_messung_ist_der_anteil_null(tmp_path: Path) -> None:
    """Die wichtigste Voreinstellung des ganzen Pakets."""

    assert _uebergabe(tmp_path).anteil_lokal("programmierung") == 0


# --- Das Routing ------------------------------------------------------------


def _manager(anteil: int) -> Any:
    from backend.orchestrator.provider_manager import ProviderManager

    class _Uebergabe:
        def anteil_lokal(self, kategorie: str) -> int:
            return anteil

    manager = ProviderManager.__new__(ProviderManager)
    manager._providers = {"claude_code": object(), "ollama": object()}
    manager._operating_mode = "auto"
    manager._fallback_name = "ollama"
    manager._local_routing_config = {"main_provider": "ollama"}
    manager._uebergabe = _Uebergabe()
    manager._uebergabe_zaehler = {}
    return manager


def test_ohne_uebergabe_bleibt_alles_bei_claude() -> None:
    assert _manager(0)._lokal_uebernimmt("alltagsdialog") == ""


def test_bei_hundert_prozent_uebernimmt_immer_das_lokale_modell() -> None:
    manager = _manager(100)

    assert all(
        manager._lokal_uebernimmt("alltagsdialog") == "ollama" for _ in range(5)
    )


def test_ein_anteil_wird_nachvollziehbar_ausgelost() -> None:
    """Nicht zufaellig: derselbe Fall faellt im Test immer gleich aus."""

    manager = _manager(25)
    treffer = [bool(manager._lokal_uebernimmt("alltagsdialog")) for _ in range(20)]

    assert 0 < sum(treffer) < 20, "weder immer noch nie"
    manager2 = _manager(25)
    assert treffer == [
        bool(manager2._lokal_uebernimmt("alltagsdialog")) for _ in range(20)
    ]


def test_ohne_kategorie_wird_nicht_umgeleitet() -> None:
    assert _manager(100)._lokal_uebernimmt("") == ""


# --- Der Schattenlauf -------------------------------------------------------


@pytest.mark.parametrize(
    "roh, verschwunden",
    [
        ("Schreib an marc@example.com", "marc@example.com"),
        ("Mein Schluessel ist sk-ABCDEF0123456789XYZ", "sk-ABCDEF0123456789XYZ"),
        ("Der Pfad ist /home/marc/geheim", "/home/marc"),
        ("Siehe https://example.com/geheim", "https://example.com"),
    ],
)
def test_personenbezug_verschwindet_vor_der_speicherung(
    roh: str, verschwunden: str
) -> None:
    sauber = anonymisieren(roh)

    assert verschwunden not in sauber
    assert "<" in sauber


def test_die_fehlerklassen_sind_abstrakt_und_zaehlbar() -> None:
    klasse = fehlerklasse_bestimmen(
        verlangte_werkzeuge=["internet_suchen"],
        schueler_werkzeuge=[],
        schueler_aufruf_ungueltig=False,
        schueler_punkte=1.0,
        lehrer_punkte=2.0,
        schueler_halluzination=False,
    )

    assert klasse == "werkzeug_nicht_aufgerufen"
    assert klasse in FEHLERKLASSEN


def test_der_schattenlauf_ist_standardmaessig_aus() -> None:
    """Er kostet Rechenzeit - und die ist bei diesem Orb das knappste Gut."""

    buch = Schattenbuch(store=_speicher(Path(".")))

    assert buch.aktiv is False
    assert buch.darf_laufen() is False


def test_das_schattenbuch_speichert_keinen_wortlaut() -> None:
    speicher = _speicher(Path("."))
    buch = Schattenbuch(store=speicher)
    buch._aktiv = True

    buch.eintragen(
        Lehre(
            kategorie="werkzeugwahl",
            fehlerklasse="werkzeug_nicht_aufgerufen",
            aufgabenmuster="Suche die Wohnung von marc@example.com",
            verbesserungsvorschlag="Werkzeugbeschreibung schaerfen",
        )
    )

    abgelegt = speicher.get("lehren")[0]
    assert "marc@example.com" not in abgelegt["aufgabenmuster"]
    assert abgelegt["fehlerklasse"] == "werkzeug_nicht_aufgerufen"


# --- Messwerte --------------------------------------------------------------


def test_messungen_werden_nur_angehaengt(tmp_path: Path) -> None:
    reihe = Messreihe("L1", verzeichnis=tmp_path)
    reihe.anhaengen(
        Messung(
            katalog_version="1.0.0", katalog_pruefsumme="abc", lauf="L1",
            kategorie="alltagsdialog", fall="a1", modell="ollama", erfolg=True,
        )
    )
    reihe.anhaengen(
        Messung(
            katalog_version="1.0.0", katalog_pruefsumme="abc", lauf="L1",
            kategorie="alltagsdialog", fall="a2", modell="ollama", erfolg=False,
        )
    )

    alle = reihe.alle()
    assert len(alle) == 2
    assert zusammenfassen(alle)["erfolgsquote"] == 0.5


def test_die_zusammenfassung_trennt_die_modelle(tmp_path: Path) -> None:
    reihe = Messreihe("L1", verzeichnis=tmp_path)
    for modell, erfolg in (("claude_code", True), ("ollama", False)):
        reihe.anhaengen(
            Messung(
                katalog_version="1.0.0", katalog_pruefsumme="abc", lauf="L1",
                kategorie="alltagsdialog", fall="a1", modell=modell,
                erfolg=erfolg,
            )
        )

    alle = reihe.alle()
    assert zusammenfassen(alle, modell="claude_code")["erfolgsquote"] == 1.0
    assert zusammenfassen(alle, modell="ollama")["erfolgsquote"] == 0.0


# --- Die Kategorienzuordnung ------------------------------------------------


@pytest.mark.parametrize(
    "satz, kategorie",
    [
        ("Schreib eine Python-Funktion", "programmierung"),
        ("Merk dir, dass ich Kaffee ohne Zucker trinke", "gedaechtnis"),
        ("Oeffne den Browser", "rechnerbedienung"),
        ("Ist diese Studie belastbar?", "recherche"),
        ("Wer war Immanuel Kant?", "geschichte_philosophie"),
        ("Fasse den Text zusammen", "darstellung"),
        ("Wie spaet ist es?", "werkzeugwahl"),
        ("Wie geht es dir?", "alltagsdialog"),
    ],
)
def test_anfragen_landen_in_der_richtigen_kategorie(satz: str, kategorie: str) -> None:
    assert kategorie_fuer(satz) == kategorie
