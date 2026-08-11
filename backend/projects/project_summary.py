"""Project Summary – die Antwort auf "Woran arbeite ich gerade?".

Liefert aktives Projekt, aktuellen Arbeitsstand, offene Aufgaben, letzte
Änderungen und den empfohlenen nächsten Schritt in einer für den Benutzer
direkt lesbaren Form.
"""

from __future__ import annotations

import time
from typing import Any

from backend.cognitive.task_manager import TaskManager
from backend.memory.memory_engine import MemoryEngine
from backend.projects.document_tracker import DocumentTracker
from backend.projects.milestone_manager import MilestoneManager
from backend.projects.project_memory import ProjectMemory


class ProjectSummary:
    """Erzeugt Projektzusammenfassungen."""

    def __init__(
        self,
        project_memory: ProjectMemory,
        memory: MemoryEngine,
        documents: DocumentTracker,
        milestones: MilestoneManager,
        tasks: TaskManager,
    ) -> None:
        self._projects = project_memory
        self._memory = memory
        self._documents = documents
        self._milestones = milestones
        self._tasks = tasks

    def summarize(self, project_id: str) -> dict[str, Any] | None:
        """Erstellt die strukturierte Zusammenfassung eines Projekts."""

        project = self._projects.get(project_id)
        if project is None:
            return None

        open_tasks = self._memory.tasks.open_tasks(project_id=project_id)
        all_tasks = self._memory.tasks.list(project_id=project_id)
        done = len(all_tasks) - len(open_tasks)
        progress = (done / len(all_tasks)) if all_tasks else 0.0

        since = time.time() - 7 * 86400.0
        changes = self._documents.changed_since(project_id, since)
        milestone_progress = self._milestones.progress(project_id)

        return {
            "project_id": project_id,
            "name": project.get("name"),
            "kind": project.get("kind"),
            "description": project.get("description"),
            "path": project.get("path"),
            "task_progress": round(progress, 2),
            "tasks_total": len(all_tasks),
            "tasks_open": len(open_tasks),
            "open_tasks": [task.content for task in open_tasks[:8]],
            "recent_changes": [
                {"name": entry.get("name"), "path": entry.get("path")} for entry in changes[:8]
            ],
            "documents": len(self._documents.documents(project_id)),
            "literature": len(self._projects.entries(project_id, "literature")),
            "open_questions": [
                str(entry.get("text", ""))
                for entry in self._projects.entries(project_id, "open_questions")[-5:]
            ],
            "milestones": milestone_progress,
            "next_step": self._tasks.suggest_next_action(project_id=project_id),
            "last_opened_at": project.get("last_opened_at"),
        }

    def as_text(self, project_id: str) -> str:
        """Formuliert die Zusammenfassung als lesbare Antwort.

        Dies ist die Antwort auf die Frage "Woran arbeite ich gerade?".
        """

        summary = self.summarize(project_id)
        if summary is None:
            return "Es ist derzeit kein Projekt aktiv."

        lines = [f"Aktives Projekt: {summary['name']} ({summary['kind']})"]
        if summary.get("description"):
            lines.append(str(summary["description"]))

        lines.append(
            f"Arbeitsstand: {summary['tasks_total'] - summary['tasks_open']} von "
            f"{summary['tasks_total']} Aufgaben erledigt "
            f"({int(summary['task_progress'] * 100)} %)."
        )

        if summary["open_tasks"]:
            lines.append("Offene Aufgaben:")
            lines.extend(f"  • {task}" for task in summary["open_tasks"])

        if summary["recent_changes"]:
            lines.append("Letzte Änderungen:")
            lines.extend(f"  • {change['name']}" for change in summary["recent_changes"])

        if summary["open_questions"]:
            lines.append("Offene Fragen:")
            lines.extend(f"  • {question}" for question in summary["open_questions"])

        milestone = summary["milestones"].get("next")
        if milestone:
            lines.append(f"Nächster Meilenstein: {milestone.get('title')}")

        lines.append(summary["next_step"])
        return "\n".join(lines)

    def overview(self) -> list[dict[str, Any]]:
        """Kurzübersicht über alle Projekte."""

        results: list[dict[str, Any]] = []
        for project in self._projects.list():
            project_id = str(project.get("id"))
            open_tasks = self._memory.tasks.open_tasks(project_id=project_id)
            results.append(
                {
                    "id": project_id,
                    "name": project.get("name"),
                    "kind": project.get("kind"),
                    "open_tasks": len(open_tasks),
                    "last_opened_at": project.get("last_opened_at"),
                }
            )
        return results
