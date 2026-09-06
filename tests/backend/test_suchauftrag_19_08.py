"""Der Suchauftrag darf den Suchbegriff nicht auffressen.

Am 19.08.2026 verlangte der Benutzer viermal dasselbe::

    10:13:16  "Jo, suche noch einmal über Markus Gabriel, was du findest."
    10:14:59  "Hallo Orb, führe erneut eine Suche durch zu Markus Gabriel."
    10:15:41  "Hallo Orb, führe erneut eine Suche durch zu Markus Gabriel."
    10:17:31  "Hallo Orb, führe eine neue Suche zu Markus Gabriel
               Neurealismus durch."

Die ersten drei ergaben Treffer zu **Sigmar** Gabriel, Peter Gabriel und
Mission Impossible. Erst der vierte - der ein zusätzliches Fachwort
enthielt - fand den richtigen Philosophen.

Nicht die Suchmaschine war schuld. Der Suchbegriff lautete::

    "führe erneut durch markus gabriel"

Der Auftrag stand mit im Suchtext und verdünnte den Namen. Dazu kam ein
zweiter Fall: Wo der Benutzer nach dem eigenen Fehler des Orb fragte,
sprang die Vorabsuche an, weil das Wort "Suche" im Satz stand - und legte
dem Modell "Numerische lineare Algebra" vor.
"""

from __future__ import annotations

import pytest

from backend.orchestrator.orchestrator import (
    braucht_aktuelles,
    braucht_werkzeuge,
    ist_selbstdiagnose,
)
from backend.tools.web_tools import suchbegriff_aus


# --- Der Suchbegriff -------------------------------------------------------


@pytest.mark.parametrize(
    "satz",
    [
        "Jo, suche noch einmal über Markus Gabriel, was du findest.",
        "Hallo Orb, führe erneut eine Suche durch zu Markus Gabriel.",
        "führe erneut eine suche durch zu markus gabriel",
        "Führe eine neue Suche zu Markus Gabriel durch",
    ],
)
def test_der_name_bleibt_allein_uebrig(satz):
    begriff = suchbegriff_aus(satz)
    assert begriff.split() == ["markus", "gabriel"], begriff


def test_ein_fachwort_bleibt_erhalten():
    begriff = suchbegriff_aus(
        "Hallo Orb, führe eine neue Suche zu Markus Gabriel Neurealismus durch."
    )
    assert "neurealismus" in begriff
    assert "markus" in begriff and "gabriel" in begriff
    assert "führe" not in begriff and "durch" not in begriff


def test_die_anrede_gehoert_nie_in_die_anfrage():
    for satz in ("Hallo Orb, was ist die Julikrise?",
                 "Hey Orb, suche nach dem Neurealismus"):
        assert "orb" not in suchbegriff_aus(satz).split(), satz


def test_ein_gewoehnlicher_suchauftrag_bleibt_unversehrt():
    # Die Bereinigung darf nicht so weit gehen, dass das Thema verschwindet.
    begriff = suchbegriff_aus("Suche nach den aktuellen Nachrichten aus der Ukraine")
    assert "ukraine" in begriff
    assert "nachrichten" in begriff


def test_ausgabeanweisung_wird_nicht_zum_suchthema():
    begriff = suchbegriff_aus(
        "Suche nach Schweizer Privathaftpflichtversicherungen im Vergleich "
        "und nenne mir zwei passende Quellen."
    )
    assert begriff.split() == [
        "schweizer", "privathaftpflichtversicherungen", "vergleich"
    ]


# --- Die Frage nach dem eigenen Fehler -------------------------------------


@pytest.mark.parametrize(
    "satz",
    [
        "Führe eine Fehleranalyse durch und finde heraus, warum die Suche nicht funktioniert.",
        "Finde den Fehler, warum die Suche nicht funktioniert.",
        "Finde den Fehler in deinem Code.",
        "Führe einen Funktionstest durch",
        "Prüfe deine Werkzeuge",
    ],
)
def test_eine_frage_nach_dem_eigenen_fehler_loest_keine_netzsuche_aus(satz):
    assert ist_selbstdiagnose(satz), satz
    assert not braucht_aktuelles(satz), satz


@pytest.mark.parametrize(
    "satz",
    [
        "Führe eine Fehleranalyse durch und finde heraus, warum die Suche nicht funktioniert.",
        "Finde den Fehler in deinem Code.",
    ],
)
def test_aber_werkzeuge_braucht_sie_erst_recht(satz):
    # Ohne Werkzeuge bleibt dem Modell nur die Behauptung - im Protokoll
    # stand woertlich "Ich hab den Code durchsucht und ...", ohne dass eine
    # einzige Datei geoeffnet worden waere.
    assert braucht_werkzeuge(satz), satz


@pytest.mark.parametrize(
    "satz",
    [
        "Hallo Orb, führe erneut eine Suche durch zu Markus Gabriel.",
        "Suche nach den aktuellen Nachrichten aus der Ukraine",
        "Was ist heute in der Welt passiert?",
    ],
)
def test_ein_echter_suchauftrag_wird_nicht_faelschlich_gestoppt(satz):
    assert not ist_selbstdiagnose(satz), satz
    assert braucht_aktuelles(satz), satz
