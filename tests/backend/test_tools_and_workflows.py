"""Tests der Werkzeuge und Arbeitsabläufe (Phasen 9 und 19).

Der Schwerpunkt liegt auf dem sicheren Auswerten von Rechenausdrücken und
darauf, dass die Werkzeugschleife nicht in eine Endlosschleife gerät. Beides
sind Stellen, an denen eine Modellantwort Schaden anrichten könnte.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.events.event_bus import EventBus
from backend.security.security_engine import SecurityEngine
from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.tools.registry import ToolRegistry
from backend.tools.standard_tools import (
    CalculateTool,
    CurrentTimeTool,
    build_standard_tools,
    evaluate_expression,
)
from backend.tools.tool_engine import parse_tool_calls, strip_tool_calls
from backend.workflows.workflow import (
    OnError,
    Workflow,
    WorkflowStep,
    evaluate_condition,
    resolve_placeholders,
)
from backend.workflows.workflow_engine import WorkflowEngine


# --- Rechenausdrücke ---------------------------------------------------------


def test_evaluate_basic_arithmetic() -> None:
    assert evaluate_expression("2 + 3") == 5.0
    assert evaluate_expression("17 * 23") == 391.0
    assert evaluate_expression("(1250 / 8) ** 2") == pytest.approx(24414.0625)
    assert evaluate_expression("2^10") == 1024.0
    assert evaluate_expression("3,5 + 1,5") == 5.0


def test_evaluate_rejects_code() -> None:
    """Ein Ausdruck aus einer Modellantwort darf nichts ausführen."""

    for dangerous in [
        "__import__('os').system('dir')",
        "open('/etc/passwd').read()",
        "eval('1+1')",
        "[].__class__",
        "lambda: 1",
        "print(1)",
    ]:
        with pytest.raises(ValueError):
            evaluate_expression(dangerous)


def test_evaluate_rejects_division_by_zero() -> None:
    with pytest.raises(ValueError, match="null"):
        evaluate_expression("5 / 0")


def test_evaluate_rejects_huge_exponent() -> None:
    """Sonst blockiert eine einzige Zeile den Rechner für Minuten."""

    with pytest.raises(ValueError, match="Exponent"):
        evaluate_expression("9 ** 99999")


def test_evaluate_rejects_overlong_input() -> None:
    with pytest.raises(ValueError, match="zu lang"):
        evaluate_expression("1+" * 200 + "1")


# --- Werkzeuge ------------------------------------------------------------------


def test_calculate_tool_returns_result() -> None:
    result = asyncio.run(CalculateTool().execute({"ausdruck": "6 * 7"}))
    assert result.ok
    assert "42" in result.output


def test_calculate_tool_reports_bad_input() -> None:
    result = asyncio.run(CalculateTool().execute({"ausdruck": "import os"}))
    assert not result.ok
    assert result.error


def test_current_time_tool_names_weekday() -> None:
    result = asyncio.run(CurrentTimeTool().execute({}))
    assert result.ok
    assert any(
        day in result.output
        for day in ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
    )


def test_tool_validation_rejects_unknown_fields() -> None:
    tool = CalculateTool()
    valid, problem, _ = tool.validate({"ausdruck": "1+1", "erfunden": "x"})
    assert not valid
    assert "erfunden" in problem


def test_tool_validation_requires_mandatory_fields() -> None:
    valid, problem, _ = CalculateTool().validate({})
    assert not valid
    assert "ausdruck" in problem


def test_tool_validation_converts_types() -> None:
    """Sprachmodelle liefern Zahlen häufig als Text."""

    class Sample(Tool):
        name = "probe"
        description = "Eine Probe zum Prüfen der Umwandlung."
        permission = "compute"
        parameters = (
            ToolParameter("zahl", "integer", "Eine Zahl."),
            ToolParameter("ja", "boolean", "Ein Schalter.", required=False),
        )

        async def execute(self, arguments):  # type: ignore[no-untyped-def]
            return ToolResult.success("ok")

    valid, _, cleaned = Sample().validate({"zahl": "42", "ja": "ja"})
    assert valid
    assert cleaned["zahl"] == 42
    assert cleaned["ja"] is True


# --- Verzeichnis -------------------------------------------------------------------


def test_registry_rejects_duplicate_names() -> None:
    registry = ToolRegistry()
    assert registry.register(CalculateTool())
    assert not registry.register(CalculateTool())
    assert len(registry) == 1


def test_registry_rejects_unknown_permission() -> None:
    """Ein Werkzeug mit erfundener Berechtigung kommt gar nicht ins Angebot."""

    class Rogue(Tool):
        name = "boese"
        description = "Verlangt eine Berechtigung, die es nicht gibt."
        permission = "alles_duerfen"
        parameters = ()

        async def execute(self, arguments):  # type: ignore[no-untyped-def]
            return ToolResult.success("")

    registry = ToolRegistry()
    assert not registry.register(Rogue())


def test_registry_unregisters_by_source() -> None:
    """Beim Entladen eines Plugins verschwinden genau dessen Werkzeuge."""

    registry = ToolRegistry()
    registry.register(CalculateTool(), source="plugin:test")
    registry.register(CurrentTimeTool(), source="eingebaut")

    assert registry.unregister_source("plugin:test") == 1
    assert registry.names() == ["aktuelle_zeit"]


def test_standard_tools_are_registered() -> None:
    security = SecurityEngine(EventBus())
    registry = ToolRegistry()
    count = registry.register_many(build_standard_tools(security=security))

    assert count >= 6
    assert "rechnen" in registry
    assert "aktuelle_zeit" in registry


# --- Werkzeugaufrufe im Text ----------------------------------------------------------


def test_parse_tool_call_from_code_block() -> None:
    text = """Ich schaue nach.

```werkzeug
{"werkzeug": "rechnen", "argumente": {"ausdruck": "2+2"}}
```
"""
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].tool == "rechnen"
    assert calls[0].arguments["ausdruck"] == "2+2"


def test_parse_tool_call_accepts_english_keys() -> None:
    text = '```tool\n{"tool": "rechnen", "arguments": {"ausdruck": "1+1"}}\n```'
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].tool == "rechnen"


def test_parse_ignores_broken_json() -> None:
    """Ein vergessenes Komma zerstört nicht die ganze Antwort."""

    text = '```werkzeug\n{"werkzeug": "rechnen" "argumente": {}}\n```'
    assert parse_tool_calls(text) == []


def test_strip_tool_calls_leaves_prose() -> None:
    text = 'Einen Moment.\n\n```werkzeug\n{"werkzeug": "rechnen"}\n```\n\nSo, fertig.'
    cleaned = strip_tool_calls(text)
    assert "werkzeug" not in cleaned
    assert "Einen Moment." in cleaned
    assert "So, fertig." in cleaned


# --- Arbeitsabläufe --------------------------------------------------------------------


def test_placeholders_are_resolved() -> None:
    context = {"eingabe": "Bismarck", "suche": "Treffer gefunden"}
    assert resolve_placeholders("Suche nach {{eingabe}}", context) == "Suche nach Bismarck"
    assert resolve_placeholders("{{suche}}", context) == "Treffer gefunden"


def test_unknown_placeholder_stays_visible() -> None:
    """Ein stehen gebliebener Platzhalter fällt auf – ein leerer Wert nicht."""

    assert resolve_placeholders("{{gibtesnicht}}", {}) == "{{gibtesnicht}}"


def test_conditions_are_evaluated() -> None:
    context = {"treffer": "etwas", "leer": ""}
    assert evaluate_condition("", context)
    assert evaluate_condition("{{treffer}} vorhanden", context)
    assert not evaluate_condition("{{leer}} vorhanden", context)
    assert evaluate_condition("{{leer}} leer", context)
    assert evaluate_condition("{{treffer}} enthaelt etwas", context)
    assert evaluate_condition("{{treffer}} == etwas", context)
    assert not evaluate_condition("{{treffer}} == anderes", context)


def test_workflow_validation_catches_unknown_tool() -> None:
    workflow = Workflow(
        workflow_id="x",
        name="Test",
        steps=[WorkflowStep(name="a", tool="gibtesnicht")],
    )
    problems = workflow.validate(["rechnen"])
    assert any("gibtesnicht" in problem for problem in problems)


def test_workflow_validation_catches_forward_reference() -> None:
    """Ein Verweis auf einen späteren Schritt ist ein Fehler."""

    workflow = Workflow(
        workflow_id="x",
        name="Test",
        steps=[
            WorkflowStep(name="erst", tool="rechnen", arguments={"ausdruck": "{{spaeter}}"}),
            WorkflowStep(name="spaeter", tool="rechnen", arguments={"ausdruck": "1+1"}),
        ],
    )
    problems = workflow.validate(["rechnen"])
    assert any("spaeter" in problem for problem in problems)


def test_workflow_matches_trigger() -> None:
    workflow = Workflow(
        workflow_id="x", name="Recherche", triggers=["starte meine recherche"]
    )
    assert workflow.matches("Starte meine Recherche")
    assert workflow.matches("Bitte starte meine Recherche jetzt")
    assert not workflow.matches("Wie spät ist es?")


def test_workflow_runs_end_to_end() -> None:
    """Ein Ablauf mit zwei Schritten läuft durch und reicht Werte weiter."""

    async def scenario() -> None:
        security = SecurityEngine(EventBus())
        registry = ToolRegistry()
        registry.register_many(build_standard_tools(security=security))
        engine = WorkflowEngine(
            registry=registry,
            security=security,
            store_filename="workflows/test-workflows.json",
        )

        for existing in engine.workflows():
            engine.remove(existing["workflow_id"])

        workflow, message = engine.create(
            "Probe",
            [
                {"name": "zeit", "tool": "aktuelle_zeit"},
                {"name": "summe", "tool": "rechnen", "arguments": {"ausdruck": "40+2"}},
            ],
        )
        assert workflow is not None, message

        run = await engine.run(workflow.workflow_id)
        assert run.state.value == "fertig"
        assert len(run.results) == 2
        assert all(result.ok for result in run.results)
        assert "42" in run.results[1].output

        engine.remove(workflow.workflow_id)

    asyncio.run(scenario())


def test_workflow_skips_step_on_error_when_configured() -> None:
    """Bei ``ueberspringen`` läuft der Ablauf weiter."""

    async def scenario() -> None:
        security = SecurityEngine(EventBus())
        registry = ToolRegistry()
        registry.register_many(build_standard_tools(security=security))
        engine = WorkflowEngine(
            registry=registry,
            security=security,
            store_filename="workflows/test-skip.json",
        )

        for existing in engine.workflows():
            engine.remove(existing["workflow_id"])

        workflow, _ = engine.create(
            "MitFehler",
            [
                {
                    "name": "kaputt",
                    "tool": "rechnen",
                    "arguments": {"ausdruck": "import os"},
                    "on_error": "ueberspringen",
                },
                {"name": "danach", "tool": "rechnen", "arguments": {"ausdruck": "1+1"}},
            ],
        )
        assert workflow is not None

        run = await engine.run(workflow.workflow_id)
        assert run.state.value == "fertig"
        assert run.results[0].skipped
        assert run.results[1].ok

        engine.remove(workflow.workflow_id)

    asyncio.run(scenario())


def test_workflow_aborts_on_error_by_default() -> None:
    async def scenario() -> None:
        security = SecurityEngine(EventBus())
        registry = ToolRegistry()
        registry.register_many(build_standard_tools(security=security))
        engine = WorkflowEngine(
            registry=registry,
            security=security,
            store_filename="workflows/test-abort.json",
        )

        for existing in engine.workflows():
            engine.remove(existing["workflow_id"])

        workflow, _ = engine.create(
            "Abbruch",
            [
                {"name": "kaputt", "tool": "rechnen", "arguments": {"ausdruck": "eval('1')"}},
                {"name": "danach", "tool": "rechnen", "arguments": {"ausdruck": "1+1"}},
            ],
        )
        assert workflow is not None

        run = await engine.run(workflow.workflow_id)
        assert run.state.value == "fehlgeschlagen"
        # Der zweite Schritt wurde gar nicht mehr versucht.
        assert len(run.results) == 1

        engine.remove(workflow.workflow_id)

    asyncio.run(scenario())


def test_on_error_parsing() -> None:
    assert OnError.parse("ueberspringen") is OnError.SKIP
    assert OnError.parse("wiederholen") is OnError.RETRY
    assert OnError.parse("unsinn") is OnError.ABORT
