"""Project Engine – die zentrale Schnittstelle der Project Intelligence.

Alle anderen Module greifen ausschließlich über das Cognitive Core auf
Projektinformationen zu; das Cognitive Core wiederum nutzt genau diese
Klasse. Direkte Zugriffe zwischen Fachmodulen finden nicht statt.

Die Engine bündelt Projekterkennung, Projektgedächtnis, Dokumentverfolgung,
Kontextaufbau, Sitzungen, Meilensteine, Arbeitszustände, den Projektgraphen
und die Projektzusammenfassung.

Projektinformationen werden nur bei Bedarf geladen; große Projekte werden
inkrementell indexiert.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.cognitive.task_manager import TaskManager
from backend.memory.memory_engine import MemoryEngine
from backend.projects.dependency_graph import DependencyGraph
from backend.projects.document_tracker import DocumentTracker
from backend.projects.milestone_manager import MilestoneManager
from backend.projects.project_context import ProjectContext, ProjectContextData
from backend.projects.project_detector import ProjectDetector, DetectionResult
from backend.projects.project_memory import ProjectMemory
from backend.projects.project_summary import ProjectSummary
from backend.projects.session_manager import SessionManager
from backend.projects.workspace_manager import WorkspaceManager
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class ProjectEngine:
    """Zentrale Fassade der Project Intelligence Engine."""

    def __init__(self, memory: MemoryEngine, tasks: TaskManager) -> None:
        self._memory = memory
        self.storage = ProjectMemory()
        self.detector = ProjectDetector()
        self.documents = DocumentTracker(self.storage)
        self.milestones = MilestoneManager()
        self.workspaces = WorkspaceManager()
        self.graph = DependencyGraph(self.storage, memory)
        self.summaries = ProjectSummary(
            self.storage, memory, self.documents, self.milestones, tasks
        )
        self.context = ProjectContext(self.storage, memory, self.documents, self.milestones)
        self.sessions = SessionManager(self.storage, self.documents, self.summaries)

    # --- Projekte anlegen und erkennen ---------------------------------------

    def create(self, name: str, *, path: str | None = None, kind: str = "allgemein") -> dict[str, Any]:
        """Legt ein Projekt manuell an."""

        return self.storage.create(name, path=path, kind=kind)

    def detect_and_register(self, path: str | Path, *, auto_confirm: bool = False) -> dict[str, Any]:
        """Erkennt ein Projekt in einem Verzeichnis und registriert es.

        Ist die Erkennung unsicher, wird das Projekt **nicht** automatisch
        angelegt; stattdessen wird eine Rückfrage vorgeschlagen, damit der
        Benutzer die Zuordnung bestätigen oder manuell vornehmen kann.

        Args:
            path: Zu untersuchendes Verzeichnis.
            auto_confirm: Legt das Projekt auch bei unsicherer Erkennung an.

        Returns:
            Ein Bericht mit dem Erkennungsergebnis und – falls angelegt –
            dem Projekt.
        """

        detection: DetectionResult = self.detector.detect(path)

        existing = self.storage.find_by_path(detection.path)
        if existing is not None:
            return {
                "detection": detection.to_dict(),
                "project": existing,
                "created": False,
                "message": f"Das Verzeichnis gehört bereits zum Projekt „{existing.get('name')}“.",
            }

        if detection.needs_confirmation and not auto_confirm:
            return {
                "detection": detection.to_dict(),
                "project": None,
                "created": False,
                "requires_confirmation": True,
                "message": (
                    f"Ich vermute, dass es sich um ein {detection.kind}-Projekt handelt, "
                    "bin mir aber nicht sicher. Soll ich es als Projekt "
                    f"„{self.detector.suggest_name(detection.path)}“ anlegen?"
                ),
            }

        project = self.storage.create(
            self.detector.suggest_name(detection.path),
            path=detection.path,
            kind=detection.kind,
        )
        return {
            "detection": detection.to_dict(),
            "project": project,
            "created": True,
            "message": f"Projekt „{project['name']}“ wurde angelegt.",
        }

    # --- Aktives Projekt ------------------------------------------------------

    def activate(self, project_id: str) -> dict[str, Any]:
        """Aktiviert ein Projekt und startet eine Sitzung.

        Ein Projektwechsel vermischt niemals Wissen: Kontext, Aufgaben und
        Erinnerungen sind projektgebunden.
        """

        project = self.storage.get(project_id)
        if project is None:
            return {"activated": False, "message": "Unbekanntes Projekt."}

        self.storage.set_active(project_id)
        session = self.sessions.begin(project_id)
        logger.info("Projekt aktiviert: %s", project.get("name"))
        return {"activated": True, "project": project, "session": session}

    def active_project(self) -> dict[str, Any] | None:
        """Das aktuell aktive Projekt."""

        return self.storage.active()

    def active_project_id(self) -> str | None:
        """Die ID des aktiven Projekts."""

        project = self.storage.active()
        return str(project["id"]) if project else None

    def deactivate(self) -> None:
        """Hebt die Projektzuordnung auf."""

        self.storage.set_active(None)

    # --- Kontext und Zusammenfassung --------------------------------------------

    def context_for(self, project_id: str | None = None) -> ProjectContextData | None:
        """Baut den Projektkontext für Antworten auf."""

        target = project_id or self.active_project_id()
        if target is None:
            return None
        return self.context.build(target)

    def context_prompt(self, project_id: str | None = None) -> str:
        """Der Projektkontext als Text für Modellanfragen."""

        context = self.context_for(project_id)
        return context.to_prompt() if context else ""

    def summary_text(self, project_id: str | None = None) -> str:
        """Beantwortet "Woran arbeite ich gerade?"."""

        target = project_id or self.active_project_id()
        if target is None:
            return "Es ist derzeit kein Projekt aktiv."
        return self.summaries.as_text(target)

    # --- Projektinhalte ------------------------------------------------------------

    def add_note(self, text: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        """Fügt dem Projekt eine Notiz hinzu."""

        target = project_id or self.active_project_id()
        return self.storage.add_entry(target, "notes", text) if target else None

    def add_decision(self, text: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        """Hält eine getroffene Entscheidung fest."""

        target = project_id or self.active_project_id()
        return self.storage.add_entry(target, "decisions", text) if target else None

    def add_open_question(self, text: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        """Vermerkt eine offene Frage."""

        target = project_id or self.active_project_id()
        return self.storage.add_entry(target, "open_questions", text) if target else None

    def add_outline(self, text: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        """Hinterlegt eine Gliederung oder einen Kapitelstand."""

        target = project_id or self.active_project_id()
        return self.storage.add_entry(target, "outlines", text) if target else None

    def track_document(
        self, path: str | Path, *, role: str = "dokument", project_id: str | None = None
    ) -> dict[str, Any] | None:
        """Nimmt ein Dokument in die Projektverfolgung auf."""

        target = project_id or self.active_project_id()
        return self.documents.track(target, path, role=role) if target else None

    # --- Transparenz und Verwaltung -------------------------------------------------

    def list_projects(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        """Listet alle Projekte."""

        return self.storage.list(include_archived=include_archived)

    def export(self, project_id: str) -> dict[str, Any] | None:
        """Exportiert ein Projekt vollständig."""

        export = self.storage.export(project_id)
        if export is None:
            return None
        export["tasks"] = [
            task.to_dict() for task in self._memory.tasks.list(project_id=project_id)
        ]
        export["knowledge"] = [
            record.to_dict() for record in self._memory.knowledge.for_project(project_id)
        ]
        export["milestones"] = self.milestones.list(project_id)
        export["graph"] = self.graph.as_dict(project_id)
        return export

    def archive(self, project_id: str) -> bool:
        """Archiviert ein Projekt."""

        return self.storage.archive(project_id)

    def delete(self, project_id: str) -> dict[str, Any]:
        """Entfernt ein Projekt samt allem zugehörigen Wissen.

        Erfüllt die Transparenzanforderung "Projektwissen vollständig
        entfernen".
        """

        removed_memories = self._memory.forget_project(project_id)
        for milestone in self.milestones.list(project_id):
            self.milestones.delete(str(milestone["id"]))
        self.workspaces.forget(project_id)
        deleted = self.storage.delete(project_id)

        return {
            "deleted": deleted,
            "removed_memories": removed_memories,
            "message": (
                f"Projekt entfernt; {removed_memories} zugehörige Gedächtniseinträge gelöscht."
                if deleted
                else "Unbekanntes Projekt."
            ),
        }
