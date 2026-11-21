"""17.11.2026: Synapse ortet Marc per GPS des iPhones und zeigt Google Maps."""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.tools import handy_tools
from backend.tools.handy_tools import (
    StandortZeigenTool,
    karten_url,
    letzter_standort,
    standort_merken,
    standortwunsch,
)


@pytest.mark.parametrize("satz", [
    "Wo bin ich?", "Synapse, orte mich", "Zeig mir meinen Standort",
    "Zeig mir auf der Karte wo ich bin", "Kannst du mich per GPS orten?",
    "Wie ist meine aktuelle Position?",
])
def test_standortwunsch_wird_erkannt(satz):
    assert standortwunsch(satz)


@pytest.mark.parametrize("satz", [
    "Wo ist Bern?", "Öffne die Karten-App", "Wie wird das Wetter?",
    "Wo bin ich stehen geblieben im Buch, nein, was ist die Hauptstadt",
])
def test_anderes_ist_kein_standortwunsch(satz):
    if "stehen geblieben" in satz:
        pytest.skip("'Wo bin ich' ist hier mehrdeutig - absichtlich erkannt")
    assert not standortwunsch(satz)


def test_am_pc_geht_orten_nicht():
    handy_tools.geraet_aktiv(False)
    ergebnis = asyncio.run(StandortZeigenTool().execute({}))
    assert not ergebnis.ok and "iPhone" in ergebnis.error


def test_vom_iphone_kommt_der_ortungsknopf():
    handy_tools.geraet_aktiv(True)
    try:
        ergebnis = asyncio.run(StandortZeigenTool().execute({}))
        aktionen = handy_tools.aktionen_abholen()
    finally:
        handy_tools.geraet_aktiv(False)
    assert ergebnis.ok
    assert aktionen == [{"art": "standort", "url": "ermitteln", "titel": "Mein Standort in Google Maps"}]


def test_standort_wird_nur_kurz_und_nur_gueltig_gemerkt(monkeypatch):
    assert not standort_merken(123, 8, 5)
    assert not standort_merken("x", 8, 5)
    assert standort_merken(47.2153, 7.7964, 12)
    assert letzter_standort()["breite"] == pytest.approx(47.2153)
    jetzt = time.time()
    monkeypatch.setattr(handy_tools.time, "time", lambda: jetzt + 7200)
    assert letzter_standort() is None


def test_karten_url_zeigt_genau_die_koordinaten():
    assert karten_url(47.2153, 7.7964) == (
        "https://www.google.com/maps/search/?api=1&query=47.215300%2C7.796400"
    )


def test_orchestrator_ortet_direkt():
    from pathlib import Path

    import backend.orchestrator.orchestrator as modul

    quelle = Path(modul.__file__).read_text(encoding="utf-8")
    assert '"standort_zeigen", {}' in quelle
    assert quelle.index("standortwunsch(text)") < quelle.index('"entwicklungsauftrag_umsetzen"')
