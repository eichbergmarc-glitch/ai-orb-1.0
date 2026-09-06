"""Zahlen als Zahlen vergleichen - der Fall werkzeug_03.

Im echten Messlauf vom 1. September 2026 rechneten beide Modelle korrekt
aus, dass ein Tag 86400 Sekunden hat. Beide fielen durch, weil die
Erwartung die Zeichenkette ``86400`` suchte und die Antworten die Zahl
deutsch als ``86.400`` schrieben.

Die Gegenprobe ist genauso wichtig wie der Fall selbst: Eine falsche Zahl
muss falsch bleiben, und ``3,5`` darf nicht plötzlich 35 sein.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.lernen.bewertung import (
    deterministisch_pruefen,
    zahl_deuten,
    zahl_kommt_vor,
    zahlen_aus,
)
from backend.lernen.faehigkeitskatalog import Pruefstueck


def _stueck(*erwartet: str, verboten: tuple[str, ...] = ()) -> Pruefstueck:
    return Pruefstueck(
        kennung="probe",
        kategorie="werkzeugwahl",
        aufgabe="Rechne etwas aus.",
        art="deterministisch",
        erwartet=tuple(erwartet),
        verboten=verboten,
    )


# --- Tausendertrennung ----------------------------------------------------


@pytest.mark.parametrize(
    "geschrieben",
    [
        "86400",
        "86.400",
        "86 400",
        "86 400",   # geschuetztes Leerzeichen
        "86 400",   # schmales geschuetztes Leerzeichen
        "86 400",   # schmales Leerzeichen
        "86'400",        # Schweizer Schreibweise
    ],
)
def test_dieselbe_zahl_in_vielen_schreibweisen(geschrieben: str):
    assert zahl_deuten(geschrieben) == Decimal("86400")


@pytest.mark.parametrize(
    "antwort",
    [
        "Ein Tag hat 86400 Sekunden.",
        "Ein Tag hat 86.400 Sekunden.",
        "Ein Tag hat 86 400 Sekunden.",
        "Ein Tag hat 86 400 Sekunden.",
        "Ein Tag hat 86 400 Sekunden.",
        "Das Ergebnis ist 86'400.",
    ],
)
def test_der_pruefstein_erkennt_die_richtige_antwort(antwort: str):
    urteil = deterministisch_pruefen(_stueck("86400"), antwort)

    assert urteil.punkte == urteil.hoechstpunkte, urteil.begruendung


def test_grosse_zahlen_mit_mehreren_gruppen():
    assert zahl_deuten("1.234.567") == Decimal("1234567")
    assert zahl_deuten("1 234 567") == Decimal("1234567")


# --- Dezimalzahlen dürfen nicht kaputtgehen -------------------------------


def test_das_komma_bleibt_das_dezimalzeichen():
    assert zahl_deuten("3,5") == Decimal("3.5")
    assert zahl_deuten("0,25") == Decimal("0.25")
    assert zahl_deuten("3,5") != Decimal("35")


def test_ein_punkt_ohne_dreiergruppe_ist_ein_dezimalpunkt():
    assert zahl_deuten("3.14") == Decimal("3.14")
    assert zahl_deuten("0.5") == Decimal("0.5")


def test_punkt_und_komma_zusammen_sind_deutsch():
    assert zahl_deuten("1.234,56") == Decimal("1234.56")


def test_eine_dezimalzahl_wird_richtig_wiedergefunden():
    urteil = deterministisch_pruefen(_stueck("3,5"), "Das ergibt 3.5 Stunden.")
    assert urteil.punkte == urteil.hoechstpunkte

    urteil = deterministisch_pruefen(_stueck("3,5"), "Das ergibt 35 Stunden.")
    assert urteil.punkte < urteil.hoechstpunkte


# --- Falsches bleibt falsch -----------------------------------------------


@pytest.mark.parametrize("falsch", ["86000", "8640", "864000", "86.401", "86,4"])
def test_eine_falsche_zahl_besteht_nicht(falsch: str):
    urteil = deterministisch_pruefen(_stueck("86400"), f"Ein Tag hat {falsch} Sekunden.")

    assert urteil.punkte < urteil.hoechstpunkte


def test_gar_keine_zahl_besteht_nicht():
    urteil = deterministisch_pruefen(_stueck("86400"), "Ein Tag hat viele Sekunden.")

    assert urteil.punkte < urteil.hoechstpunkte


def test_eine_verbotene_zahl_wird_auch_in_deutscher_schreibweise_erkannt():
    urteil = deterministisch_pruefen(
        _stueck("86400", verboten=("3600",)),
        "Ein Tag hat 86.400 Sekunden, eine Stunde 3.600.",
    )

    assert urteil.punkte < urteil.hoechstpunkte
    assert "unerlaubt" in urteil.begruendung


# --- Text bleibt Text ------------------------------------------------------


def test_woerter_werden_weiterhin_als_zeichenkette_geprueft():
    assert zahl_kommt_vor("Bundesstadt", "Bern ist die Bundesstadt.") is None

    urteil = deterministisch_pruefen(_stueck("Bern"), "Die Antwort ist Bern.")
    assert urteil.punkte == urteil.hoechstpunkte


def test_eine_jahreszahl_im_text_bleibt_eine_zahl():
    """1789 ist eine Zahl - und muss als solche gefunden werden."""

    urteil = deterministisch_pruefen(_stueck("1789"), "Die Revolution begann 1789.")
    assert urteil.punkte == urteil.hoechstpunkte


def test_zahlen_aus_liest_mehrere_zahlen():
    zahlen = zahlen_aus("Ein Tag hat 86.400 Sekunden, eine Stunde 3.600, ein Jahr 365 Tage.")

    assert Decimal("86400") in zahlen
    assert Decimal("3600") in zahlen
    assert Decimal("365") in zahlen


def test_kein_text_ist_keine_zahl():
    for nichts in ("", "   ", "keine Zahl", "-", ".", ","):
        assert zahl_deuten(nichts) is None


def test_die_loesung_haengt_nicht_an_86400():
    """Allgemein, nicht auf den einen Fall zugeschnitten."""

    for wert, geschrieben in (
        ("1000", "1.000"),
        ("2500000", "2.500.000"),
        ("42", "42"),
        ("999", "999"),
        ("10000", "10 000"),
    ):
        urteil = deterministisch_pruefen(_stueck(wert), f"Das Ergebnis lautet {geschrieben}.")
        assert urteil.punkte == urteil.hoechstpunkte, f"{wert} vs {geschrieben}"
