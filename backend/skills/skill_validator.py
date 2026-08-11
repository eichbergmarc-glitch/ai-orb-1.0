"""Skill Validator – Prüfung vor jeder Installation.

Vor der Installation wird geprüft:

* Ist der Skill kompatibel?
* Sind Abhängigkeiten vorhanden?
* Sind die Berechtigungen korrekt?
* Bestehen Sicherheitsrisiken?
* Sind Tests vorhanden?

Abhängigkeiten werden dabei niemals automatisch installiert – fehlende
Pakete werden lediglich gemeldet.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend import __version__ as ORB_VERSION
from backend.skills.skill_permissions import SkillPermissions
from backend.skills.skill_registry import SkillManifest
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Aufrufe, die in Skill-Code als sicherheitskritisch gelten.
_DANGEROUS_CALLS: tuple[str, ...] = (
    "eval",
    "exec",
    "compile",
    "__import__",
)

#: Module, deren Verwendung eine entsprechende Berechtigung voraussetzt.
_MODULE_PERMISSIONS: dict[str, str] = {
    "subprocess": "system_commands",
    "os": "file_read",
    "shutil": "file_write",
    "socket": "internet",
    "urllib": "internet",
    "http": "internet",
    "requests": "internet",
    "sqlite3": "database",
}


@dataclass
class ValidationReport:
    """Das Ergebnis einer Skill-Prüfung."""

    valid: bool = True
    compatible: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    security_findings: list[str] = field(default_factory=list)
    has_tests: bool = False
    has_documentation: bool = False
    undeclared_permissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "compatible": self.compatible,
            "errors": self.errors,
            "warnings": self.warnings,
            "missing_dependencies": self.missing_dependencies,
            "security_findings": self.security_findings,
            "has_tests": self.has_tests,
            "has_documentation": self.has_documentation,
            "undeclared_permissions": self.undeclared_permissions,
        }

    def summary(self) -> str:
        """Fasst das Prüfergebnis verständlich zusammen."""

        if self.valid and not self.warnings:
            return "Der Skill hat alle Prüfungen bestanden."

        lines: list[str] = []
        if self.errors:
            lines.append("Fehler:")
            lines.extend(f"  • {error}" for error in self.errors)
        if self.security_findings:
            lines.append("Sicherheitshinweise:")
            lines.extend(f"  ⚠ {finding}" for finding in self.security_findings)
        if self.missing_dependencies:
            lines.append(
                "Fehlende Abhängigkeiten (bitte selbst installieren): "
                + ", ".join(self.missing_dependencies)
            )
        if self.warnings:
            lines.append("Hinweise:")
            lines.extend(f"  • {warning}" for warning in self.warnings)
        return "\n".join(lines)


class SkillValidator:
    """Prüft Skills vor Installation und Aktivierung."""

    def __init__(self, permissions: SkillPermissions | None = None) -> None:
        self._permissions = permissions or SkillPermissions()

    def validate(self, manifest: SkillManifest, skill_path: Path) -> ValidationReport:
        """Prüft einen Skill vollständig.

        Args:
            manifest: Die Skill-Beschreibung.
            skill_path: Verzeichnis des Skills.

        Returns:
            Der Prüfbericht.
        """

        report = ValidationReport()

        self._check_manifest(manifest, report)
        self._check_compatibility(manifest, report)
        self._check_dependencies(manifest, report)
        self._check_permissions(manifest, report)
        self._check_files(manifest, skill_path, report)

        report.valid = not report.errors
        if report.valid:
            logger.info("Skill '%s' hat die Prüfung bestanden.", manifest.name)
        else:
            logger.warning(
                "Skill '%s' hat die Prüfung nicht bestanden: %s",
                manifest.name,
                "; ".join(report.errors),
            )
        return report

    # --- Einzelprüfungen ------------------------------------------------------

    @staticmethod
    def _check_manifest(manifest: SkillManifest, report: ValidationReport) -> None:
        if not manifest.name.strip():
            report.errors.append("Der Skill hat keinen Namen.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,48}", manifest.name):
            report.errors.append(
                "Der Skill-Name darf nur Kleinbuchstaben, Ziffern, Bindestrich "
                "und Unterstrich enthalten."
            )
        if not re.fullmatch(r"\d+\.\d+\.\d+", manifest.version):
            report.errors.append("Die Version muss dem Muster X.Y.Z entsprechen.")
        if not manifest.description.strip():
            report.warnings.append("Es fehlt eine Beschreibung des Skills.")
        if not manifest.capabilities:
            report.warnings.append("Der Skill deklariert keine Fähigkeiten.")

    @staticmethod
    def _check_compatibility(manifest: SkillManifest, report: ValidationReport) -> None:
        def parse(version: str) -> tuple[int, ...]:
            try:
                return tuple(int(part) for part in version.split("."))
            except ValueError:
                return (0,)

        if parse(manifest.min_orb_version) > parse(ORB_VERSION):
            report.compatible = False
            report.errors.append(
                f"Der Skill benötigt AI-Orb {manifest.min_orb_version}, "
                f"installiert ist {ORB_VERSION}."
            )

    @staticmethod
    def _check_dependencies(manifest: SkillManifest, report: ValidationReport) -> None:
        """Prüft, ob alle benötigten Pakete vorhanden sind.

        Es wird ausdrücklich nichts installiert – fehlende Pakete werden nur
        gemeldet, damit der Benutzer entscheiden kann.
        """

        for dependency in manifest.dependencies:
            module_name = re.split(r"[<>=!\[]", dependency)[0].strip()
            if not module_name:
                continue
            if importlib.util.find_spec(module_name) is None:
                report.missing_dependencies.append(dependency)

        if report.missing_dependencies:
            report.warnings.append(
                "Der Skill kann erst genutzt werden, wenn die fehlenden "
                "Abhängigkeiten installiert sind."
            )

    def _check_permissions(self, manifest: SkillManifest, report: ValidationReport) -> None:
        _, unknown = self._permissions.validate(manifest.permissions)
        if unknown:
            report.errors.append(
                "Unbekannte Berechtigungen angefordert: " + ", ".join(unknown)
            )

    def _check_files(
        self, manifest: SkillManifest, skill_path: Path, report: ValidationReport
    ) -> None:
        """Prüft Dateien, Tests, Dokumentation und Sicherheitsrisiken."""

        if not skill_path.exists():
            report.errors.append(f"Skill-Verzeichnis nicht gefunden: {skill_path}")
            return

        entrypoint = skill_path / manifest.entrypoint
        if not entrypoint.exists():
            report.errors.append(f"Einstiegspunkt fehlt: {manifest.entrypoint}")
            return

        report.has_tests = any(skill_path.glob("test_*.py")) or (skill_path / "tests").exists()
        if not report.has_tests:
            report.warnings.append("Der Skill enthält keine Tests.")

        report.has_documentation = bool(manifest.documentation) or (
            skill_path / "README.md"
        ).exists()
        if not report.has_documentation:
            report.warnings.append("Der Skill enthält keine Dokumentation.")

        self._scan_source(entrypoint, manifest, report)

    @staticmethod
    def _scan_source(
        entrypoint: Path, manifest: SkillManifest, report: ValidationReport
    ) -> None:
        """Untersucht den Quellcode auf Risiken und nicht deklarierte Rechte."""

        try:
            source = entrypoint.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError) as error:
            report.errors.append(f"Quellcode konnte nicht geprüft werden: {error}")
            return

        used_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    used_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                used_modules.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _DANGEROUS_CALLS:
                    report.security_findings.append(
                        f"Der Skill verwendet '{node.func.id}()' – das erlaubt die "
                        "Ausführung beliebigen Codes."
                    )

        declared = set(manifest.permissions)
        for module in sorted(used_modules):
            required = _MODULE_PERMISSIONS.get(module)
            if required and required not in declared:
                report.undeclared_permissions.append(required)
                report.security_findings.append(
                    f"Der Skill nutzt '{module}', hat dafür aber keine Berechtigung "
                    f"'{required}' angemeldet."
                )
