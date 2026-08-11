"""Workspace Manager – merkt sich den Arbeitszustand eines Projekts.

Gespeichert werden geöffnete Programme, Fensteranordnung, Terminals,
Editoren, PDFs, Dokumente und Arbeitsbereiche. Beim erneuten Öffnen eines
Projekts kann der Orb den letzten Arbeitszustand wiederherstellen – aber
ausschließlich dann, wenn der Benutzer dies wünscht.

Browser-Tabs werden **nur mit ausdrücklicher Zustimmung** erfasst; ohne
Zustimmung bleibt dieser Bereich leer.
"""

from __future__ import annotations

import time
from typing import Any

from backend.config import get_config
from backend.system.desktop_control import DesktopControl
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)


class WorkspaceManager:
    """Speichert und stellt Arbeitszustände wieder her."""

    def __init__(self, desktop: DesktopControl | None = None, filename: str = "workspaces.json") -> None:
        config = get_config()
        workspace_config = config.section("workspace")

        self._store = JsonStore(filename, default={"workspaces": {}})
        self._desktop = desktop or DesktopControl()
        self._track_browser_tabs = bool(workspace_config.get("track_browser_tabs", False))
        self._restore_enabled = bool(workspace_config.get("restore_on_open", False))

    # --- Speichern -----------------------------------------------------------

    def save(
        self,
        project_id: str,
        *,
        applications: list[str] | None = None,
        windows: list[dict[str, Any]] | None = None,
        documents: list[str] | None = None,
        terminals: list[str] | None = None,
        browser_tabs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Speichert den aktuellen Arbeitszustand eines Projekts.

        Args:
            project_id: Zugehöriges Projekt.
            applications: Namen der geöffneten Programme.
            windows: Fensterpositionen und -größen.
            documents: Pfade geöffneter Dokumente.
            terminals: Arbeitsverzeichnisse offener Terminals.
            browser_tabs: Offene Browser-Tabs. Werden nur übernommen, wenn
                ``workspace.track_browser_tabs`` in ``config.yaml``
                aktiviert wurde.
        """

        workspaces = dict(self._store.get("workspaces", {}) or {})
        state: dict[str, Any] = {
            "project_id": project_id,
            "applications": list(applications or []),
            "windows": list(windows or []),
            "documents": list(documents or []),
            "terminals": list(terminals or []),
            "browser_tabs": list(browser_tabs or []) if self._track_browser_tabs else [],
            "saved_at": time.time(),
        }
        if browser_tabs and not self._track_browser_tabs:
            logger.info(
                "Browser-Tabs wurden nicht gespeichert "
                "(workspace.track_browser_tabs ist deaktiviert)."
            )

        workspaces[project_id] = state
        self._store.set("workspaces", workspaces)
        logger.info("Arbeitszustand für Projekt %s gespeichert.", project_id)
        return state

    def get(self, project_id: str) -> dict[str, Any] | None:
        """Liest den gespeicherten Arbeitszustand eines Projekts."""

        return (self._store.get("workspaces", {}) or {}).get(project_id)

    # --- Wiederherstellen ------------------------------------------------------

    def restore(self, project_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Stellt den letzten Arbeitszustand wieder her.

        Args:
            project_id: Das Projekt, dessen Zustand wiederhergestellt wird.
            confirmed: Muss ``True`` sein, damit tatsächlich Programme
                gestartet werden. Ohne Bestätigung wird nur beschrieben,
                was wiederhergestellt würde.

        Returns:
            Ein Bericht darüber, was wiederhergestellt wurde bzw. würde.
        """

        state = self.get(project_id)
        if state is None:
            return {"restored": False, "message": "Für dieses Projekt ist kein Arbeitszustand gespeichert."}

        applications = list(state.get("applications", []) or [])
        documents = list(state.get("documents", []) or [])

        if not confirmed:
            return {
                "restored": False,
                "requires_confirmation": True,
                "message": (
                    "Soll ich den letzten Arbeitszustand wiederherstellen? "
                    f"Das würde {len(applications)} Programm(e) starten und "
                    f"{len(documents)} Dokument(e) öffnen."
                ),
                "applications": applications,
                "documents": documents,
            }

        started: list[str] = []
        failed: list[str] = []
        for application in applications:
            result = self._desktop.launch(application)
            (started if result.success else failed).append(application)

        opened: list[str] = []
        for document in documents:
            result = self._desktop.open_path(document)
            if result.success:
                opened.append(document)
            else:
                failed.append(document)

        logger.info(
            "Arbeitszustand wiederhergestellt: %d Programme, %d Dokumente.",
            len(started),
            len(opened),
        )
        return {
            "restored": True,
            "started": started,
            "opened": opened,
            "failed": failed,
            "message": f"{len(started)} Programm(e) und {len(opened)} Dokument(e) wiederhergestellt.",
        }

    @property
    def restore_on_open(self) -> bool:
        """Ob der Orb beim Projektwechsel automatisch nachfragen soll."""

        return self._restore_enabled

    def forget(self, project_id: str) -> bool:
        """Löscht den gespeicherten Arbeitszustand eines Projekts."""

        workspaces = dict(self._store.get("workspaces", {}) or {})
        if workspaces.pop(project_id, None) is None:
            return False
        self._store.set("workspaces", workspaces)
        return True
