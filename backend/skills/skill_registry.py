"""Skill Registry – Verzeichnis aller installierten Skills.

Gespeichert werden Status, Version, Kompatibilität, Berechtigungen, letzte
Aktualisierung und Fehlerstatus jedes Skills.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Zustände eines Skills.
SKILL_STATUSES: tuple[str, ...] = ("installiert", "aktiv", "deaktiviert", "fehlerhaft")


@dataclass
class SkillManifest:
    """Die Beschreibung eines Skills (dessen ``skill.json``)."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = "unbekannt"
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    entrypoint: str = "skill.py"
    min_orb_version: str = "0.1.0"
    documentation: str = ""
    configuration: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillManifest":
        known = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**known)  # type: ignore[arg-type]


@dataclass
class SkillRecord:
    """Der Eintrag eines Skills in der Registry."""

    manifest: SkillManifest
    status: str = "installiert"
    installed_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    granted_permissions: list[str] = field(default_factory=list)
    last_error: str = ""
    compatible: bool = True
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "status": self.status,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "granted_permissions": self.granted_permissions,
            "last_error": self.last_error,
            "compatible": self.compatible,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillRecord":
        return cls(
            manifest=SkillManifest.from_dict(data.get("manifest", {})),
            status=str(data.get("status", "installiert")),
            installed_at=float(data.get("installed_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            granted_permissions=list(data.get("granted_permissions", [])),
            last_error=str(data.get("last_error", "")),
            compatible=bool(data.get("compatible", True)),
            path=str(data.get("path", "")),
        )


class SkillRegistry:
    """Verwaltet alle installierten Skills."""

    def __init__(self, filename: str = "skills.json") -> None:
        self._store = JsonStore(filename, default={"skills": {}})
        self._records: dict[str, SkillRecord] = {}
        for name, data in (self._store.get("skills", {}) or {}).items():
            self._records[name] = SkillRecord.from_dict(data)

    def _persist(self) -> None:
        self._store.set(
            "skills", {name: record.to_dict() for name, record in self._records.items()}
        )

    def add(self, record: SkillRecord) -> SkillRecord:
        """Nimmt einen Skill in die Registry auf."""

        self._records[record.manifest.name] = record
        self._persist()
        logger.info("Skill registriert: %s %s", record.manifest.name, record.manifest.version)
        return record

    def get(self, name: str) -> SkillRecord | None:
        """Liest einen Skill-Eintrag."""

        return self._records.get(name)

    def remove(self, name: str) -> bool:
        """Entfernt einen Skill aus der Registry."""

        if self._records.pop(name, None) is None:
            return False
        self._persist()
        return True

    def set_status(self, name: str, status: str, *, error: str = "") -> bool:
        """Ändert den Status eines Skills."""

        record = self._records.get(name)
        if record is None or status not in SKILL_STATUSES:
            return False
        record.status = status
        record.last_error = error
        record.updated_at = time.time()
        self._persist()
        return True

    def grant(self, name: str, permission: str) -> bool:
        """Erteilt einem Skill eine Berechtigung."""

        record = self._records.get(name)
        if record is None:
            return False
        if permission not in record.granted_permissions:
            record.granted_permissions.append(permission)
        record.updated_at = time.time()
        self._persist()
        return True

    def revoke(self, name: str, permission: str) -> bool:
        """Entzieht einem Skill eine Berechtigung."""

        record = self._records.get(name)
        if record is None:
            return False
        if permission in record.granted_permissions:
            record.granted_permissions.remove(permission)
        record.updated_at = time.time()
        self._persist()
        return True

    def list(self, *, status: str | None = None) -> list[SkillRecord]:
        """Listet alle Skills, optional nach Status gefiltert."""

        records = list(self._records.values())
        if status is not None:
            records = [record for record in records if record.status == status]
        records.sort(key=lambda record: record.manifest.name)
        return records

    def active(self) -> list[SkillRecord]:
        """Alle aktiven Skills."""

        return self.list(status="aktiv")

    def snapshot(self) -> dict[str, Any]:
        """Übersicht für die Transparenzansicht."""

        return {name: record.to_dict() for name, record in self._records.items()}
