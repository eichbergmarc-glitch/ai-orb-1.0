"""Project Context – der Projektbezug jeder Antwort.

Während eines Gesprächs kennt der Orb das aktuelle Kapitel, die offenen
Aufgaben, die relevante Literatur, die letzten Änderungen, wichtige
Entscheidungen und die noch offenen Fragen des aktiven Projekts.

Antworten werden dadurch immer projektbezogen erzeugt, ohne dass der
Benutzer den Zusammenhang bei jedem Gespräch erneut erklären muss.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.memory.memory_engine import MemoryEngine
from backend.projects.document_tracker import DocumentTracker
from backend.projects.milestone_manager import MilestoneManager
from backend.projects.project_memory import ProjectMemory


@dataclass
class ProjectContextData:
    """Die für eine Antwort relevanten Projektinformationen."""

    project_id: str
    name: str
    kind: str = "allgemein"
    description: str = ""
    current_chapter: str = ""
    open_tasks: list[str] = field(default_factory=list)
    literature: list[str] = field(default_factory=list)
    recent_changes: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    next_milestone: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "current_chapter": self.current_chapter,
            "open_tasks": self.open_tasks,
            "literature": self.literature,
            "recent_changes": self.recent_changes,
            "decisions": self.decisions,
            "open_questions": self.open_questions,
            "next_milestone": self.next_milestone,
        }

    def to_prompt(self) -> str:
        """Formt den Projektkontext in einen kompakten Text für Modellanfragen."""

        lines = [f"Aktives Projekt: {self.name} ({self.kind})"]
        if self.description:
            lines.append(f"Beschreibung: {self.description}")
        if self.current_chapter:
            lines.append(f"Aktueller Abschnitt: {self.current_chapter}")
        if self.open_tasks:
            lines.append("Offene Aufgaben: " + "; ".join(self.open_tasks[:5]))
        if self.literature:
            lines.append("Verwendete Literatur: " + "; ".join(self.literature[:5]))
        if self.decisions:
            lines.append("Bereits getroffene Entscheidungen: " + "; ".join(self.decisions[:5]))
        if self.open_questions:
            lines.append("Noch offene Fragen: " + "; ".join(self.open_questions[:5]))
        if self.recent_changes:
            lines.append("Zuletzt geändert: " + "; ".join(self.recent_changes[:5]))
        if self.next_milestone:
            lines.append(f"Nächster Meilenstein: {self.next_milestone}")
        return "\n".join(lines)


class ProjectContext:
    """Stellt den Kontext des aktiven Projekts bereit."""

    def __init__(
        self,
        project_memory: ProjectMemory,
        memory: MemoryEngine,
        documents: DocumentTracker,
        milestones: MilestoneManager,
    ) -> None:
        self._projects = project_memory
        self._memory = memory
        self._documents = documents
        self._milestones = milestones

    def build(self, project_id: str) -> ProjectContextData | None:
        """Baut den Kontext eines Projekts auf.

        Args:
            project_id: Das Projekt, dessen Kontext benötigt wird.

        Returns:
            Der Projektkontext, oder ``None``, wenn das Projekt unbekannt ist.
        """

        project = self._projects.get(project_id)
        if project is None:
            return None

        context = ProjectContextData(
            project_id=project_id,
            name=str(project.get("name", "")),
            kind=str(project.get("kind", "allgemein")),
            description=str(project.get("description", "")),
        )

        outlines = self._projects.entries(project_id, "outlines")
        if outlines:
            context.current_chapter = str(outlines[-1].get("text", ""))[:120]

        context.open_tasks = [
            task.content for task in self._memory.tasks.open_tasks(project_id=project_id)[:10]
        ]

        context.literature = [
            str(entry.get("name") or entry.get("source") or entry.get("text", ""))
            for entry in self._projects.entries(project_id, "literature")[:10]
        ]

        since = time.time() - 7 * 86400.0
        context.recent_changes = [
            str(entry.get("name", "")) for entry in self._documents.changed_since(project_id, since)[:5]
        ]

        context.decisions = [
            str(entry.get("text", "")) for entry in self._projects.entries(project_id, "decisions")[-5:]
        ]
        context.open_questions = [
            str(entry.get("text", ""))
            for entry in self._projects.entries(project_id, "open_questions")[-5:]
        ]

        upcoming = self._milestones.list(project_id, status="geplant") or self._milestones.list(
            project_id, status="laufend"
        )
        if upcoming:
            context.next_milestone = str(upcoming[0].get("title", ""))

        return context

    def as_prompt(self, project_id: str) -> str:
        """Bequemlichkeitsfunktion: Kontext direkt als Prompt-Text."""

        context = self.build(project_id)
        return context.to_prompt() if context else ""
