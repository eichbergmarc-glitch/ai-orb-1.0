"""Berechtigungssystem für Skills.

Jeder Skill besitzt eigene Rechte: Dateizugriff, Internet, Browsersteuerung,
Mikrofon, Kamera, Systembefehle, Datenbanken. Der Benutzer kann jede
Berechtigung jederzeit ändern.

Bestimmte Berechtigungen gelten als eingeschränkt und werden niemals ohne
ausdrückliche Rückfrage gewährt (konfigurierbar über
``skills.restricted_permissions`` in ``config.yaml``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Alle vergebbaren Skill-Berechtigungen mit verständlicher Beschreibung.
PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "file_read": "Dateien lesen",
    "file_write": "Dateien schreiben und ändern",
    "internet": "auf das Internet zugreifen",
    "browser_control": "den Browser steuern",
    "microphone": "das Mikrofon verwenden",
    "camera": "die Kamera verwenden",
    "system_commands": "Systembefehle ausführen",
    "database": "auf Datenbanken zugreifen",
    "screen_capture": "den Bildschirminhalt aufnehmen",
}


@dataclass
class PermissionRequest:
    """Eine Berechtigungsanfrage eines Skills."""

    skill: str
    permissions: list[str]
    restricted: list[str]

    @property
    def needs_confirmation(self) -> bool:
        """Ob eine Rückfrage beim Benutzer erforderlich ist."""

        return bool(self.permissions)

    def describe(self) -> str:
        """Formuliert die Anfrage verständlich für den Benutzer."""

        lines = [f"Der Skill „{self.skill}“ möchte folgende Rechte:"]
        for permission in self.permissions:
            description = PERMISSION_DESCRIPTIONS.get(permission, permission)
            marker = "  ⚠ " if permission in self.restricted else "  • "
            lines.append(f"{marker}{description}")
        if self.restricted:
            lines.append(
                "Die mit ⚠ markierten Rechte sind besonders weitreichend. "
                "Erteile sie nur, wenn du dem Skill vertraust."
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "permissions": self.permissions,
            "restricted": self.restricted,
            "description": self.describe(),
        }


class SkillPermissions:
    """Prüft und verwaltet Skill-Berechtigungen."""

    def __init__(self) -> None:
        config = get_config()
        skills_config = config.section("skills")
        self._restricted = set(skills_config.get("restricted_permissions", []) or [])

    def validate(self, permissions: list[str]) -> tuple[list[str], list[str]]:
        """Trennt bekannte von unbekannten Berechtigungen.

        Returns:
            Ein Tupel aus gültigen und unbekannten Berechtigungen.
        """

        valid = [item for item in permissions if item in PERMISSION_DESCRIPTIONS]
        unknown = [item for item in permissions if item not in PERMISSION_DESCRIPTIONS]
        return valid, unknown

    def build_request(self, skill: str, permissions: list[str]) -> PermissionRequest:
        """Erzeugt eine Berechtigungsanfrage für die Benutzerbestätigung."""

        valid, unknown = self.validate(permissions)
        if unknown:
            logger.warning(
                "Skill '%s' fordert unbekannte Berechtigungen an: %s", skill, unknown
            )
        restricted = [item for item in valid if item in self._restricted]
        return PermissionRequest(skill=skill, permissions=valid, restricted=restricted)

    def is_restricted(self, permission: str) -> bool:
        """Ob eine Berechtigung als eingeschränkt gilt."""

        return permission in self._restricted

    def check(self, granted: list[str], required: str) -> bool:
        """Prüft, ob eine benötigte Berechtigung vorliegt."""

        return required in granted

    def describe_all(self) -> dict[str, Any]:
        """Übersicht über alle Berechtigungen (Transparenzansicht)."""

        return {
            "verfügbar": PERMISSION_DESCRIPTIONS,
            "eingeschränkt": sorted(self._restricted),
        }
