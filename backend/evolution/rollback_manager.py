"""Rollback Manager – jede Änderung muss rückgängig zu machen sein.

Zu jeder übernommenen Änderung werden Branch, Commit, Testergebnisse,
Version und Änderungsbeschreibung gespeichert. Zusätzlich wird vor jeder
Übernahme eine vollständige Sicherung der betroffenen Dateien angelegt.
"""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir, get_project_root
from backend.utils.store import JsonStore

logger = get_logger(__name__)


@dataclass
class RestorePoint:
    """Ein Wiederherstellungspunkt vor einer Änderung."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    patch_id: str = ""
    title: str = ""
    description: str = ""
    branch: str = ""
    commit: str = ""
    version: str = ""
    files: list[str] = field(default_factory=list)
    new_files: list[str] = field(default_factory=list)
    backup_path: str = ""
    test_summary: str = ""
    created_at: float = field(default_factory=time.time)
    restored_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patch_id": self.patch_id,
            "title": self.title,
            "description": self.description,
            "branch": self.branch,
            "commit": self.commit,
            "version": self.version,
            "files": self.files,
            "new_files": self.new_files,
            "backup_path": self.backup_path,
            "test_summary": self.test_summary,
            "created_at": self.created_at,
            "restored_at": self.restored_at,
        }


class RollbackManager:
    """Legt Wiederherstellungspunkte an und setzt Änderungen zurück."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_project_root()
        self._store = JsonStore("rollback.json", default={"points": []})
        self._backup_root = get_data_dir() / "rollback"
        self._backup_root.mkdir(parents=True, exist_ok=True)

    def create_point(
        self,
        *,
        patch_id: str,
        title: str,
        description: str,
        branch: str,
        commit: str,
        version: str,
        files: list[str],
        test_summary: str = "",
    ) -> RestorePoint:
        """Legt vor einer Übernahme einen Wiederherstellungspunkt an.

        Args:
            patch_id: Der zugehörige Patch.
            title: Kurzbeschreibung der Änderung.
            description: Ausführliche Beschreibung.
            branch: Der Git-Branch des Patches.
            commit: Der Commit des Patches.
            version: Die Version vor der Änderung.
            files: Die betroffenen Dateien (relative Pfade).
            test_summary: Zusammenfassung der Testergebnisse.

        Returns:
            Der angelegte Wiederherstellungspunkt.
        """

        point = RestorePoint(
            patch_id=patch_id,
            title=title,
            description=description,
            branch=branch,
            commit=commit,
            version=version,
            files=list(files),
            new_files=[
                relative for relative in files if not (self._root / relative).exists()
            ],
            test_summary=test_summary,
        )

        backup_dir = self._backup_root / point.id
        backup_dir.mkdir(parents=True, exist_ok=True)

        for relative in files:
            source = self._root / relative
            if not source.exists():
                continue
            target = backup_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        point.backup_path = str(backup_dir)
        points = list(self._store.get("points", []) or [])
        points.append(point.to_dict())
        self._store.set("points", points)

        logger.info(
            "Wiederherstellungspunkt %s angelegt (%d Datei(en)).", point.id, len(files)
        )
        return point

    def rollback(self, point_id: str) -> dict[str, Any]:
        """Setzt eine Änderung vollständig zurück.

        Args:
            point_id: Die ID des Wiederherstellungspunkts.

        Returns:
            Ein Bericht über die Wiederherstellung.
        """

        points = list(self._store.get("points", []) or [])
        target_point = next((item for item in points if item.get("id") == point_id), None)
        if target_point is None:
            return {"restored": False, "message": "Der Wiederherstellungspunkt ist unbekannt."}

        backup_dir = Path(str(target_point.get("backup_path", "")))
        if not backup_dir.exists():
            return {"restored": False, "message": "Die Sicherung ist nicht mehr vorhanden."}

        restored: list[str] = []
        removed: list[str] = []
        failed: list[str] = []

        for relative in target_point.get("files", []) or []:
            source = backup_dir / relative
            destination = self._root / relative
            if relative in (target_point.get("new_files", []) or []):
                try:
                    if destination.exists():
                        destination.unlink()
                    removed.append(relative)
                except OSError as error:
                    logger.error("Entfernen der neuen Datei %s fehlgeschlagen: %s", relative, error)
                    failed.append(relative)
                continue
            if not source.exists():
                failed.append(relative)
                continue
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                restored.append(relative)
            except OSError as error:
                logger.error("Wiederherstellung von %s fehlgeschlagen: %s", relative, error)
                failed.append(relative)

        target_point["restored_at"] = time.time()
        self._store.set("points", points)

        logger.info("Rollback %s: %d Datei(en) wiederhergestellt.", point_id, len(restored))
        return {
            "restored": bool(restored or removed),
            "restored_files": restored,
            "removed_files": removed,
            "failed_files": failed,
            "message": (
                f"{len(restored)} Datei(en) wiederhergestellt und "
                f"{len(removed)} neu angelegte Datei(en) entfernt."
                if restored or removed
                else "Es konnte keine Datei wiederhergestellt werden."
            ),
        }

    def latest(self) -> dict[str, Any] | None:
        """Der zuletzt angelegte Wiederherstellungspunkt."""

        points = list(self._store.get("points", []) or [])
        return points[-1] if points else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        """Alle Wiederherstellungspunkte, neueste zuletzt."""

        return list(self._store.get("points", []) or [])[-limit:]

    def undo_last(self) -> dict[str, Any]:
        """Macht die zuletzt übernommene Änderung rückgängig."""

        point = self.latest()
        if point is None:
            return {"restored": False, "message": "Es wurde noch keine Änderung übernommen."}
        return self.rollback(str(point["id"]))
