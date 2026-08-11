"""Tests für die Evolution Engine.

Der Schwerpunkt liegt auf den Sicherheitsregeln: Die produktive Codebasis
darf niemals automatisch verändert werden, und jede Änderung muss
rückgängig zu machen sein.
"""

from __future__ import annotations

import pytest

from backend.evolution.bug_detector import BugDetector
from backend.evolution.code_analyzer import CodeAnalyzer
from backend.evolution.idea_generator import IdeaGenerator
from backend.evolution.rollback_manager import RollbackManager
from backend.evolution.skill_trainer import SkillTrainer


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.utils.store.get_data_dir", lambda: tmp_path)
    yield tmp_path


@pytest.fixture()
def sample_project(tmp_path):
    """Ein kleines Projekt mit bewusst mangelhaftem Code."""

    backend_dir = tmp_path / "backend" / "beispiel"
    backend_dir.mkdir(parents=True)
    (tmp_path / "backend" / "__init__.py").write_text('"""Paket."""\n', encoding="utf-8")
    (backend_dir / "__init__.py").write_text('"""Paket."""\n', encoding="utf-8")

    body = "\n".join(f"    wert_{index} = {index}" for index in range(80))
    (backend_dir / "schlecht.py").write_text(
        "def sehr_lange_funktion():\n" + body + "\n    return wert_0\n",
        encoding="utf-8",
    )
    return tmp_path


def test_code_analyzer_finds_long_function(sample_project):
    report = CodeAnalyzer(root=sample_project).analyze()

    categories = {finding["category"] for finding in report["findings"]}
    assert "funktionslänge" in categories
    assert "dokumentation" in categories


def test_code_analyzer_reports_metrics(sample_project):
    report = CodeAnalyzer(root=sample_project).analyze()

    assert report["total_lines"] > 0
    assert report["total_functions"] >= 1


def test_ideas_are_always_justified():
    """Jede Idee muss eine Begründung besitzen."""

    ideas = IdeaGenerator().generate(
        code_report={
            "findings": [
                {"category": "funktionslänge", "location": "a.py:1", "message": "zu lang"},
                {"category": "funktionslänge", "location": "b.py:1", "message": "zu lang"},
                {"category": "funktionslänge", "location": "c.py:1", "message": "zu lang"},
            ],
            "average_documentation": 0.5,
        },
        architecture_report={"cycles": [["a", "b", "a"]], "maintainability": 0.5},
    )

    assert ideas
    for idea in ideas:
        assert idea.rationale.strip() != ""
        assert idea.type


def test_skill_suggestions_come_from_observed_usage():
    ideas = IdeaGenerator().generate(
        usage={"file_types": {"pdf": 12}, "missing_capabilities": ["pdf_lesen"]}
    )

    skill_ideas = [idea for idea in ideas if idea.type == "neuer_skill"]
    assert skill_ideas
    assert "pdf" in skill_ideas[0].rationale.lower()


def test_bug_detector_groups_similar_errors():
    detector = BugDetector()
    detector.report(message="Verbindung zu 192.168.0.1 fehlgeschlagen", module="net")
    detector.report(message="Verbindung zu 10.0.0.5 fehlgeschlagen", module="net")

    groups = detector.groups()

    assert len(groups) == 1
    assert groups[0].count == 2


def test_bug_detector_prioritises_user_feedback():
    detector = BugDetector()
    for _ in range(3):
        detector.report_user_feedback("Der Orb reagiert nicht auf Klicks")

    assert detector.groups()[0].priority in ("hoch", "mittel")


def test_rollback_restores_previous_content(tmp_path):
    project = tmp_path / "projekt"
    (project / "backend").mkdir(parents=True)
    target = project / "backend" / "modul.py"
    target.write_text("original\n", encoding="utf-8")

    manager = RollbackManager(root=project)
    point = manager.create_point(
        patch_id="p1",
        title="Teständerung",
        description="Beschreibung",
        branch="evolution/p1",
        commit="abc",
        version="0.1.0",
        files=["backend/modul.py"],
    )

    target.write_text("verändert\n", encoding="utf-8")
    result = manager.rollback(point.id)

    assert result["restored"] is True
    assert target.read_text(encoding="utf-8") == "original\n"


def test_rollback_records_are_listed(tmp_path):
    project = tmp_path / "projekt"
    (project / "backend").mkdir(parents=True)
    (project / "backend" / "modul.py").write_text("inhalt\n", encoding="utf-8")

    manager = RollbackManager(root=project)
    manager.create_point(
        patch_id="p1",
        title="Erste Änderung",
        description="",
        branch="b",
        commit="c",
        version="0.1.0",
        files=["backend/modul.py"],
    )

    assert len(manager.list()) == 1
    assert manager.latest()["title"] == "Erste Änderung"


def test_skill_trainer_creates_complete_draft(tmp_path):
    trainer = SkillTrainer(root=tmp_path)

    draft = trainer.create_draft("zotero")

    from pathlib import Path

    directory = Path(draft.path)
    assert (directory / "skill.json").exists()
    assert (directory / "skill.py").exists()
    assert (directory / "test_skill.py").exists()
    assert (directory / "README.md").exists()
    assert draft.capabilities


def test_skill_draft_is_not_installed(tmp_path):
    """Entwürfe landen im Entwurfsverzeichnis, nicht im Skill-Verzeichnis."""

    trainer = SkillTrainer(root=tmp_path)
    draft = trainer.create_draft("pdf-analyse")

    assert "skill_drafts" in draft.path
