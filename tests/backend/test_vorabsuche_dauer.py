"""Sicherung gegen den Absturz der Vorabsuche.

Das Protokoll zeigte: 'ToolRun' object has no attribute 'duration_seconds'.
Die erzwungene Vorabsuche brach im ERFOLGSFALL ab - und zwar genau dann,
als die Suche wieder funktionierte (vorher scheiterte sie immer und kam nie
bis zu der kaputten Zeile). Ein ToolRun misst seine Dauer in 'seconds'.
"""

from __future__ import annotations

import inspect

from backend.tools.tool_engine import ToolRun


def test_toolrun_kennt_seconds_nicht_duration_seconds():
    felder = {f.name for f in ToolRun.__dataclass_fields__.values()}
    assert "seconds" in felder
    assert "duration_seconds" not in felder


def test_vorabsuche_greift_auf_das_richtige_feld_zu():
    from backend.orchestrator.orchestrator import Orchestrator

    quelle = inspect.getsource(Orchestrator._vorab_suchen)
    assert "lauf.duration_seconds" not in quelle, (
        "Die Vorabsuche greift wieder auf das nicht vorhandene "
        "'duration_seconds' zu - das stuerzt im Erfolgsfall ab."
    )
    assert "lauf.seconds" in quelle
