"""Skill Updater – prüft und führt Aktualisierungen durch.

Vor jedem Update wird geprüft:

* Kompatibilität mit der aktuellen AI-Orb-Version
* welche Änderungen enthalten sind
* ob Sicherheitsrisiken bestehen
* ob neue Berechtigungen verlangt werden

Vor größeren Änderungen – insbesondere bei neuen Berechtigungen oder einem
Hauptversionssprung – wird der Benutzer ausdrücklich informiert und um
Zustimmung gebeten. Jeder Skill besitzt eine Änderungshistorie und kann
zurückgerollt werden.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.skills.skill_installer import SkillInstaller
from backend.skills.skill_registry import SkillManifest, SkillRegistry
from backend.skills.skill_validator import SkillValidator, ValidationReport
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir
from backend.utils.store import JsonStore

logger = get_logger(__name__)


def _parse_version(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError:
        return (0,)


@dataclass
class UpdateProposal:
    """Der Vorschlag für eine Skill-Aktualisierung."""

    skill: str
    current_version: str
    new_version: str
    validation: ValidationReport
    new_permissions: list[str] = field(default_factory=list)
    removed_permissions: list[str] = field(default_factory=list)
    is_major: bool = False
    source_path: str = ""

    @property
    def needs_explicit_consent(self) -> bool:
        """Ob eine ausdrückliche Zustimmung erforderlich ist."""

        return bool(self.new_permissions) or self.is_major or bool(
            self.validation.security_findings
        )

    def describe(self) -> str:
        """Formuliert den Vorschlag verständlich."""

        lines = [
            f"Aktualisierung für „{self.skill}“: "
            f"{self.current_version} → {self.new_version}"
        ]
        if self.is_major:
            lines.append("Dies ist ein größeres Update; es kann Verhalten verändern.")
        if self.new_permissions:
            lines.append("Neue Berechtigungen: " + ", ".join(self.new_permissions))
        if self.removed_permissions:
            lines.append("Nicht mehr benötigt: " + ", ".join(self.removed_permissions))
        if self.validation.security_findings:
            lines.append("Sicherheitshinweise:")
            lines.extend(f"  ⚠ {finding}" for finding in self.validation.security_findings)
        if not self.validation.valid:
            lines.append("Die Prüfung wurde nicht bestanden – ich rate von diesem Update ab.")
        elif self.needs_explicit_consent:
            lines.append("Soll ich das Update trotzdem einspielen?")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "current_version": self.current_version,
            "new_version": self.new_version,
            "validation": self.validation.to_dict(),
            "new_permissions": self.new_permissions,
            "removed_permissions": self.removed_permissions,
            "is_major": self.is_major,
            "needs_explicit_consent": self.needs_explicit_consent,
            "description": self.describe(),
        }


class SkillUpdater:
    """Verwaltet Aktualisierungen und Rollbacks von Skills."""

    def __init__(
        self,
        registry: SkillRegistry,
        validator: SkillValidator,
        installer: SkillInstaller,
    ) -> None:
        self._registry = registry
        self._validator = validator
        self._installer = installer
        self._history = JsonStore("skill_history.json", default={"entries": {}})
        self._backup_dir = get_data_dir() / "skill_backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def check(self, name: str, source: str | Path) -> UpdateProposal | None:
        """Prüft eine verfügbare Aktualisierung.

        Args:
            name: Name des installierten Skills.
            source: Verzeichnis mit der neuen Version.

        Returns:
            Der Aktualisierungsvorschlag, oder ``None``, wenn der Skill
            nicht installiert ist oder keine neuere Version vorliegt.
        """

        record = self._registry.get(name)
        if record is None:
            return None

        source_path = Path(source).expanduser().resolve()
        manifest = self._installer._read_manifest(source_path)  # noqa: SLF001 - bewusst geteilt
        if manifest is None or manifest.name != name:
            return None

        if _parse_version(manifest.version) <= _parse_version(record.manifest.version):
            return None

        validation = self._validator.validate(manifest, source_path)

        current_permissions = set(record.manifest.permissions)
        new_permissions = set(manifest.permissions)

        return UpdateProposal(
            skill=name,
            current_version=record.manifest.version,
            new_version=manifest.version,
            validation=validation,
            new_permissions=sorted(new_permissions - current_permissions),
            removed_permissions=sorted(current_permissions - new_permissions),
            is_major=_parse_version(manifest.version)[0] > _parse_version(record.manifest.version)[0],
            source_path=str(source_path),
        )

    def apply(self, proposal: UpdateProposal, *, confirmed: bool = False) -> dict[str, Any]:
        """Führt eine Aktualisierung durch.

        Vor dem Überschreiben wird die bisherige Version gesichert, damit
        jederzeit zurückgerollt werden kann.
        """

        if not proposal.validation.valid:
            return {
                "updated": False,
                "message": "Das Update hat die Prüfung nicht bestanden und wurde nicht eingespielt.",
                "details": proposal.validation.to_dict(),
            }

        if proposal.needs_explicit_consent and not confirmed:
            return {
                "updated": False,
                "requires_confirmation": True,
                "message": proposal.describe(),
            }

        record = self._registry.get(proposal.skill)
        if record is None:
            return {"updated": False, "message": "Der Skill ist nicht installiert."}

        target = Path(record.path)
        backup = self._backup_dir / f"{proposal.skill}-{record.manifest.version}"

        try:
            if target.exists():
                if backup.exists():
                    shutil.rmtree(backup)
                shutil.copytree(target, backup)
                shutil.rmtree(target)
            shutil.copytree(proposal.source_path, target)
        except (OSError, shutil.Error) as error:
            logger.exception("Update von '%s' fehlgeschlagen.", proposal.skill)
            return {"updated": False, "message": f"Update fehlgeschlagen: {error}"}

        new_manifest = self._installer._read_manifest(target)  # noqa: SLF001
        if new_manifest is not None:
            record.manifest = new_manifest
        record.updated_at = time.time()
        record.granted_permissions = [
            permission
            for permission in record.granted_permissions
            if permission in record.manifest.permissions
        ]
        self._registry.add(record)

        self._record_history(
            proposal.skill,
            {
                "from": proposal.current_version,
                "to": proposal.new_version,
                "at": time.time(),
                "backup": str(backup),
                "new_permissions": proposal.new_permissions,
            },
        )

        logger.info(
            "Skill '%s' aktualisiert: %s → %s",
            proposal.skill,
            proposal.current_version,
            proposal.new_version,
        )
        return {
            "updated": True,
            "skill": proposal.skill,
            "version": proposal.new_version,
            "message": (
                f"„{proposal.skill}“ wurde auf {proposal.new_version} aktualisiert. "
                + (
                    "Neue Berechtigungen musst du noch bestätigen: "
                    + ", ".join(proposal.new_permissions)
                    if proposal.new_permissions
                    else "Die bisherigen Berechtigungen bleiben unverändert."
                )
            ),
        }

    def rollback(self, name: str) -> dict[str, Any]:
        """Stellt die zuletzt gesicherte Version eines Skills wieder her."""

        entries = list((self._history.get("entries", {}) or {}).get(name, []))
        if not entries:
            return {"rolled_back": False, "message": "Es liegt keine frühere Version vor."}

        last = entries[-1]
        backup = Path(str(last.get("backup", "")))
        record = self._registry.get(name)
        if record is None or not backup.exists():
            return {"rolled_back": False, "message": "Die Sicherung ist nicht mehr vorhanden."}

        target = Path(record.path)
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(backup, target)
        except (OSError, shutil.Error) as error:
            return {"rolled_back": False, "message": f"Rollback fehlgeschlagen: {error}"}

        manifest = self._installer._read_manifest(target)  # noqa: SLF001
        if manifest is not None:
            record.manifest = manifest
            record.updated_at = time.time()
            self._registry.add(record)

        logger.info("Skill '%s' auf Version %s zurückgesetzt.", name, last.get("from"))
        return {
            "rolled_back": True,
            "message": f"„{name}“ wurde auf Version {last.get('from')} zurückgesetzt.",
        }

    def history(self, name: str) -> list[dict[str, Any]]:
        """Die Änderungshistorie eines Skills."""

        return list((self._history.get("entries", {}) or {}).get(name, []))

    def _record_history(self, name: str, entry: dict[str, Any]) -> None:
        entries = dict(self._history.get("entries", {}) or {})
        skill_entries = list(entries.get(name, []))
        skill_entries.append(entry)
        entries[name] = skill_entries
        self._history.set("entries", entries)
