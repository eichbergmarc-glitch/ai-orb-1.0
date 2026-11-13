"""Vorlesung in Abschnitten auch auf dem Handy (12.11.2026)."""

from __future__ import annotations

import asyncio
import types

from backend.runtime import Runtime
from backend.studium.vorlesungs_session import VorlesungsSession


def _runtime(tmp_path):
    r = object.__new__(Runtime)
    r.voice = types.SimpleNamespace(_vorlesung=VorlesungsSession(tmp_path / "v.json", max_abschnitte=3))
    gefragt = []

    async def process(text, spoken=False, on_speech=None):
        gefragt.append(text)
        return types.SimpleNamespace(response=f"Abschnitt {len(gefragt)} über Philosophie.",
                                     already_spoken=False)

    r.cognitive = types.SimpleNamespace(process=process)
    import collections

    r._sprechauftraege = collections.OrderedDict()
    r.AUFTRAEGE_MERKEN = 50
    r._loop = None
    r._stimme_in_der_cloud = lambda: True

    async def anlegen(stuecke):
        return "auftrag"

    r._auftrag_anlegen = anlegen
    r._fuers_sprechen = lambda text, grenze: (text, False)
    r._stuecke_bilden = lambda text: [text]
    return r, gefragt


def test_start_weiter_pause(tmp_path):
    r, gefragt = _runtime(tmp_path)
    erstes = asyncio.run(r._geraet_beantworten("Halte mir eine Vorlesung über Philosophie"))
    assert erstes["vorlesung_weiter"] is True
    assert "[AI-ORB:VORLESUNG]" in gefragt[0]

    zweites = asyncio.run(r.vorlesung_weiter_vom_geraet())
    assert zweites["vorlesung_weiter"] is True and "Abschnitt 2" in gefragt[1]

    pause = asyncio.run(r._geraet_beantworten("Pause"))
    assert "pausiert" in pause["antwort"] and not pause.get("vorlesung_weiter")
    assert not r.voice._vorlesung.aktiv

    weiter = asyncio.run(r._geraet_beantworten("weiter"))
    assert weiter["vorlesung_weiter"] is False  # Abschnitt 3 von 3 war der letzte
    assert "Abschnitt 3" in gefragt[2]


def test_normale_frage_bleibt_normal(tmp_path):
    r, gefragt = _runtime(tmp_path)
    ergebnis = asyncio.run(r._geraet_beantworten("Wie spät ist es?"))
    assert gefragt == ["Wie spät ist es?"] and ergebnis["vorlesung_weiter"] is False


def test_antwort_am_pc(tmp_path):
    r, gefragt = _runtime(tmp_path)
    gesagt = []

    async def say(text, emotion=""):
        gesagt.append(text)
        return True

    r.voice.say = say

    async def ablauf():
        ergebnis = await r._geraet_beantworten("Wie spät ist es?", ausgabe_pc=True)
        assert r.pc_spricht() or gesagt
        await r._pc_sprechaufgabe
        return ergebnis

    ergebnis = asyncio.run(ablauf())
    assert ergebnis["am_pc"] is True and ergebnis["teile"] == 0 and ergebnis["auftrag"] == ""
    assert gesagt == ["Abschnitt 1 über Philosophie."]
    assert not r.pc_spricht()


def test_befehl_ausgabe_umschalten():
    assert Runtime._befehl_erkennen("Hey Synapse, antworte am PC.") == "ausgabe_pc"
    assert Runtime._befehl_erkennen("Antworte hier") == "ausgabe_hier"
    assert Runtime._befehl_erkennen("Antworte mir zur Philosophie") == ""


def test_offene_antwort_beginnt_mit_dem_ersten_satz(tmp_path):
    """13.11.2026: Das Handy bekommt den Auftrag, sobald der erste Satz steht."""

    r, _ = _runtime(tmp_path)
    freigabe = None

    async def process(text, spoken=False, on_speech=None):
        await on_speech("Erster Satz.")
        await freigabe.wait()
        await on_speech("Zweiter Satz.")
        return types.SimpleNamespace(response="Erster Satz. Zweiter Satz.", already_spoken=True)

    r.cognitive = types.SimpleNamespace(process=process)

    async def ablauf():
        nonlocal freigabe
        freigabe = asyncio.Event()
        ergebnis = await r._geraet_beantworten("Wie spät ist es?")
        assert ergebnis["offen"] is True and ergebnis["teile"] == -1
        auftrag = ergebnis["auftrag"]
        assert r.sprechstueck(auftrag, 1)[0] == "kommt"
        assert r.auftrag_ende(auftrag)["stand"] == "offen"
        freigabe.set()
        for _ in range(20):
            await asyncio.sleep(0)
        ende = r.auftrag_ende(auftrag)
        assert ende["stand"] == "fertig" and ende["teile"] == 2
        assert ende["antwort"] == "Erster Satz. Zweiter Satz."
        assert r.sprechstueck(auftrag, 2)[0] == "weg"

    asyncio.run(ablauf())
