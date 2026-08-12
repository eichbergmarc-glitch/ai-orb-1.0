"""Bei einer klaren Ansage sieht der Orb GARANTIERT auf den Bildschirm.

Der Benutzer sagte "mach einen Printscreen und nutze das Werkzeug", und das
Modell nannte das Werkzeug, ohne es zu rufen. Ein Schubser hilft oft, aber
bei einer ausdruecklichen Bitte ist "oft" zu wenig. Darum wird hier - wie
schon bei der erzwungenen Vorabsuche - deterministisch gehandelt: Der Orb
macht das Bild selbst. Diese Tests sichern den Ausloeser und den erzwungenen
Aufruf.
"""

from __future__ import annotations

import asyncio

from backend.orchestrator.orchestrator import will_bildschirm


def test_klare_bildschirm_bitten_loesen_aus():
    ja = [
        "mach einen Printscreen und sag mir welches Dokument offen ist",
        "Hallo Orb, schau auf den Bildschirm",
        "was ist gerade auf dem Bildschirm",
        "mach ein Bildschirmfoto",
        "beschreib mir was auf dem Monitor zu sehen ist",
        "lies den Bildschirm vor",
    ]
    for satz in ja:
        assert will_bildschirm(satz), f"sollte ausloesen: {satz!r}"


def test_kein_fehlalarm():
    nein = [
        "mach den Bildschirm heller",          # Einstellung, kein Ansehen
        "wie spaet ist es",
        "such nach aktuellen Nachrichten",
        "erzaehl mir einen Witz",
        "dreh die Lautstaerke runter",
    ]
    for satz in nein:
        assert not will_bildschirm(satz), f"sollte NICHT ausloesen: {satz!r}"


# --- Der erzwungene Aufruf ------------------------------------------------------


class _FakeResult:
    def __init__(self, ok, output="", error=""):
        self.ok = ok
        self.output = output
        self.error = error


class _FakeRun:
    def __init__(self, result):
        self.result = result
        self.seconds = 0.1


class _FakeToolEngine:
    enabled = True

    def __init__(self, result):
        self._result = result
        self.aufrufe = []

    async def direkt_ausfuehren(self, name, arguments, *, actor="vorab"):
        self.aufrufe.append((name, arguments))
        return _FakeRun(self._result)


def _orchestrator_mit(tool_engine):
    from backend.orchestrator.orchestrator import Orchestrator
    orch = Orchestrator.__new__(Orchestrator)   # ohne vollen Aufbau
    orch._tool_engine = tool_engine
    return orch


def test_vorab_bildschirm_ruft_das_werkzeug_und_reicht_das_bild_durch():
    te = _FakeToolEngine(_FakeResult(True, output="Auf dem Bildschirm ist ein Word-Dokument 'Antike.docx'."))
    orch = _orchestrator_mit(te)

    block = asyncio.run(orch._vorab_bildschirm("welches Dokument ist offen?"))

    assert te.aufrufe and te.aufrufe[0][0] == "bildschirm_ansehen"
    assert "Antike.docx" in block
    assert "nicht sehen" in block.lower()  # weist die Ausrede des Modells ab


def test_vorab_bildschirm_meldet_fehler_ehrlich():
    te = _FakeToolEngine(_FakeResult(False, error="Bildschirmauswertung nicht verfuegbar."))
    orch = _orchestrator_mit(te)
    block = asyncio.run(orch._vorab_bildschirm("schau auf den Bildschirm"))
    assert "nicht" in block.lower()
    assert "verfuegbar" in block.lower() or "ging nicht" in block.lower()
