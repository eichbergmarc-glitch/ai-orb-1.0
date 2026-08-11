"""Document Tracker – verfolgt Dokumente, Versionen und Exzerpte.

Verfolgt werden Dokumente, deren Versionen (über Änderungszeit und
Inhaltsprüfsumme), Notizen, Exzerpte, Verknüpfungen, Quellen und
Kommentare. Dokumente werden automatisch dem aktiven Projekt zugeordnet.

Es wird ausschließlich mit Metadaten gearbeitet: Dokumentinhalte werden
nicht kopiert, sondern nur referenziert.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from backend.projects.project_memory import ProjectMemory
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


class DocumentTracker:
    """Verfolgt Dokumente eines Projekts."""

    def __init__(self, project_memory: ProjectMemory) -> None:
        self._projects = project_memory

    # --- Registrierung ------------------------------------------------------

    def track(self, project_id: str, path: str | Path, *, role: str = "dokument") -> dict[str, Any] | None:
        """Nimmt ein Dokument in die Verfolgung auf oder aktualisiert es.

        Args:
            project_id: Zugehöriges Projekt.
            path: Pfad zur Datei.
            role: Rolle des Dokuments (``dokument``, ``literatur``,
                ``gliederung``, ``notiz``).

        Returns:
            Der Dokumenteintrag, oder ``None``, wenn die Datei fehlt.
        """

        file_path = Path(path).expanduser()
        if not file_path.exists() or not file_path.is_file():
            logger.warning("Dokument nicht gefunden: %s", file_path)
            return None

        section = "literature" if role == "literatur" else "files"
        existing = self.find(project_id, file_path)
        checksum = self._checksum(file_path)
        stat = file_path.stat()

        if existing is not None:
            versions = list(existing.get("versions", []) or [])
            if not versions or versions[-1].get("checksum") != checksum:
                versions.append(
                    {
                        "checksum": checksum,
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "seen_at": time.time(),
                    }
                )
                existing["versions"] = versions
                existing["updated_at"] = time.time()
                self._replace(project_id, section, existing)
                logger.info("Neue Version erkannt: %s", file_path.name)
            return existing

        entry = self._projects.add_entry(
            project_id,
            section,
            {
                "path": str(file_path),
                "name": file_path.name,
                "suffix": file_path.suffix.lower(),
                "role": role,
                "notes": [],
                "excerpts": [],
                "comments": [],
                "links": [],
                "source": None,
                "updated_at": time.time(),
                "versions": [
                    {
                        "checksum": checksum,
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "seen_at": time.time(),
                    }
                ],
            },
        )
        if entry is not None:
            logger.info("Dokument aufgenommen: %s (%s)", file_path.name, role)
        return entry

    def find(self, project_id: str, path: str | Path) -> dict[str, Any] | None:
        """Sucht ein verfolgtes Dokument anhand seines Pfads."""

        needle = str(Path(path).expanduser())
        for section in ("files", "literature"):
            for entry in self._projects.entries(project_id, section):
                if entry.get("path") == needle:
                    return entry
        return None

    def documents(self, project_id: str, *, role: str | None = None) -> list[dict[str, Any]]:
        """Listet alle verfolgten Dokumente eines Projekts."""

        entries = self._projects.entries(project_id, "files") + self._projects.entries(
            project_id, "literature"
        )
        if role is not None:
            entries = [entry for entry in entries if entry.get("role") == role]
        return entries

    # --- Anreicherung ---------------------------------------------------------

    def add_note(self, project_id: str, path: str | Path, note: str) -> bool:
        """Ergänzt eine Notiz zu einem Dokument."""

        return self._append_to_list(project_id, path, "notes", {"text": note, "at": time.time()})

    def add_excerpt(
        self, project_id: str, path: str | Path, text: str, *, page: int | None = None
    ) -> bool:
        """Ergänzt ein Exzerpt (Zitat) zu einem Dokument."""

        return self._append_to_list(
            project_id, path, "excerpts", {"text": text, "page": page, "at": time.time()}
        )

    def add_comment(self, project_id: str, path: str | Path, comment: str) -> bool:
        """Ergänzt einen Kommentar zu einem Dokument."""

        return self._append_to_list(
            project_id, path, "comments", {"text": comment, "at": time.time()}
        )

    def link(self, project_id: str, path: str | Path, target: str, relation: str = "bezug") -> bool:
        """Verknüpft ein Dokument mit einem anderen Element."""

        return self._append_to_list(
            project_id, path, "links", {"target": target, "relation": relation}
        )

    def set_source(self, project_id: str, path: str | Path, source: str) -> bool:
        """Hinterlegt die Quelle eines Dokuments (z. B. Zitationsangabe)."""

        entry = self.find(project_id, path)
        if entry is None:
            return False
        entry["source"] = source
        entry["updated_at"] = time.time()
        section = "literature" if entry.get("role") == "literatur" else "files"
        self._replace(project_id, section, entry)
        return True

    # --- Änderungen ------------------------------------------------------------

    def changed_since(self, project_id: str, since: float) -> list[dict[str, Any]]:
        """Gibt alle Dokumente zurück, die seit einem Zeitpunkt geändert wurden."""

        changed: list[dict[str, Any]] = []
        for entry in self.documents(project_id):
            versions = entry.get("versions", []) or []
            if versions and float(versions[-1].get("modified_at", 0.0)) > since:
                changed.append(entry)
        return changed

    def rescan(self, project_id: str) -> list[dict[str, Any]]:
        """Prüft alle verfolgten Dokumente auf neue Versionen."""

        updated: list[dict[str, Any]] = []
        for entry in list(self.documents(project_id)):
            path = entry.get("path")
            if not path:
                continue
            before = len(entry.get("versions", []) or [])
            refreshed = self.track(project_id, path, role=str(entry.get("role", "dokument")))
            if refreshed and len(refreshed.get("versions", []) or []) > before:
                updated.append(refreshed)
        return updated

    # --- Interne Hilfsfunktionen --------------------------------------------------

    def _append_to_list(
        self, project_id: str, path: str | Path, field: str, value: dict[str, Any]
    ) -> bool:
        entry = self.find(project_id, path)
        if entry is None:
            return False
        items = list(entry.get(field, []) or [])
        items.append(value)
        entry[field] = items
        entry["updated_at"] = time.time()
        section = "literature" if entry.get("role") == "literatur" else "files"
        self._replace(project_id, section, entry)
        return True

    def _replace(self, project_id: str, section: str, entry: dict[str, Any]) -> None:
        """Ersetzt einen Eintrag im Projektgedächtnis."""

        entry_id = entry.get("id")
        if not entry_id:
            return
        self._projects.remove_entry(project_id, section, str(entry_id))
        self._projects.add_entry(project_id, section, entry)

    @staticmethod
    def _checksum(path: Path, *, chunk_size: int = 65536, max_bytes: int = 8 * 1024 * 1024) -> str:
        """Berechnet eine Inhaltsprüfsumme (bei großen Dateien nur der Anfang)."""

        digest = hashlib.sha256()
        read = 0
        try:
            with path.open("rb") as handle:
                while read < max_bytes:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    read += len(chunk)
        except OSError:
            return ""
        return digest.hexdigest()
