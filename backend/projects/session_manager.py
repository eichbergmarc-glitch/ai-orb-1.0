"""Session Manager – Beginn und Ende einer Arbeitssitzung.

Beim Arbeitsbeginn: Projekt erkennen, Kontext laden, offene Aufgaben
anzeigen, letzte Sitzung zusammenfassen und wichtige Änderungen
hervorheben.

Beim Arbeitsende: Projektstatus speichern, offene Punkte sichern und eine
Zusammenfassung erstellen.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.projects.document_tracker import DocumentTracker
from backend.projects.project_memory import ProjectMemory
from backend.projects.project_summary import ProjectSummary
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)


class SessionManager:
    """Verwaltet Arbeitssitzungen je Projekt."""

    def __init__(
        self,
        project_memory: ProjectMemory,
        documents: DocumentTracker,
        summaries: ProjectSummary,
        filename: str = "sessions.json",
    ) -> None:
        self._projects = project_memory
        self._documents = documents
        self._summaries = summaries
        self._store = JsonStore(filename, default={"sessions": [], "current": None})

    # --- Sitzungsbeginn ------------------------------------------------------

    def begin(self, project_id: str) -> dict[str, Any]:
        """Startet eine Arbeitssitzung für ein Projekt.

        Returns:
            Ein Bericht mit Kontext, offenen Aufgaben, der Zusammenfassung
            der letzten Sitzung und den seither erfolgten Änderungen.
        """

        project = self._projects.get(project_id)
        if project is None:
            return {"started": False, "message": "Unbekanntes Projekt."}

        last = self.last_session(project_id)
        since = float(last.get("ended_at", 0.0)) if last else 0.0
        changes = self._documents.changed_since(project_id, since) if since else []

        session: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "started_at": time.time(),
            "ended_at": None,
            "summary": "",
            "open_points": [],
        }
        self._store.set("current", session)
        self._projects.set_active(project_id)

        summary = self._summaries.summarize(project_id) or {}
        logger.info("Sitzung für Projekt '%s' begonnen.", project.get("name"))

        return {
            "started": True,
            "session_id": session["id"],
            "project": {"id": project_id, "name": project.get("name"), "kind": project.get("kind")},
            "open_tasks": summary.get("open_tasks", []),
            "last_session_summary": (last or {}).get("summary", ""),
            "changed_since_last_session": [
                {"name": entry.get("name"), "path": entry.get("path")} for entry in changes[:10]
            ],
            "next_step": summary.get("next_step", ""),
            "message": self._format_start_message(project, last, changes, summary),
        }

    @staticmethod
    def _format_start_message(
        project: dict[str, Any],
        last: dict[str, Any] | None,
        changes: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> str:
        lines = [f"Willkommen zurück im Projekt „{project.get('name')}“."]
        if last and last.get("summary"):
            lines.append(f"Letzte Sitzung: {last['summary']}")
        if last and last.get("open_points"):
            lines.append("Offen geblieben: " + "; ".join(str(p) for p in last["open_points"][:5]))
        if changes:
            lines.append(
                f"Seit deiner letzten Sitzung wurden {len(changes)} Datei(en) geändert: "
                + ", ".join(str(entry.get("name")) for entry in changes[:5])
            )
        if summary.get("next_step"):
            lines.append(str(summary["next_step"]))
        return "\n".join(lines)

    # --- Sitzungsende ---------------------------------------------------------

    async def end(self, summary_text: str | None = None, open_points: list[str] | None = None) -> dict[str, Any]:
        """Beendet die laufende Sitzung und sichert deren Zustand.

        Args:
            summary_text: Optionale Zusammenfassung. Fehlt sie, wird eine
                aus dem Projektstand erzeugt.
            open_points: Punkte, die offen geblieben sind.
        """

        current = self._store.get("current")
        if not current:
            return {"ended": False, "message": "Es läuft derzeit keine Sitzung."}

        project_id = str(current.get("project_id"))
        if summary_text is None:
            project_summary = self._summaries.summarize(project_id) or {}
            summary_text = (
                f"{project_summary.get('tasks_total', 0) - project_summary.get('tasks_open', 0)} von "
                f"{project_summary.get('tasks_total', 0)} Aufgaben erledigt; "
                f"nächster Schritt: {project_summary.get('next_step', 'offen')}"
            )

        current["ended_at"] = time.time()
        current["summary"] = summary_text
        current["open_points"] = list(open_points or [])
        current["duration_seconds"] = current["ended_at"] - float(current.get("started_at", current["ended_at"]))

        sessions = list(self._store.get("sessions", []) or [])
        sessions.append(current)
        self._store.update({"sessions": sessions, "current": None})

        logger.info(
            "Sitzung beendet (Projekt %s, Dauer %.0f s).",
            project_id,
            current["duration_seconds"],
        )
        return {
            "ended": True,
            "session_id": current.get("id"),
            "summary": summary_text,
            "open_points": current["open_points"],
            "duration_seconds": current["duration_seconds"],
        }

    # --- Abfragen ---------------------------------------------------------------

    def current(self) -> dict[str, Any] | None:
        """Die laufende Sitzung, falls vorhanden."""

        return self._store.get("current")

    def last_session(self, project_id: str) -> dict[str, Any] | None:
        """Die zuletzt abgeschlossene Sitzung eines Projekts."""

        sessions = [
            session
            for session in (self._store.get("sessions", []) or [])
            if session.get("project_id") == project_id and session.get("ended_at")
        ]
        if not sessions:
            return None
        sessions.sort(key=lambda session: float(session.get("ended_at", 0.0)))
        return sessions[-1]

    def history(self, project_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Sitzungsverlauf, optional auf ein Projekt begrenzt."""

        sessions = list(self._store.get("sessions", []) or [])
        if project_id is not None:
            sessions = [session for session in sessions if session.get("project_id") == project_id]
        return sessions[-limit:]
