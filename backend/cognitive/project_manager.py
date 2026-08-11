"""Project Manager des Cognitive Core.

Dünne Steuerungsschicht über der Project Intelligence Engine
(:mod:`backend.projects`). Der Cognitive Core spricht ausschließlich mit
dieser Klasse; die Fachmodule der Project Engine werden von außen nicht
direkt angesprochen.

Der Orb merkt sich, welche Ordner, Dateien, Literatur, offenen Dokumente,
Gliederungen, Notizen und Gespräche zu einem Projekt gehören.
Projektwissen bleibt projektbezogen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.projects.project_engine import ProjectEngine
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class ProjectManager:
    """Steuert Projektauswahl, -kontext und -inhalte für das Cognitive Core."""

    def __init__(self, engine: ProjectEngine) -> None:
        self._engine = engine

    @property
    def engine(self) -> ProjectEngine:
        """Zugriff auf die zugrunde liegende Project Engine."""

        return self._engine

    # --- Auswahl ---------------------------------------------------------------

    def active_id(self) -> str | None:
        """ID des aktiven Projekts."""

        return self._engine.active_project_id()

    def activate_by_name(self, name: str) -> dict[str, Any]:
        """Aktiviert ein Projekt anhand seines Namens.

        Ist der Name nicht eindeutig oder unbekannt, wird nicht geraten,
        sondern eine Rückfrage zurückgegeben.
        """

        project = self._engine.storage.find_by_name(name)
        if project is None:
            candidates = [
                item["name"]
                for item in self._engine.list_projects()
                if name.lower() in str(item.get("name", "")).lower()
            ]
            if len(candidates) == 1:
                project = self._engine.storage.find_by_name(candidates[0])
            elif len(candidates) > 1:
                return {
                    "activated": False,
                    "requires_clarification": True,
                    "candidates": candidates,
                    "message": "Welches Projekt meinst du? " + ", ".join(candidates),
                }
            else:
                return {
                    "activated": False,
                    "message": f"Ich kenne kein Projekt mit dem Namen „{name}“.",
                }

        return self._engine.activate(str(project["id"]))

    def activate_by_path(self, path: str | Path) -> dict[str, Any]:
        """Aktiviert das Projekt, zu dem ein Verzeichnis gehört.

        Ist noch kein Projekt hinterlegt, wird die Erkennung angestoßen.
        """

        project = self._engine.storage.find_by_path(str(path))
        if project is not None:
            return self._engine.activate(str(project["id"]))
        return self._engine.detect_and_register(path)

    def deactivate(self) -> None:
        """Hebt die Projektzuordnung auf."""

        self._engine.deactivate()

    # --- Kontext ----------------------------------------------------------------

    def context_prompt(self) -> str:
        """Der Kontext des aktiven Projekts als Text für Modellanfragen."""

        return self._engine.context_prompt()

    def summary_text(self) -> str:
        """Beantwortet "Woran arbeite ich gerade?"."""

        return self._engine.summary_text()

    def overview(self) -> list[dict[str, Any]]:
        """Kurzübersicht über alle Projekte."""

        return self._engine.summaries.overview()

    # --- Inhalte -----------------------------------------------------------------

    def remember_decision(self, text: str) -> bool:
        """Hält eine Entscheidung im aktiven Projekt fest."""

        return self._engine.add_decision(text) is not None

    def remember_open_question(self, text: str) -> bool:
        """Vermerkt eine offene Frage im aktiven Projekt."""

        return self._engine.add_open_question(text) is not None

    def remember_note(self, text: str) -> bool:
        """Legt eine Notiz im aktiven Projekt ab."""

        return self._engine.add_note(text) is not None

    def track_document(self, path: str | Path, *, role: str = "dokument") -> bool:
        """Nimmt ein Dokument in die Verfolgung des aktiven Projekts auf."""

        return self._engine.track_document(path, role=role) is not None

    # --- Sitzungen -----------------------------------------------------------------

    def begin_session(self) -> dict[str, Any]:
        """Startet eine Arbeitssitzung im aktiven Projekt."""

        project_id = self.active_id()
        if project_id is None:
            return {"started": False, "message": "Es ist kein Projekt aktiv."}
        return self._engine.sessions.begin(project_id)

    async def end_session(self, open_points: list[str] | None = None) -> dict[str, Any]:
        """Beendet die laufende Sitzung und sichert offene Punkte."""

        return await self._engine.sessions.end(open_points=open_points)
