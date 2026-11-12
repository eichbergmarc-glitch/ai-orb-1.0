"""Fahrplan und Weckwort (12.11.2026): Zugfrage ergab wirre Antworten."""

from __future__ import annotations

import asyncio

from backend.tools import fahrplan_tools
from backend.tools.fahrplan_tools import (
    VerbindungSuchenTool,
    fahrplan_anfrage,
    verbindungen_formatieren,
)
from backend.tools.web_tools import suchbegriff_aus, weckwort_entfernen

MARCS_FRAGE = (
    "Hey Synapse, ich möchte, dass du mir eine Bus- und Zugverbindung suchst von "
    "Melchnau-Giuch nach Ostermundigen-Bern. Abfahrt frühestens heute 16:45 Uhr."
)

ANTWORT = {
    "from": {"name": "Melchnau, Giuch"},
    "to": {"name": "Ostermundigen"},
    "connections": [
        {
            "from": {"departure": "2026-11-12T16:52:00+0100"},
            "to": {"arrival": "2026-11-12T18:01:00+0100"},
            "duration": "00d01:09:00",
            "transfers": 1,
            "sections": [
                {
                    "journey": {"category": "B", "number": "56"},
                    "departure": {"departure": "2026-11-12T16:52:00+0100",
                                  "station": {"name": "Melchnau, Giuch"}},
                    "arrival": {"arrival": "2026-11-12T17:10:00+0100",
                                "station": {"name": "Langenthal"}},
                },
                {"journey": None, "walk": {"duration": 120}},
                {
                    "journey": {"category": "IR", "number": "17"},
                    "departure": {"departure": "2026-11-12T17:17:00+0100",
                                  "platform": "3", "station": {"name": "Langenthal"}},
                    "arrival": {"arrival": "2026-11-12T18:01:00+0100",
                                "station": {"name": "Ostermundigen"}},
                },
            ],
        }
    ],
}


def test_weckwort_wird_entfernt():
    assert weckwort_entfernen("Hey Synapse, wie wird das Wetter?") == "wie wird das Wetter?"
    assert weckwort_entfernen("Synapse: Licht an") == "Licht an"
    assert weckwort_entfernen("Hallo Synapse") == "Hallo Synapse"  # sonst bliebe nichts
    assert weckwort_entfernen("Was ist Razer Synapse?") == "Was ist Razer Synapse?"


def test_suchbegriff_ohne_weckwort():
    assert "synapse" not in suchbegriff_aus(MARCS_FRAGE)


def test_marcs_frage_wird_erkannt():
    args = fahrplan_anfrage(MARCS_FRAGE)
    assert args == {"von": "Melchnau-Giuch", "nach": "Ostermundigen-Bern", "zeit": "16:45"}


def test_weitere_formulierungen():
    assert fahrplan_anfrage("Wann fährt der nächste Zug von Bern nach Zürich?") == {
        "von": "Bern", "nach": "Zürich"}
    args = fahrplan_anfrage("Ich muss morgen um 9 Uhr in Basel sein, Zug von Langenthal nach Basel")
    assert args["zeit"] == "09:00" and args["datum"] == "morgen" and args["ankunft"] is True
    assert fahrplan_anfrage("Wie wird das Wetter in Bern?") is None
    assert fahrplan_anfrage("Ich fahre von Bern nach Thun") is None  # kein OeV-Wort


def test_formatierung():
    text = verbindungen_formatieren(ANTWORT)
    assert "Ab 16:52, an 18:01 (1 h 09 min, 1x umsteigen)" in text
    assert "IR 17 17:17 ab Langenthal (Gleis/Kante 3), an Ostermundigen 18:01" in text


class _Antwort:
    def __init__(self, daten):
        self._daten = daten

    def raise_for_status(self):
        pass

    def json(self):
        return self._daten


def test_werkzeug_versucht_schreibweisen(monkeypatch):
    gefragt = []

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, params):
            gefragt.append((params["from"], params["to"], params.get("time")))
            if params["from"] == "Melchnau, Giuch":
                return _Antwort(ANTWORT)
            return _Antwort({"connections": []})

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    ergebnis = asyncio.run(VerbindungSuchenTool().execute(
        {"von": "Melchnau-Giuch", "nach": "Ostermundigen-Bern", "zeit": "16:45"}))
    assert ergebnis.ok, ergebnis.error
    assert "16:52" in ergebnis.output
    assert gefragt[0] == ("Melchnau-Giuch", "Ostermundigen-Bern", "16:45")
    assert any(f == "Melchnau, Giuch" for f, _, _ in gefragt)


def test_werkzeug_meldet_fehler_ehrlich(monkeypatch):
    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, params):
            raise OSError("keine Verbindung")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    ergebnis = asyncio.run(VerbindungSuchenTool().execute({"von": "Bern", "nach": "Thun"}))
    assert not ergebnis.ok and "nicht erreichbar" in ergebnis.error
    assert fahrplan_tools._datum("morgen")


def test_verhoertes_weckwort_und_unklare_orte():
    from backend.tools.fahrplan_tools import ist_fahrplanfrage

    text = "Hey Snaps, Zugverbindung Melchnau-Giuch aus der Mundigen, heute 16:45 Abfahrt."
    assert weckwort_entfernen(text).startswith("Zugverbindung")
    assert weckwort_entfernen("Snapchat öffnen") == "Snapchat öffnen"
    assert fahrplan_anfrage(text) is None and ist_fahrplanfrage(text)
    assert not ist_fahrplanfrage("Wie wird das Wetter morgen, nimmst du den Zug?")
    assert fahrplan_anfrage("Zugverbindung Bern nach Thun um 7:30") == {
        "von": "Bern", "nach": "Thun", "zeit": "07:30"}


def test_internetverbindung_ist_keine_fahrplanfrage():
    from backend.tools.fahrplan_tools import ist_fahrplanfrage

    assert not ist_fahrplanfrage("Meine Internetverbindung ist langsam")
    assert not ist_fahrplanfrage("Stell eine Verbindung zum Drucker her")
