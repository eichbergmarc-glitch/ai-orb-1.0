"""Review Engine – automatische Prüfung jedes Patches.

Geprüft werden Lesbarkeit, Architektur, Sicherheit, Dokumentation, Tests
und Abwärtskompatibilität. Unsicherheiten werden ausdrücklich gekennzeichnet:
Wo die automatische Prüfung an ihre Grenzen stößt, wird das benannt, statt
eine Sicherheit vorzutäuschen.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.evolution.patch_generator import Patch
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ReviewComment:
    """Eine einzelne Anmerkung des Reviews."""

    aspect: str
    severity: str
    message: str
    location: str = ""
    uncertain: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
            "uncertain": self.uncertain,
        }


@dataclass
class ReviewReport:
    """Das Ergebnis eines Reviews."""

    comments: list[ReviewComment] = field(default_factory=list)
    aspects: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Ob der Patch das Review bestanden hat."""

        return not any(comment.severity == "hoch" for comment in self.comments)

    @property
    def uncertainties(self) -> list[ReviewComment]:
        """Alle Punkte, bei denen die automatische Prüfung unsicher ist."""

        return [comment for comment in self.comments if comment.uncertain]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "aspects": self.aspects,
            "comments": [comment.to_dict() for comment in self.comments],
            "uncertainties": [comment.to_dict() for comment in self.uncertainties],
        }

    def summary(self) -> str:
        """Fasst das Review verständlich zusammen."""

        if not self.comments:
            return "Das Review hat keine Beanstandungen ergeben."

        lines: list[str] = []
        for severity, label in (("hoch", "Blockierend"), ("mittel", "Zu prüfen"), ("gering", "Hinweis")):
            relevant = [comment for comment in self.comments if comment.severity == severity]
            if not relevant:
                continue
            lines.append(f"{label}:")
            lines.extend(
                f"  • {comment.message}" + (f" ({comment.location})" if comment.location else "")
                for comment in relevant
            )
        if self.uncertainties:
            lines.append(
                "Bei folgenden Punkten kann ich die Auswirkung nicht sicher beurteilen – "
                "bitte selbst prüfen:"
            )
            lines.extend(f"  ? {comment.message}" for comment in self.uncertainties)
        return "\n".join(lines)


class ReviewEngine:
    """Prüft Patches automatisch vor der Freigabe."""

    #: Muster, die auf eine mögliche Verletzung der Abwärtskompatibilität
    #: hindeuten.
    _BREAKING_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"^-\s*def\s+(\w+)", "Eine öffentliche Funktion wurde entfernt oder umbenannt"),
        (r"^-\s*class\s+(\w+)", "Eine Klasse wurde entfernt oder umbenannt"),
        (r"^-\s*(\w+)\s*=\s*", "Eine Konstante wurde entfernt"),
    )

    def review(self, patch: Patch) -> ReviewReport:
        """Prüft einen Patch vollständig.

        Args:
            patch: Der zu prüfende Patch.

        Returns:
            Der Reviewbericht.
        """

        report = ReviewReport()
        workspace = Path(patch.workspace)

        self._check_readability(patch, workspace, report)
        self._check_architecture(patch, workspace, report)
        self._check_security(patch, report)
        self._check_documentation(patch, workspace, report)
        self._check_tests(patch, workspace, report)
        self._check_compatibility(patch, report)

        logger.info(
            "Review für Patch %s: %s (%d Anmerkungen).",
            patch.id,
            "bestanden" if report.passed else "nicht bestanden",
            len(report.comments),
        )
        return report

    # --- Einzelaspekte ---------------------------------------------------------

    def _check_readability(self, patch: Patch, workspace: Path, report: ReviewReport) -> None:
        problems = 0
        for relative in patch.files_changed:
            if not relative.endswith(".py"):
                continue
            path = workspace / relative
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            long_lines = [index for index, line in enumerate(lines, 1) if len(line) > 120]
            if long_lines:
                problems += 1
                report.comments.append(
                    ReviewComment(
                        aspect="lesbarkeit",
                        severity="gering",
                        message=f"{len(long_lines)} sehr lange Zeile(n) erschweren das Lesen.",
                        location=f"{relative}:{long_lines[0]}",
                    )
                )
        report.aspects["lesbarkeit"] = problems == 0

    def _check_architecture(self, patch: Patch, workspace: Path, report: ReviewReport) -> None:
        """Prüft, ob die Kommunikationsregeln eingehalten wurden.

        Fachmodule dürfen nicht direkt miteinander sprechen – die
        Kommunikation läuft über das Cognitive Core.
        """

        violations = 0
        forbidden_pairs = {
            "backend/agents": ("backend.projects", "backend.skills"),
            "backend/projects": ("backend.agents", "backend.evolution"),
            "backend/skills": ("backend.agents", "backend.projects"),
        }

        for relative in patch.files_changed:
            if not relative.endswith(".py"):
                continue
            package = "/".join(relative.split("/")[:2])
            forbidden = forbidden_pairs.get(package)
            if not forbidden:
                continue
            try:
                source = (workspace / relative).read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module
                elif isinstance(node, ast.Import):
                    module = node.names[0].name if node.names else ""
                if module.startswith(forbidden):
                    violations += 1
                    report.comments.append(
                        ReviewComment(
                            aspect="architektur",
                            severity="hoch",
                            message=(
                                f"'{package}' greift direkt auf '{module}' zu. "
                                "Die Kommunikation muss über das Cognitive Core laufen."
                            ),
                            location=f"{relative}:{getattr(node, 'lineno', 0)}",
                        )
                    )
        report.aspects["architektur"] = violations == 0

    def _check_security(self, patch: Patch, report: ReviewReport) -> None:
        risky = (
            ("eval(", "Ausführung beliebigen Codes"),
            ("exec(", "Ausführung beliebigen Codes"),
            ("shell=True", "Shell-Aufruf mit Injektionsrisiko"),
            ("verify=False", "Deaktivierte Zertifikatsprüfung"),
        )
        added_lines = [
            line[1:] for line in patch.diff.splitlines() if line.startswith("+") and not line.startswith("+++")
        ]
        findings = 0
        for line in added_lines:
            for pattern, reason in risky:
                if pattern in line:
                    findings += 1
                    report.comments.append(
                        ReviewComment(
                            aspect="sicherheit",
                            severity="hoch",
                            message=f"Sicherheitsrisiko: {pattern} – {reason}.",
                            location=line.strip()[:80],
                        )
                    )
        report.aspects["sicherheit"] = findings == 0

    def _check_documentation(self, patch: Patch, workspace: Path, report: ReviewReport) -> None:
        undocumented = 0
        for relative in patch.files_changed:
            if not relative.endswith(".py"):
                continue
            try:
                tree = ast.parse((workspace / relative).read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            if not ast.get_docstring(tree):
                undocumented += 1
                report.comments.append(
                    ReviewComment(
                        aspect="dokumentation",
                        severity="mittel",
                        message="Das Modul besitzt keinen Modul-Docstring.",
                        location=relative,
                    )
                )
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if not node.name.startswith("_") and not ast.get_docstring(node):
                        undocumented += 1
                        report.comments.append(
                            ReviewComment(
                                aspect="dokumentation",
                                severity="gering",
                                message=f"'{node.name}' ist nicht dokumentiert.",
                                location=f"{relative}:{node.lineno}",
                            )
                        )
        report.aspects["dokumentation"] = undocumented == 0

    def _check_tests(self, patch: Patch, workspace: Path, report: ReviewReport) -> None:
        touched_backend = [
            path for path in patch.files_changed if path.startswith("backend/") and path.endswith(".py")
        ]
        touched_tests = [path for path in patch.files_changed if path.startswith("tests/")]

        has_tests = bool(touched_tests) or not touched_backend
        if not has_tests:
            report.comments.append(
                ReviewComment(
                    aspect="tests",
                    severity="mittel",
                    message=(
                        f"{len(touched_backend)} Backend-Datei(en) geändert, aber kein Test "
                        "ergänzt oder angepasst."
                    ),
                    location=touched_backend[0],
                )
            )
        report.aspects["tests"] = has_tests

    def _check_compatibility(self, patch: Patch, report: ReviewReport) -> None:
        """Prüft, ob die Änderung bestehende Schnittstellen entfernt."""

        breaking = 0
        for line in patch.diff.splitlines():
            if not line.startswith("-") or line.startswith("---"):
                continue
            for pattern, message in self._BREAKING_PATTERNS:
                match = re.match(pattern, line)
                if match is None:
                    continue
                name = match.group(1)
                if name.startswith("_"):
                    continue  # Interne Namen sind nicht Teil der Schnittstelle.
                breaking += 1
                report.comments.append(
                    ReviewComment(
                        aspect="abwärtskompatibilität",
                        severity="hoch",
                        message=f"{message}: '{name}'.",
                        location=line.strip()[:80],
                        uncertain=True,
                    )
                )
        report.aspects["abwärtskompatibilität"] = breaking == 0

        if patch.diff and breaking == 0:
            report.comments.append(
                ReviewComment(
                    aspect="abwärtskompatibilität",
                    severity="gering",
                    message=(
                        "Ich habe keine entfernten Schnittstellen gefunden, kann aber "
                        "nicht sicher beurteilen, ob sich das Verhalten geändert hat."
                    ),
                    uncertain=True,
                )
            )
