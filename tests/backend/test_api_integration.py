"""Integrationstests: Runtime und lokale HTTP-API.

Diese Tests starten die vollständige AI-Orb Runtime (Cognitive Core,
Agenten, Skills, Evolution Engine) samt HTTP-Server und sprechen sie über
die API an – so, wie es die Electron-Oberfläche tut.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Startet Runtime und API-Server für die Dauer des Testmoduls."""

    data_dir = tmp_path_factory.mktemp("ai-orb-data")

    import backend.utils.store as store_module

    original_get_data_dir = store_module.get_data_dir
    store_module.get_data_dir = lambda: data_dir  # type: ignore[assignment]

    from backend.api.server import create_server
    from backend.runtime import Runtime

    runtime = Runtime()
    runtime.start()

    api = create_server(runtime)
    # Port 0: Das Betriebssystem wählt einen freien Port, damit ein
    # laufendes AI-Orb den Test nicht stört.
    api._port = 0  # noqa: SLF001 - bewusst für den Test gesetzt
    api.start()

    yield f"http://127.0.0.1:{api.port}"

    api.stop()
    runtime.stop()
    store_module.get_data_dir = original_get_data_dir  # type: ignore[assignment]


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=20) as response:
        return json.loads(response.read())


def _post(base: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def test_health_endpoint(server):
    result = _get(server, "/health")

    assert result["status"] == "ok"
    assert result["version"]


def test_sse_kanal_bestaetigt_die_verbindung_sofort(server):
    request = urllib.request.Request(
        f"{server}/events",
        headers={"Accept": "text/event-stream"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        assert response.headers.get_content_type() == "text/event-stream"
        assert response.readline() == b"retry: 1000\n"
        assert response.readline() == b": connected\n"


def test_unknown_endpoint_returns_error(server):
    with pytest.raises(urllib.error.HTTPError) as error:
        _get(server, "/gibt-es-nicht")

    assert error.value.code == 404


def test_project_lifecycle(server):
    created = _post(server, "/projects/create", {"name": "Testprojekt", "kind": "schreibprojekt"})
    assert created["created"] is True

    project_id = created["project"]["id"]
    activated = _post(server, "/projects/activate", {"project_id": project_id})
    assert activated["activated"] is True

    summary = _get(server, "/projects/summary")
    assert "Testprojekt" in summary["summary"]


def test_task_creation_and_overview(server):
    result = _post(server, "/tasks/add", {"title": "Hausarbeit schreiben", "decompose": True})

    assert result["added"] is True
    assert len(result["tasks"]) > 1

    overview = _get(server, "/tasks")
    assert overview["overview"]["total"] >= len(result["tasks"])


def test_transparency_question_needs_no_language_model(server):
    """Transparenzfragen werden lokal beantwortet, auch ohne KI-Anbindung."""

    result = _post(server, "/ask", {"text": "Woran arbeite ich gerade?"})

    assert result["used_llm"] is False
    assert result["response"].strip() != ""
    assert result["intent"] == "transparenz"


def test_model_choice_is_explained(server):
    result = _post(server, "/ask", {"text": "Warum hast du dieses Modell gewählt?"})

    assert result["used_llm"] is False
    assert "Modell" in result["response"]


def test_empty_input_is_handled(server):
    result = _post(server, "/ask", {"text": "   "})

    assert "response" in result


def test_behavior_learning_records_position(server):
    recorded = _post(
        server,
        "/behavior/position",
        {
            "x": 1700,
            "y": 900,
            "screen_width": 1920,
            "screen_height": 1080,
            "monitor": 0,
            "manual": True,
        },
    )
    assert recorded["recorded"] is True

    score = _post(
        server,
        "/behavior/score",
        {"x": 1700, "y": 900, "screen_width": 1920, "screen_height": 1080, "monitor": 0},
    )
    assert score["score"] > 0


def test_agents_are_registered_and_tested(server):
    result = _get(server, "/agents")

    names = {agent["name"] for agent in result["agents"]}
    for expected in ("conversation", "reasoning", "research", "history", "coding", "desktop"):
        assert expected in names


def test_skill_catalog_is_available(server):
    result = _get(server, "/skills/catalog")

    assert result["entries"]
    assert "wissenschaftlich" in result["categories"]


def test_evolution_security_policy_forbids_automatic_changes(server):
    report = _get(server, "/evolution/report")
    policy = report["sicherheitsregeln"]

    assert policy["keine_automatische_änderung_produktiver_dateien"] is True
    assert policy["automatische_abhängigkeitsinstallation"] is False
    assert policy["quellcode_an_externe_dienste"] is False
    assert policy["benutzerbestätigung_erforderlich"] is True


def test_status_contains_all_layers(server):
    status = _get(server, "/status")

    for key in ("version", "cognitive", "agents", "skills", "behavior", "evolution"):
        assert key in status


def test_memory_can_be_searched_and_deleted(server):
    _post(server, "/ask", {"text": "Merke dir: Ich arbeite immer mit Kali Linux an meinem Projekt."})

    found = _post(server, "/memory/search", {"query": "Kali Linux"})
    assert "results" in found

    if found["results"]:
        entry_id = found["results"][0]["id"]
        deleted = _post(server, "/memory/delete", {"id": entry_id})
        assert deleted["deleted"] is True
