"""Tempo-Massnahmen vom 15.11.2026.

Drei Punkte aus der Antwortzeit-Analyse:

1. Ein deutlicher Auftrag bekommt am Schluss die Regel "handeln, nicht
   ankuendigen" - das Nachhaken kostete eine volle Modellrunde.
2. Bei einer Bitte ohne erkanntes Stichwort wird nicht mehr das ganze
   Werkzeugverzeichnis beschrieben (gemessen: 21 700 Zeichen), sondern ein
   Kernset; alle uebrigen Werkzeuge stehen mit Namen da.
3. Auch eine Frage vom Handy/iPad schreibt eine TURN_LATENCY-Zeile, mit
   dem Moment, in dem am PC das erste Wort zu hoeren ist.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.system.performance_trace import TurnTrace, mark_stage
from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.tools.registry import ToolRegistry
from backend.tools.tool_engine import ToolCall, ToolEngine, ToolRun


class _Werkzeug(Tool):
    description = "Ein Testwerkzeug, das etwas Bestimmtes tut. Weitere Erklaerung."

    def __init__(self, name: str) -> None:
        self.name = name
        self.parameters = [ToolParameter("ort", "string", "Wo", required=True)]

    async def execute(self, arguments: dict[str, object]) -> ToolResult:
        return ToolResult.success("ok")


NAMEN = (
    "internet_suchen", "webseite_lesen", "aktuelle_zeit", "rechnen", "wetter",
    "gedaechtnis_durchsuchen", "wissen_nachsehen", "animation_wechseln",
    "animation_anpassen", "mails_lesen", "mails_suchen", "pdf_erstellen",
    "musik_abspielen", "termine_ansehen", "tagebuch_schreiben", "tagebuch_zeigen",
)


def _engine() -> ToolEngine:
    registry = ToolRegistry()
    registry.register_many([_Werkzeug(name) for name in NAMEN])
    return ToolEngine(
        registry=registry,
        security=object(),  # type: ignore[arg-type]
        provider_manager=object(),
    )


def _beschrieben(anweisung: str) -> set[str]:
    return {
        zeile[2:].split(":", 1)[0]
        for zeile in anweisung.splitlines()
        if zeile.startswith("- ")
    }


# --- Punkt 2: Kernset statt Vollverzeichnis -------------------------------


def test_bitte_ohne_stichwort_beschreibt_nur_das_kernset():
    engine = _engine()
    anweisung = engine.system_instructions(text="Erzaehl mir etwas ueber Kant.")

    beschrieben = _beschrieben(anweisung)
    assert beschrieben == {n for n in ToolEngine.KERNWERKZEUGE if n in NAMEN}
    # Nichts geht verloren: Die uebrigen stehen mit Namen da ...
    assert "Weitere Werkzeuge" in anweisung
    assert "mails_lesen" in anweisung and "pdf_erstellen" in anweisung
    # ... bis auf die, die das Modell nie sehen soll.
    assert "tagebuch_schreiben" not in anweisung


def test_kernset_ist_deutlich_kuerzer_als_das_vollverzeichnis():
    engine = _engine()
    voll = engine.system_instructions()
    kurz = engine.system_instructions(text="Erzaehl mir etwas ueber Kant.")
    assert len(kurz) < len(voll)


def test_die_verbindliche_regel_steht_weiter_am_schluss():
    anweisung = _engine().system_instructions(text="Erzaehl mir etwas ueber Kant.")
    assert anweisung.rstrip().endswith(ToolEngine.VERBINDLICHE_REGEL.rstrip()[-60:])
    assert anweisung.index("Weitere Werkzeuge") < anweisung.index("SO ENTSCHEIDEST DU")


def test_ohne_text_bleibt_das_vollstaendige_verzeichnis():
    anweisung = _engine().system_instructions()
    assert "Weitere Werkzeuge" not in anweisung
    assert "mails_lesen:" in anweisung


def test_animation_wird_erkannt():
    namen = set(_engine()._relevante_werkzeuge("Wechsle die Animation auf die drei Baelle") or [])
    assert "animation_wechseln" in namen


def test_zeig_mir_das_wetter_waehlt_das_wetterwerkzeug():
    """Vorher traf 'zeig' nur die Grafikwerkzeuge - 'wetter' fehlte."""

    namen = set(_engine()._relevante_werkzeuge("Zeig mir das Wetter fuer morgen") or [])
    assert "wetter" in namen


def test_zugriff_ist_kein_zug():
    namen = _engine()._relevante_werkzeuge("Hast du Zugriff auf meine Dateien?") or []
    assert "verbindung_suchen" not in namen


def test_fehlgeschlagener_aufruf_bekommt_die_genaue_beschreibung():
    engine = _engine()
    gesehen: list[str] = []

    async def ausfuehren(call: ToolCall, actor: str) -> ToolRun:  # noqa: ARG001
        return ToolRun(call.tool, call.arguments, ToolResult.failure("Pflichtfeld 'ort' fehlt"))

    class _Modell:
        async def chat(self, nachrichten):  # noqa: ANN001
            gesehen.append(nachrichten[-1].content)
            return SimpleNamespace(text="Fertig.")

    engine._execute = ausfuehren  # type: ignore[method-assign]
    engine._providers = _Modell()
    text, _ = asyncio.run(engine.continue_with_tools(
        [], '```werkzeug\n{"werkzeug": "mails_lesen", "argumente": {}}\n```'
    ))

    assert text == "Fertig."
    assert "So wird es aufgerufen" in gesehen[0]
    assert "ort (string, Pflicht)" in gesehen[0]


# --- Punkt 1: handeln statt ankuendigen -----------------------------------


def test_auftragsregel_verbietet_die_ankuendigung():
    regel = ToolEngine.AUFTRAGS_REGEL
    assert "NUR aus dem Werkzeugaufruf" in regel
    assert "Einen Moment" in regel


def test_orchestrator_haengt_die_auftragsregel_an():
    from pathlib import Path

    import backend.orchestrator.orchestrator as modul

    quelle = Path(modul.__file__).read_text(encoding="utf-8")
    assert "AUFTRAGS_REGEL" in quelle
    assert "faehigkeit.handlungsauftrag" in quelle


# --- Punkt 3: Zeitmessung fuer den Geraeteweg -----------------------------


def _runtime_mit_stimme(monkeypatch):
    import backend.runtime as rt
    from backend.runtime import Runtime

    zuege: list[TurnTrace] = []
    original = rt.start_turn_trace

    def merken():
        zug, marke = original()
        zuege.append(zug)
        return zug, marke

    monkeypatch.setattr(rt, "start_turn_trace", merken)

    class _Stimme:
        _active_turn_trace = None

        async def say(self, text, *, emotion=""):  # noqa: ANN001, ARG002
            # So wie _on_playback_started in der Sprachschicht.
            zug = self._active_turn_trace
            if zug is not None and "answer_tts_requested" in zug.stages:
                zug.mark("answer_audible")
            return True

    leer = Runtime.__new__(Runtime)
    leer.voice = _Stimme()
    leer._eigene_rede_merken = lambda text: None
    return leer, zuege


def test_frage_vom_geraet_mit_ausgabe_am_pc_wird_vermessen(monkeypatch):
    leer, zuege = _runtime_mit_stimme(monkeypatch)

    async def ablauf(aufnahme, **_):  # noqa: ANN001, ARG001
        mark_stage("transcript_ready")
        leer._am_pc_sagen("Hallo Marc.")
        return {"frage": "Hallo?", "antwort": "Hallo Marc.", "am_pc": True}

    leer._stimme_vom_geraet_ablauf = ablauf

    async def lauf():
        ergebnis = await leer.stimme_vom_geraet("x.wav", ausgabe_pc=True)
        for _ in range(20):
            await asyncio.sleep(0)
        return ergebnis

    ergebnis = asyncio.run(lauf())
    assert ergebnis["am_pc"]
    zug = zuege[0]
    for stufe in ("transcript_ready", "answer_tts_requested", "answer_audible", "completed"):
        assert stufe in zug.stages, stufe
    # Die Sprachschicht bleibt danach frei fuer ihre eigenen Zuege.
    assert leer.voice._active_turn_trace is None


def test_nicht_erkannte_aufnahme_wird_als_ignoriert_vermessen(monkeypatch, caplog):
    leer, zuege = _runtime_mit_stimme(monkeypatch)

    async def ablauf(aufnahme, **_):  # noqa: ANN001, ARG001
        return {"frage": "", "antwort": "", "auftrag": "", "teile": 0}

    leer._stimme_vom_geraet_ablauf = ablauf
    asyncio.run(leer.stimme_vom_geraet("x.wav"))
    assert "completed" in zuege[0].stages


def test_fehler_im_ablauf_bleibt_ein_fehler(monkeypatch):
    leer, zuege = _runtime_mit_stimme(monkeypatch)

    async def ablauf(aufnahme, **_):  # noqa: ANN001, ARG001
        raise RuntimeError("kaputt")

    leer._stimme_vom_geraet_ablauf = ablauf
    try:
        asyncio.run(leer.stimme_vom_geraet("x.wav"))
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Der Fehler darf nicht verschluckt werden.")
    assert "completed" in zuege[0].stages
