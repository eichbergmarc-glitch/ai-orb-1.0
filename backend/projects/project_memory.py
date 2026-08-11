"""Projektgedächtnis – persistente Ablage aller Projektdaten.

Jedes Projekt besitzt ein eigenes Gedächtnis mit Beschreibung, Zielen,
Aufgaben, Notizen, Gesprächen, Literatur, Dateien, Gliederungen,
Entscheidungen und offenen Fragen.

Projektwissen bleibt ausschließlich diesem Projekt zugeordnet; ein
Projektwechsel vermischt niemals Wissen.

Alle Projektdaten werden ausschließlich lokal gespeichert. Cloud-Dienste
erhalten keine Projektdaten, außer der Benutzer stimmt einer konkreten
Übertragung zu.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Die Bestandteile eines Projektgedächtnisses.
SECTIONS: tuple[str, ...] = (
    "notes",
    "literature",
    "files",
    "outlines",
    "decisions",
    "open_questions",
    "conversations",
)


def _empty_project(name: str, path: str | None, kind: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "description": "",
        "kind": kind,
        "path": path,
        "created_at": time.time(),
        "updated_at": time.time(),
        "last_opened_at": time.time(),
        "archived": False,
        **{section: [] for section in SECTIONS},
    }


class ProjectMemory:
    """Verwaltet die persistente Ablage aller Projekte."""

    def __init__(self, filename: str = "projects.json") -> None:
        self._store = JsonStore(filename, default={"projects": {}, "active": None})

    # --- Projekte ----------------------------------------------------------

    def create(self, name: str, *, path: str | None = None, kind: str = "allgemein") -> dict[str, Any]:
        """Legt ein neues Projekt an."""

        projects = dict(self._store.get("projects", {}) or {})
        project = _empty_project(name, path, kind)
        projects[project["id"]] = project
        self._store.set("projects", projects)
        logger.info("Projekt angelegt: %s (%s)", name, project["id"])
        return project

    def get(self, project_id: str) -> dict[str, Any] | None:
        """Liest ein Projekt."""

        return (self._store.get("projects", {}) or {}).get(project_id)

    def find_by_name(self, name: str) -> dict[str, Any] | None:
        """Sucht ein Projekt anhand seines Namens (Groß-/Kleinschreibung egal)."""

        needle = name.strip().lower()
        for project in (self._store.get("projects", {}) or {}).values():
            if str(project.get("name", "")).strip().lower() == needle:
                return project
        return None

    def find_by_path(self, path: str) -> dict[str, Any] | None:
        """Sucht ein Projekt anhand seines Ordnerpfads."""

        needle = str(path).replace("\\", "/").rstrip("/").lower()
        for project in (self._store.get("projects", {}) or {}).values():
            project_path = str(project.get("path") or "").replace("\\", "/").rstrip("/").lower()
            if project_path and project_path == needle:
                return project
        return None

    def list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        """Listet alle Projekte, nach letzter Nutzung sortiert."""

        projects = list((self._store.get("projects", {}) or {}).values())
        if not include_archived:
            projects = [project for project in projects if not project.get("archived")]
        projects.sort(key=lambda project: project.get("last_opened_at", 0.0), reverse=True)
        return projects

    def update(self, project_id: str, **changes: Any) -> dict[str, Any] | None:
        """Aktualisiert Kopfdaten eines Projekts."""

        projects = dict(self._store.get("projects", {}) or {})
        project = projects.get(project_id)
        if project is None:
            return None
        for key, value in changes.items():
            if key in ("name", "description", "kind", "path", "archived"):
                project[key] = value
        project["updated_at"] = time.time()
        self._store.set("projects", projects)
        return project

    def touch(self, project_id: str) -> None:
        """Vermerkt, dass ein Projekt gerade geöffnet wurde."""

        projects = dict(self._store.get("projects", {}) or {})
        project = projects.get(project_id)
        if project is None:
            return
        project["last_opened_at"] = time.time()
        self._store.set("projects", projects)

    def delete(self, project_id: str) -> bool:
        """Entfernt ein Projekt vollständig (Transparenzanforderung)."""

        projects = dict(self._store.get("projects", {}) or {})
        if projects.pop(project_id, None) is None:
            return False
        self._store.set("projects", projects)
        if self._store.get("active") == project_id:
            self._store.set("active", None)
        logger.info("Projekt gelöscht: %s", project_id)
        return True

    def archive(self, project_id: str) -> bool:
        """Archiviert ein Projekt, ohne es zu löschen."""

        return self.update(project_id, archived=True) is not None

    # --- Aktives Projekt ------------------------------------------------------

    def set_active(self, project_id: str | None) -> None:
        """Setzt das aktive Projekt."""

        self._store.set("active", project_id)
        if project_id:
            self.touch(project_id)

    def active(self) -> dict[str, Any] | None:
        """Gibt das aktive Projekt zurück."""

        active_id = self._store.get("active")
        return self.get(str(active_id)) if active_id else None

    # --- Abschnitte -----------------------------------------------------------

    def add_entry(self, project_id: str, section: str, content: Any) -> dict[str, Any] | None:
        """Ergänzt einen Eintrag in einem Projektabschnitt.

        Args:
            project_id: ID des Projekts.
            section: Einer der Abschnitte aus :data:`SECTIONS`.
            content: Der Eintragsinhalt (Text oder strukturiertes Dict).

        Returns:
            Der angelegte Eintrag, oder ``None`` bei unbekanntem Projekt
            oder Abschnitt.
        """

        if section not in SECTIONS:
            return None
        projects = dict(self._store.get("projects", {}) or {})
        project = projects.get(project_id)
        if project is None:
            return None

        entry: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "created_at": time.time(),
        }
        if isinstance(content, dict):
            entry.update(content)
        else:
            entry["text"] = str(content)

        entries = list(project.get(section, []) or [])
        entries.append(entry)
        project[section] = entries
        project["updated_at"] = time.time()
        self._store.set("projects", projects)
        return entry

    def entries(self, project_id: str, section: str) -> list[dict[str, Any]]:
        """Gibt alle Einträge eines Projektabschnitts zurück."""

        project = self.get(project_id)
        if project is None:
            return []
        return list(project.get(section, []) or [])

    def remove_entry(self, project_id: str, section: str, entry_id: str) -> bool:
        """Entfernt einen Eintrag aus einem Projektabschnitt."""

        projects = dict(self._store.get("projects", {}) or {})
        project = projects.get(project_id)
        if project is None or section not in SECTIONS:
            return False
        entries = list(project.get(section, []) or [])
        remaining = [entry for entry in entries if entry.get("id") != entry_id]
        if len(remaining) == len(entries):
            return False
        project[section] = remaining
        project["updated_at"] = time.time()
        self._store.set("projects", projects)
        return True

    def export(self, project_id: str) -> dict[str, Any] | None:
        """Exportiert ein Projekt vollständig (Transparenzanforderung)."""

        project = self.get(project_id)
        return dict(project) if project else None
