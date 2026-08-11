"""Skill Installer – der Installationsablauf.

Ablauf gemäß Vorgabe:

Skill gefunden → Beschreibung anzeigen → Berechtigungen anzeigen →
Benutzer bestätigt → Installation → Tests → Aktivierung

Ohne Bestätigung des Benutzers wird nichts installiert und nichts
aktiviert. Abhängigkeiten werden niemals automatisch installiert.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.skills.skill_permissions import SkillPermissions
from backend.skills.skill_registry import SkillManifest, SkillRecord, SkillRegistry
from backend.skills.skill_validator import SkillValidator, ValidationReport
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_skills_dir

logger = get_logger(__name__)


@dataclass
class InstallProposal:
    """Der dem Benutzer vorgelegte Installationsvorschlag."""

    manifest: SkillManifest
    validation: ValidationReport
    permission_description: str = ""
    source_path: str = ""
    accepted: bool = False
    blockers: list[str] = field(default_factory=list)

    @property
    def can_install(self) -> bool:
        """Ob die Installation grundsätzlich möglich ist."""

        return self.validation.valid and not self.blockers

    def describe(self) -> str:
        """Formuliert den Vorschlag für den Benutzer."""

        lines = [
            f"Skill: {self.manifest.name} {self.manifest.version}",
            f"Autor: {self.manifest.author}",
            self.manifest.description or "(keine Beschreibung hinterlegt)",
            "",
            self.permission_description,
        ]
        summary = self.validation.summary()
        if summary:
            lines.extend(["", summary])
        if self.can_install:
            lines.append("")
            lines.append("Soll ich diesen Skill installieren?")
        else:
            lines.append("")
            lines.append("Der Skill kann in dieser Form nicht installiert werden.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "validation": self.validation.to_dict(),
            "permissions": self.permission_description,
            "can_install": self.can_install,
            "blockers": self.blockers,
            "description": self.describe(),
        }


class SkillInstaller:
    """Führt Installation und Deinstallation von Skills durch."""

    def __init__(
        self,
        registry: SkillRegistry,
        validator: SkillValidator,
        permissions: SkillPermissions,
    ) -> None:
        config = get_config()
        skills_config = config.section("skills")

        self._registry = registry
        self._validator = validator
        self._permissions = permissions
        self._require_confirmation = bool(skills_config.get("require_confirmation", True))
        self._skills_dir = get_skills_dir()
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    @property
    def skills_directory(self) -> Path:
        """Verzeichnis, in dem installierte Skills liegen."""

        return self._skills_dir

    # --- Schritt 1–3: prüfen und vorlegen ------------------------------------

    def prepare(self, source: str | Path) -> InstallProposal:
        """Prüft einen Skill und erstellt den Installationsvorschlag.

        Es wird noch nichts installiert – der Vorschlag wird dem Benutzer
        zur Bestätigung vorgelegt.

        Args:
            source: Verzeichnis des zu installierenden Skills.

        Returns:
            Der Installationsvorschlag mit Beschreibung und Berechtigungen.
        """

        source_path = Path(source).expanduser().resolve()
        manifest = self._read_manifest(source_path)

        if manifest is None:
            empty = SkillManifest(name="unbekannt")
            report = ValidationReport(valid=False, errors=["Es wurde keine skill.json gefunden."])
            return InstallProposal(manifest=empty, validation=report, source_path=str(source_path))

        report = self._validator.validate(manifest, source_path)
        request = self._permissions.build_request(manifest.name, manifest.permissions)

        blockers: list[str] = []
        existing = self._registry.get(manifest.name)
        if existing is not None:
            blockers.append(
                f"Ein Skill mit dem Namen '{manifest.name}' ist bereits installiert "
                f"(Version {existing.manifest.version}). Nutze stattdessen die Aktualisierung."
            )

        return InstallProposal(
            manifest=manifest,
            validation=report,
            permission_description=request.describe(),
            source_path=str(source_path),
            blockers=blockers,
        )

    # --- Schritt 4–7: installieren, testen, aktivieren -------------------------

    def install(self, proposal: InstallProposal, *, confirmed: bool = False) -> dict[str, Any]:
        """Installiert einen Skill nach Bestätigung durch den Benutzer.

        Args:
            proposal: Der zuvor erstellte Vorschlag.
            confirmed: Muss ``True`` sein, wenn die Bestätigungspflicht
                aktiviert ist.

        Returns:
            Ein Bericht über die Installation.
        """

        if self._require_confirmation and not confirmed:
            return {
                "installed": False,
                "requires_confirmation": True,
                "message": proposal.describe(),
            }

        if not proposal.can_install:
            return {
                "installed": False,
                "message": "Der Skill hat die Prüfung nicht bestanden.",
                "details": proposal.validation.to_dict(),
                "blockers": proposal.blockers,
            }

        target = self._skills_dir / proposal.manifest.name
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(proposal.source_path, target)
        except (OSError, shutil.Error) as error:
            logger.exception("Installation von '%s' fehlgeschlagen.", proposal.manifest.name)
            return {"installed": False, "message": f"Kopieren fehlgeschlagen: {error}"}

        record = SkillRecord(
            manifest=proposal.manifest,
            status="installiert",
            granted_permissions=list(proposal.manifest.permissions),
            compatible=proposal.validation.compatible,
            path=str(target),
        )
        self._registry.add(record)

        logger.info("Skill installiert: %s %s", record.manifest.name, record.manifest.version)
        return {
            "installed": True,
            "skill": record.manifest.name,
            "version": record.manifest.version,
            "path": str(target),
            "warnings": proposal.validation.warnings,
            "missing_dependencies": proposal.validation.missing_dependencies,
            "message": (
                f"Skill „{record.manifest.name}“ wurde installiert. "
                + (
                    "Er kann erst genutzt werden, wenn du diese Pakete installierst: "
                    + ", ".join(proposal.validation.missing_dependencies)
                    if proposal.validation.missing_dependencies
                    else "Er ist jetzt bereit zur Aktivierung."
                )
            ),
        }

    def uninstall(self, name: str, *, confirmed: bool = False) -> dict[str, Any]:
        """Entfernt einen Skill vollständig."""

        record = self._registry.get(name)
        if record is None:
            return {"removed": False, "message": f"Kein Skill mit dem Namen '{name}'."}

        if self._require_confirmation and not confirmed:
            return {
                "removed": False,
                "requires_confirmation": True,
                "message": f"Soll ich den Skill „{name}“ wirklich entfernen?",
            }

        path = Path(record.path)
        if path.exists() and path.is_relative_to(self._skills_dir):
            shutil.rmtree(path, ignore_errors=True)

        self._registry.remove(name)
        logger.info("Skill entfernt: %s", name)
        return {"removed": True, "message": f"Skill „{name}“ wurde entfernt."}

    # --- Hilfsfunktionen ------------------------------------------------------

    @staticmethod
    def _read_manifest(path: Path) -> SkillManifest | None:
        """Liest die ``skill.json`` eines Skills."""

        manifest_file = path / "skill.json"
        if not manifest_file.exists():
            return None
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.error("skill.json konnte nicht gelesen werden: %s", error)
            return None
        if not isinstance(data, dict):
            return None
        return SkillManifest.from_dict(data)

    def discover(self) -> list[SkillManifest]:
        """Findet alle im Skill-Verzeichnis liegenden Skills."""

        found: list[SkillManifest] = []
        for candidate in self._skills_dir.iterdir():
            if not candidate.is_dir():
                continue
            manifest = self._read_manifest(candidate)
            if manifest is not None:
                found.append(manifest)
        return found
