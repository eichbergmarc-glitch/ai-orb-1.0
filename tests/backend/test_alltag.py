"""Alltag (12.11.2026): Erinnerungen, Abfahrtswecker, Wetter, Briefing."""

from __future__ import annotations

import asyncio
import datetime as dt
import types

import pytest

from backend.tools import alltag_tools as a

JETZT = dt.datetime(2026, 11, 12, 13, 0)


def test_zeitangaben():
    assert a.zeitpunkt_aus("16:30", jetzt=JETZT) == dt.datetime(2026, 11, 12, 16, 30)
    assert a.zeitpunkt_aus("7 Uhr", jetzt=JETZT) == dt.datetime(2026, 11, 13, 7, 0)
    assert a.zeitpunkt_aus("16 Uhr 15", jetzt=JETZT) == dt.datetime(2026, 11, 12, 16, 15)
    assert a.zeitpunkt_aus("in 20 Minuten", jetzt=JETZT) == dt.datetime(2026, 11, 12, 13, 20)
    assert a.zeitpunkt_aus("in zwei Stunden", jetzt=JETZT) == dt.datetime(2026, 11, 12, 15, 0)
    assert a.zeitpunkt_aus("8:00", "morgen", jetzt=JETZT) == dt.datetime(2026, 11, 13, 8, 0)
    assert a.zeitpunkt_aus("9:00", "24.12.", jetzt=JETZT) == dt.datetime(2026, 12, 24, 9, 0)
    with pytest.raises(ValueError):
        a.zeitpunkt_aus("irgendwann", jetzt=JETZT)


def test_erinnerung_wird_faellig_und_angesagt(tmp_path):
    gesagt = []

    async def ansagen(text):
        gesagt.append(text)

    dienst = a.Erinnerungsdienst(tmp_path / "e.json", ansagen)
    dienst.anlegen("Hund füttern", dt.datetime.now() - dt.timedelta(minutes=1))
    dienst.anlegen("später", dt.datetime.now() + dt.timedelta(hours=1))
    assert asyncio.run(dienst.einmal_pruefen()) == 1
    assert gesagt == ["Erinnerung: Hund füttern"]
    assert [e["text"] for e in dienst.alle()] == ["später"]


def test_taeglich_und_briefing(tmp_path):
    gesagt = []

    async def ansagen(text):
        gesagt.append(text)

    async def briefing():
        return "Guten Morgen, Marc."

    dienst = a.Erinnerungsdienst(tmp_path / "e.json", ansagen)
    dienst.briefing = briefing
    dienst.anlegen(a.BRIEFING, dt.datetime.now() - dt.timedelta(minutes=1), wiederholen="taeglich")
    asyncio.run(dienst.einmal_pruefen())
    assert gesagt == ["Guten Morgen, Marc."]
    (eintrag,) = dienst.alle()
    assert dt.datetime.fromisoformat(eintrag["zeit"]) > dt.datetime.now()
    assert len(dienst.loeschen("briefing")) == 1 and dienst.alle() == []


def test_werkzeuge(tmp_path):
    dienst = a.Erinnerungsdienst(tmp_path / "e.json")
    r = asyncio.run(a.ErinnerungSetzenTool(dienst).execute({"text": "Hund", "zeit": "in 5 Minuten"}))
    assert r.ok and "Hund" in r.output
    assert "Hund" in asyncio.run(a.ErinnerungenZeigenTool(dienst).execute({})).output
    assert asyncio.run(a.ErinnerungLoeschenTool(dienst).execute({"suche": "hund"})).ok
    assert not asyncio.run(a.ErinnerungSetzenTool(dienst).execute({"text": "x", "zeit": "bald"})).ok


def test_abfahrt_erinnern(tmp_path):
    dienst = a.Erinnerungsdienst(tmp_path / "e.json")
    morgen = (dt.date.today() + dt.timedelta(days=1)).isoformat()

    async def fahrplan(parameter):
        assert parameter["isArrivalTime"] == 1 and parameter["from"] == "Melchnau, Giuch"
        return {"connections": [
            {"from": {"departure": f"{morgen}T15:19:00+0100", "station": {"name": "Melchnau, Giuch"}},
             "to": {"arrival": f"{morgen}T16:47:00+0100"},
             "sections": [{"journey": {"category": "B", "number": "51"}}]},
            {"from": {"departure": f"{morgen}T15:49:00+0100"},
             "to": {"arrival": f"{morgen}T17:17:00+0100"}, "sections": []},
        ]}

    tool = a.AbfahrtErinnernTool(dienst, heimatort="Melchnau, Giuch", abfragen=fahrplan)
    r = asyncio.run(tool.execute({"nach": "Bern", "ankunft": "17:00", "datum": "morgen"}))
    assert r.ok, r.error
    assert "B 51 ab 15:19" in r.output
    (eintrag,) = dienst.alle()
    assert eintrag["zeit"].endswith("15:09:00")


def test_wetter():
    async def holen(ort):
        return {"_ort": ort, "current": {"temperature_2m": 6.4, "weather_code": 3},
                "daily": {"time": ["a", "b"], "weather_code": [61, 0],
                          "temperature_2m_min": [2.1, 0], "temperature_2m_max": [8.6, 9],
                          "precipitation_probability_max": [70, 5]}}

    r = asyncio.run(a.WetterTool(heimatort="Melchnau", holen=holen).execute({"tage": 2}))
    assert r.output == ("In Melchnau jetzt 6 Grad, bedeckt. Heute: leichter Regen, 2 bis 9 Grad, "
                        "Regenrisiko 70 Prozent. Morgen: klar, 0 bis 9 Grad, Regenrisiko 5 Prozent.")


def test_tagesueberblick_mit_ausfaellen():
    async def wetter(ort):
        raise OSError("offline")

    class Gmail:
        async def read_unread(self, limit=5):
            return [types.SimpleNamespace(sender='"Anna" <a@x.ch>')]

    u = a.Tagesueberblick(heimatort="Melchnau", gmail=Gmail(), wetter=wetter)
    text = asyncio.run(u.erstellen())
    assert "Marc" in text and "1 ungelesene Mails, unter anderem von Anna." in text
