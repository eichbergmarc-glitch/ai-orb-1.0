"""Erweiterungen vom 16.11.2026.

1. Uebersichten zum Ansehen: Funktionen und Vorlesungen.
2. Der Chatverlauf: jede Anfrage und Antwort, ueber Neustarts hinweg.
3. Chat auf dem ganzen Bildschirm - als Sprachbefehl.
4. Vom iPad gesprochen, am PC ausgegeben: Der Orb am Bildschirm arbeitet mit.
5. Sprechdynamik: Atem, Denkpause, Raeuspern, Schmunzeln - selten und passend.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.tools import handy_tools
from backend.tools import uebersicht_tools
from backend.tools.registry import ToolRegistry
from backend.tools.uebersicht_tools import (
    build_uebersicht_tools,
    funktionen_html,
    uebersichtswunsch,
    vorlesungen_html,
)


# --- 1. Uebersichten -------------------------------------------------------


@pytest.mark.parametrize("satz", [
    "Synapse, kannst du mir einmal sagen, was du alles für Funktionen hast?",
    "Was kannst du alles?",
    "Zeig mir deine Funktionen",
    "Welche Befehle kennst du?",
    "Mach mir eine Übersicht deiner Funktionen",
])
def test_frage_nach_den_funktionen_wird_erkannt(satz):
    assert uebersichtswunsch(satz) == "funktionen"


@pytest.mark.parametrize("satz", [
    "Welche Vorlesungen gibt es?",
    "Zeig mir eine Übersicht der möglichen Vorlesungen",
    "Zeig mir die Vorlesungsübersicht",
    "Welche Vorlesungen kannst du halten?",
])
def test_frage_nach_den_vorlesungen_wird_erkannt(satz):
    assert uebersichtswunsch(satz) == "vorlesungen"


@pytest.mark.parametrize("satz", [
    "Welche Funktionen hat die Leber?",
    "Halte mir eine Vorlesung über Sokrates",
    "Fahre mit der Vorlesung fort",
    "Was kannst du mir zu Kant sagen?",
    "Neue Vorlesung über Platon",
    "weiter",
])
def test_anderes_ist_kein_uebersichtswunsch(satz):
    assert uebersichtswunsch(satz) == ""


def test_uebersichtsfrage_startet_keine_vorlesung():
    """'Welche Vorlesungen gibt es?' will sehen, nicht hoeren."""

    from backend.studium.vorlesungs_session import VorlesungsSession

    sitzung = VorlesungsSession.__new__(VorlesungsSession)
    assert sitzung.befehl("Welche Vorlesungen gibt es?") == ""


def test_funktionsuebersicht_zeigt_nur_was_angemeldet_ist():
    registry = ToolRegistry()
    registry.register_many(build_uebersicht_tools(registry))
    seite, karten = funktionen_html(registry)

    assert karten >= 5
    assert "Chat vergrössern" in seite
    # Gmail und TIDAL sind hier nicht angemeldet - also auch nicht versprochen.
    assert "Mails lesen" not in seite
    assert "Musik abspielen" not in seite

    voll, alle = funktionen_html(None)
    assert alle > karten
    assert "Mails lesen" in voll


def test_vorlesungsuebersicht_kommt_aus_der_landkarte():
    from backend.studium import landkarte

    seite, faecher, themen = vorlesungen_html()
    assert faecher == len(landkarte.felder()) >= 1
    assert themen >= faecher
    erstes = landkarte.felder()[0].gebiete[0].themen[0].titel
    assert erstes.replace("&", "&amp;") in seite or erstes in seite
    assert "Halte mir eine Vorlesung über" in seite


def _werkzeuge(tmp_path: Path, monkeypatch):
    geoeffnet: list[Path] = []
    monkeypatch.setattr(uebersicht_tools, "_ablage", lambda name: tmp_path / name)
    monkeypatch.setattr(
        uebersicht_tools, "_im_browser_oeffnen", lambda pfad: geoeffnet.append(pfad) or True
    )
    registry = ToolRegistry()
    registry.register_many(build_uebersicht_tools(registry))
    return registry, geoeffnet


def test_am_rechner_oeffnet_sich_der_browser(tmp_path, monkeypatch):
    registry, geoeffnet = _werkzeuge(tmp_path, monkeypatch)
    handy_tools.geraet_aktiv(False)

    ergebnis = asyncio.run(registry.get("vorlesungen_zeigen").execute({}))

    assert ergebnis.ok and "Bildschirm" in ergebnis.output
    assert geoeffnet == [tmp_path / "vorlesungen.html"]
    assert (tmp_path / "vorlesungen.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_vom_handy_gefragt_kommt_ein_knopf_aufs_handy(tmp_path, monkeypatch):
    registry, geoeffnet = _werkzeuge(tmp_path, monkeypatch)
    handy_tools.geraet_aktiv(True)
    try:
        ergebnis = asyncio.run(registry.get("funktionen_zeigen").execute({}))
        aktionen = handy_tools.aktionen_abholen()
    finally:
        handy_tools.geraet_aktiv(False)

    assert ergebnis.ok and not geoeffnet
    assert aktionen and aktionen[0]["art"] == "dokument"


def test_vom_ipad_gefragt_mit_ausgabe_am_pc_erscheint_es_am_bildschirm(tmp_path, monkeypatch):
    registry, geoeffnet = _werkzeuge(tmp_path, monkeypatch)
    handy_tools.geraet_aktiv(True, ausgabe_pc=True)
    try:
        assert handy_tools.ausgabe_am_pc()
        ergebnis = asyncio.run(registry.get("funktionen_zeigen").execute({}))
        aktionen = handy_tools.aktionen_abholen()
    finally:
        handy_tools.geraet_aktiv(False)

    assert ergebnis.ok and geoeffnet and not aktionen
    assert not handy_tools.ausgabe_am_pc()


def test_orchestrator_zeigt_die_uebersicht_vor_dem_entwicklungsauftrag():
    import backend.orchestrator.orchestrator as modul

    quelle = Path(modul.__file__).read_text(encoding="utf-8")
    assert quelle.index("uebersichtswunsch(text)") < quelle.index('"entwicklungsauftrag_umsetzen"')


# --- 2. Chatverlauf --------------------------------------------------------


def test_verlauf_ueberlebt_den_neustart(tmp_path):
    from backend.system.chatverlauf import Chatverlauf

    datei = tmp_path / "verlauf.json"
    verlauf = Chatverlauf(datei)
    zeile = verlauf.eintragen("user", "Wie wird das Wetter?", quelle="gesprochen")
    verlauf.eintragen("orb", "Morgen bewölkt.")

    assert zeile and zeile["uhrzeit"] and zeile["tag"]
    wieder = Chatverlauf(datei).letzte()
    assert [z["rolle"] for z in wieder] == ["user", "orb"]
    assert wieder[0]["text"] == "Wie wird das Wetter?"


def test_verlauf_verdoppelt_nicht_und_bleibt_begrenzt(tmp_path):
    from backend.system.chatverlauf import Chatverlauf

    verlauf = Chatverlauf(tmp_path / "v.json", hoechstens=10)
    assert verlauf.eintragen("user", "Hallo") is not None
    assert verlauf.eintragen("user", "Hallo") is None
    assert verlauf.eintragen("orb", "   ") is None
    for nummer in range(30):
        verlauf.eintragen("user", f"Frage {nummer}")
    assert len(verlauf.letzte(100)) == 10
    assert verlauf.letzte(1)[0]["text"] == "Frage 29"


def test_kaputte_verlaufsdatei_ist_kein_startfehler(tmp_path):
    from backend.system.chatverlauf import Chatverlauf

    datei = tmp_path / "v.json"
    datei.write_text("{kaputt", encoding="utf-8")
    assert Chatverlauf(datei).letzte() == []


def _runtime_mit_verlauf(tmp_path):
    from backend.runtime import Runtime
    from backend.system.chatverlauf import Chatverlauf

    gemeldet: list[tuple[str, dict]] = []

    class _Bus:
        async def publish(self, name, payload=None):  # noqa: ANN001
            gemeldet.append((name, dict(payload or {})))

    class _Denkschicht:
        async def process(self, text, **_):  # noqa: ANN001
            return type("A", (), {"response": "Antwort auf " + text})()

    leer = Runtime.__new__(Runtime)
    leer.event_bus = _Bus()
    leer.cognitive = _Denkschicht()
    leer.chatverlauf = Chatverlauf(tmp_path / "v.json")
    leer._verlauf_einhaengen()
    return leer, gemeldet


def test_jede_anfrage_und_antwort_landet_im_verlauf(tmp_path):
    leer, gemeldet = _runtime_mit_verlauf(tmp_path)

    antwort = asyncio.run(leer.cognitive.process("Wie spät ist es?", spoken=True))

    assert antwort.response == "Antwort auf Wie spät ist es?"
    zeilen = leer.chatverlauf.letzte()
    assert [(z["rolle"], z["quelle"]) for z in zeilen] == [("user", "gesprochen"), ("orb", "gesprochen")]
    assert [name for name, _ in gemeldet] == ["orb.chat.message", "orb.chat.message"]


def test_regieanweisung_einer_vorlesung_steht_nicht_als_anfrage_im_verlauf(tmp_path):
    from backend.studium.vorlesungs_session import VORLESUNGS_MARKER

    leer, _ = _runtime_mit_verlauf(tmp_path)
    asyncio.run(leer.cognitive.process(VORLESUNGS_MARKER + "\nAbschnitt 2 ...", spoken=True))

    assert [z["rolle"] for z in leer.chatverlauf.letzte()] == ["orb"]


# --- 3. Chat gross und klein -----------------------------------------------


@pytest.mark.parametrize("satz,befehl", [
    ("Chat vergrössern", "chat_gross"),
    ("Chat vergrößern.", "chat_gross"),
    ("Hey Synapse, Chat auf den ganzen Bildschirm", "chat_gross"),
    ("Chatfenster maximieren", "chat_gross"),
    ("Chat verkleinern", "chat_klein"),
    ("Chat wieder klein", "chat_klein"),
    ("Chat aktivieren", "chat_auf"),
    ("Chat schliessen", "chat_zu"),
])
def test_chatbefehle(satz, befehl):
    from backend.runtime import Runtime

    assert Runtime._befehl_erkennen(satz) == befehl


def test_eine_frage_zum_chat_ist_kein_befehl():
    from backend.runtime import Runtime

    assert Runtime._befehl_erkennen("Kannst du den Chat grösser machen als sonst und mir sagen warum?") == ""


# --- 5. Sprechdynamik ------------------------------------------------------


def _dynamik():
    from backend.tts.sprechdynamik import Sprechdynamik

    return Sprechdynamik()


def test_kurze_auskunft_bekommt_keine_zutat():
    dynamik = _dynamik()
    dynamik.neue_rede("Wie spät ist es?")
    assert dynamik.regie("Es ist kurz nach neun.", "freundlich") == ""


def test_ernstes_bleibt_ernst():
    dynamik = _dynamik()
    dynamik.neue_rede("Erzähl mir einen Witz")
    assert dynamik.regie("Leider ist das fehlgeschlagen, haha.", "bedauernd") == ""


def test_schmunzeln_nur_wenn_der_text_es_traegt_und_nicht_staendig():
    from backend.tts.sprechdynamik import SCHMUNZELN

    dynamik = _dynamik()
    dynamik.neue_rede("Was ist ein Quark?")
    assert dynamik.regie("Das war natürlich ein Scherz von mir.", "freundlich", jetzt=100.0) == SCHMUNZELN
    assert dynamik.regie("Und noch ein Scherz gleich hinterher.", "freundlich", jetzt=110.0) != SCHMUNZELN
    assert dynamik.regie("Ein dritter Scherz nach einer Weile.", "freundlich", jetzt=200.0) == SCHMUNZELN


def test_raeuspern_nur_am_anfang_und_selten():
    from backend.tts.sprechdynamik import RAEUSPERN

    dynamik = _dynamik()
    gezaehlt = 0
    for nummer in range(120):
        dynamik.neue_rede(f"Erklär mir bitte Thema {nummer}")
        for satz in range(4):
            zutat = dynamik.regie(
                f"Das ist Satz {satz} der Rede {nummer} mit einigen weiteren Wörtern.",
                "freundlich", jetzt=1000.0 + nummer * 30 + satz,
            )
            if zutat == RAEUSPERN:
                assert satz == 0
                gezaehlt += 1
    # 120 Erklaerungen in einer Stunde: hoechstens alle zehn Minuten eines.
    assert 1 <= gezaehlt <= 7


def test_nie_zwei_zutaten_in_folge_ausser_schmunzeln():
    dynamik = _dynamik()
    dynamik.neue_rede("Erzähl mir etwas über Rom")
    lang = "Rom wuchs über viele Jahrhunderte von einer kleinen Siedlung am Tiber zu einer Stadt, " \
           "die das ganze Mittelmeer beherrschte und deren Recht bis heute nachwirkt."
    folge = [bool(dynamik.regie(lang + f" Teil {i}.", "freundlich", jetzt=50.0 + i)) for i in range(8)]
    assert not any(a and b for a, b in zip(folge, folge[1:]))
    assert any(folge)


def test_ausgeschaltet_heisst_ausgeschaltet():
    dynamik = _dynamik()
    dynamik.eingeschaltet = False
    dynamik.neue_rede("Erzähl mir einen Witz")
    assert dynamik.regie("Haha, das war ein Scherz.", "freundlich") == ""


def test_die_stimme_entscheidet_je_satz_nur_einmal():
    """Dateiname und Anfrage muessen dieselbe Regie sehen."""

    from backend.tts import sprechdynamik
    from backend.tts.base_engine import SpeechRequest
    from backend.tts.openai_tts_engine import OpenAITtsEngine

    sprechdynamik.aktuelle().eingeschaltet = True
    sprechdynamik.neue_rede("Was ist ein Quark?")
    auftrag = SpeechRequest(text="Das war natürlich ein Scherz von mir.", emotion="freundlich")
    erste = OpenAITtsEngine._dynamik(auftrag)
    assert OpenAITtsEngine._dynamik(auftrag) == erste
