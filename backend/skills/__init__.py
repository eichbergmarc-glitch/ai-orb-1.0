"""Skill- und Plugin-System von AI-Orb (v3 Phase 6).

Neue Fähigkeiten werden nicht in den Kern programmiert, sondern als Skills
installiert. Ein Skill ist ein eigenständiges Modul mit klar definierten
Schnittstellen, eigener Version, eigenen Berechtigungen, eigenen Tests und
eigener Dokumentation.

Der Kern bleibt dabei stabil: Skills werden dynamisch geladen und können
jederzeit aktiviert, deaktiviert, aktualisiert oder zurückgerollt werden.
"""

from backend.skills.skill_documentation import SkillDocumentation
from backend.skills.skill_installer import InstallProposal, SkillInstaller
from backend.skills.skill_loader import LoadedSkill, SkillApi, SkillLoader
from backend.skills.skill_manager import SkillManager
from backend.skills.skill_marketplace import CatalogEntry, SkillMarketplace
from backend.skills.skill_permissions import (
    PERMISSION_DESCRIPTIONS,
    PermissionRequest,
    SkillPermissions,
)
from backend.skills.skill_registry import SkillManifest, SkillRecord, SkillRegistry
from backend.skills.skill_updater import SkillUpdater, UpdateProposal
from backend.skills.skill_validator import SkillValidator, ValidationReport

__all__ = [
    "CatalogEntry",
    "InstallProposal",
    "LoadedSkill",
    "PERMISSION_DESCRIPTIONS",
    "PermissionRequest",
    "SkillApi",
    "SkillDocumentation",
    "SkillInstaller",
    "SkillLoader",
    "SkillManager",
    "SkillManifest",
    "SkillMarketplace",
    "SkillPermissions",
    "SkillRecord",
    "SkillRegistry",
    "SkillUpdater",
    "SkillValidator",
    "UpdateProposal",
    "ValidationReport",
]
