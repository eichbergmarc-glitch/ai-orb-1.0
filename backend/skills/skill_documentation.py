"""Skill Documentation – erzeugt die Dokumentation eines Skills.

Jeder Skill besitzt eine Dokumentation mit Beschreibung, Fähigkeiten,
Berechtigungen, Abhängigkeiten, Konfiguration und Versionshistorie. Diese
Dokumentation ist für den Benutzer jederzeit einsehbar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.skills.skill_permissions import PERMISSION_DESCRIPTIONS
from backend.skills.skill_registry import SkillRecord, SkillRegistry


class SkillDocumentation:
    """Erzeugt lesbare Dokumentation zu installierten Skills."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def for_skill(self, name: str) -> str:
        """Erzeugt die Dokumentation eines einzelnen Skills als Markdown."""

        record = self._registry.get(name)
        if record is None:
            return f"Es ist kein Skill mit dem Namen „{name}“ installiert."
        return self._render(record)

    def _render(self, record: SkillRecord) -> str:
        manifest = record.manifest
        lines = [
            f"# {manifest.name} {manifest.version}",
            "",
            manifest.description or "_Keine Beschreibung hinterlegt._",
            "",
            f"**Autor:** {manifest.author}  ",
            f"**Status:** {record.status}  ",
            f"**Benötigt AI-Orb ab:** {manifest.min_orb_version}",
            "",
            "## Fähigkeiten",
            "",
        ]

        if manifest.capabilities:
            lines.extend(f"- {capability}" for capability in manifest.capabilities)
        else:
            lines.append("_Keine Fähigkeiten deklariert._")

        lines.extend(["", "## Berechtigungen", ""])
        if manifest.permissions:
            for permission in manifest.permissions:
                description = PERMISSION_DESCRIPTIONS.get(permission, permission)
                granted = "erteilt" if permission in record.granted_permissions else "nicht erteilt"
                lines.append(f"- {description} (`{permission}`) – {granted}")
        else:
            lines.append("_Der Skill benötigt keine besonderen Rechte._")

        lines.extend(["", "## Abhängigkeiten", ""])
        if manifest.dependencies:
            lines.extend(f"- `{dependency}`" for dependency in manifest.dependencies)
        else:
            lines.append("_Keine zusätzlichen Pakete erforderlich._")

        if manifest.configuration:
            lines.extend(["", "## Konfiguration", ""])
            for key, value in manifest.configuration.items():
                lines.append(f"- `{key}`: {value}")

        if record.last_error:
            lines.extend(["", "## Letzter Fehler", "", f"```\n{record.last_error}\n```"])

        if manifest.documentation:
            lines.extend(["", "## Weitere Hinweise", "", manifest.documentation])

        lines.extend(["", f"_Installiert unter: {record.path}_"])
        return "\n".join(lines)

    def overview(self) -> str:
        """Erzeugt eine Übersicht über alle installierten Skills."""

        records = self._registry.list()
        if not records:
            return "Es sind derzeit keine Skills installiert."

        lines = ["# Installierte Skills", ""]
        for record in records:
            capabilities = ", ".join(record.manifest.capabilities) or "–"
            lines.append(
                f"- **{record.manifest.name}** {record.manifest.version} "
                f"({record.status}) – {capabilities}"
            )
        return "\n".join(lines)

    def write_to_file(self, name: str, target_dir: Path) -> Path | None:
        """Schreibt die Dokumentation eines Skills als Markdown-Datei."""

        record = self._registry.get(name)
        if record is None:
            return None
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{name}.md"
        target.write_text(self._render(record), encoding="utf-8")
        return target

    def as_dict(self, name: str) -> dict[str, Any] | None:
        """Gibt die Dokumentationsdaten strukturiert zurück."""

        record = self._registry.get(name)
        if record is None:
            return None
        return {
            "manifest": record.manifest.to_dict(),
            "status": record.status,
            "granted_permissions": record.granted_permissions,
            "markdown": self._render(record),
        }
