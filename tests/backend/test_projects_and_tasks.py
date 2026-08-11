"""Tests für Projekte, Aufgaben und Ziele."""

from __future__ import annotations

import pytest

from backend.cognitive.goal_manager import GoalManager
from backend.cognitive.task_manager import TaskManager
from backend.memory.memory_engine import MemoryEngine
from backend.projects.project_memory import ProjectMemory


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Leitet sämtliche Persistenz in ein temporäres Verzeichnis um."""

    monkeypatch.setattr("backend.utils.store.get_data_dir", lambda: tmp_path)
    yield tmp_path


@pytest.fixture()
def memory() -> MemoryEngine:
    return MemoryEngine()


def test_task_decomposition_uses_known_pattern(memory):
    manager = TaskManager(memory)

    created = manager.decompose("Hausarbeit über den Investiturstreit")

    assert len(created) > 1
    titles = [task.content for task in created[1:]]
    assert "Literatur sammeln" in titles
    assert "Zitation prüfen" in titles


def test_task_without_pattern_is_not_invented(memory):
    """Ohne passendes Muster wird keine künstliche Struktur erfunden."""

    manager = TaskManager(memory)

    created = manager.decompose("Blumen gießen")

    assert len(created) == 1


def test_next_step_prefers_started_tasks(memory):
    manager = TaskManager(memory)
    first = manager.add("Erste Aufgabe")
    second = manager.add("Zweite Aufgabe")
    manager.set_status(second.id, "in_bearbeitung")

    assert manager.next_step().id == second.id


def test_blocked_tasks_are_skipped(memory):
    manager = TaskManager(memory)
    blocked = manager.add("Blockierte Aufgabe")
    open_task = manager.add("Offene Aufgabe")
    manager.set_status(blocked.id, "blockiert", reason="Wartet auf Literatur")

    assert manager.next_step().id == open_task.id
    assert manager.blocked()[0].metadata["blocked_reason"] == "Wartet auf Literatur"


def test_task_overview_counts_states(memory):
    manager = TaskManager(memory)
    done = manager.add("Erledigt")
    manager.add("Offen")
    manager.set_status(done.id, "erledigt")

    overview = manager.overview()

    assert overview["total"] == 2
    assert overview["by_status"]["erledigt"] == 1
    assert overview["by_status"]["offen"] == 1


def test_project_knowledge_stays_separated(memory):
    projects = ProjectMemory()
    first = projects.create("Projekt Eins")
    second = projects.create("Projekt Zwei")

    memory.remember("Wichtige Notiz zum ersten Projekt", project_id=first["id"], force=True)
    memory.remember("Wichtige Notiz zum zweiten Projekt", project_id=second["id"], force=True)

    assert len(memory.all(project_id=first["id"])) == 1
    assert len(memory.all(project_id=second["id"])) == 1


def test_deleting_project_removes_its_knowledge(memory):
    projects = ProjectMemory()
    project = projects.create("Zu löschendes Projekt")
    memory.remember("Eine Projektnotiz", project_id=project["id"], force=True)

    removed = memory.forget_project(project["id"])

    assert removed == 1
    assert memory.all(project_id=project["id"]) == []


def test_project_sections_store_entries():
    projects = ProjectMemory()
    project = projects.create("Hausarbeit")

    projects.add_entry(project["id"], "decisions", "Fragestellung auf 1075–1122 eingegrenzt")
    projects.add_entry(project["id"], "open_questions", "Welche Quellenedition nutzen?")

    assert len(projects.entries(project["id"], "decisions")) == 1
    assert len(projects.entries(project["id"], "open_questions")) == 1


def test_goals_are_sorted_by_priority():
    goals = GoalManager()
    goals.add("Niedrige Priorität", priority="niedrig")
    goals.add("Hohe Priorität", priority="hoch")

    active = goals.list()

    assert active[0]["title"] == "Hohe Priorität"


def test_goal_progress_completes_goal():
    goals = GoalManager()
    goal = goals.add("Hausarbeit abschließen")

    goals.set_progress(goal["id"], 1.0)

    assert goals.get(goal["id"])["status"] == "erreicht"


def test_goal_overview_reports_horizons():
    goals = GoalManager()
    goals.add("Heute erledigen", horizon="heute")
    goals.add("Rust lernen", horizon="langfristig")

    overview = goals.overview()

    assert overview["total"] == 2
    assert overview["by_horizon"]["heute"] == 1
    assert overview["by_horizon"]["langfristig"] == 1
