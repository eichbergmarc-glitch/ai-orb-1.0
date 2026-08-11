"""Code Analyzer – kontinuierliche Analyse der eigenen Codebasis.

Analysiert werden Modulgrößen, Komplexität, Abhängigkeiten, Code-Duplikate,
mögliche Fehlerquellen, Dokumentation und Testabdeckung. Daraus entstehen
konkrete Verbesserungsvorschläge.

Die Analyse ist rein lesend: Es wird niemals Code verändert.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)


@dataclass
class Finding:
    """Ein einzelnes Analyseergebnis."""

    category: str
    severity: str
    message: str
    location: str
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass
class ModuleReport:
    """Kennzahlen eines einzelnen Moduls."""

    path: str
    lines: int = 0
    functions: int = 0
    classes: int = 0
    max_complexity: int = 0
    documented_functions: int = 0
    imports: list[str] = field(default_factory=list)

    @property
    def documentation_ratio(self) -> float:
        """Anteil dokumentierter Funktionen (0.0 bis 1.0)."""

        if self.functions == 0:
            return 1.0
        return self.documented_functions / self.functions

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "lines": self.lines,
            "functions": self.functions,
            "classes": self.classes,
            "max_complexity": self.max_complexity,
            "documentation_ratio": round(self.documentation_ratio, 2),
            "imports": self.imports,
        }


class CodeAnalyzer:
    """Analysiert die Python-Codebasis von AI-Orb."""

    def __init__(self, root: Path | None = None) -> None:
        config = get_config()
        evolution_config = config.section("evolution")

        self._root = root or get_project_root()
        self._max_function_lines = int(evolution_config.get("max_function_lines", 60))
        self._max_module_lines = int(evolution_config.get("max_module_lines", 500))
        self._max_complexity = int(evolution_config.get("max_complexity", 12))

    def analyze(self) -> dict[str, Any]:
        """Analysiert die gesamte Codebasis.

        Returns:
            Ein Bericht mit Modulkennzahlen und Verbesserungsvorschlägen.
        """

        modules: list[ModuleReport] = []
        findings: list[Finding] = []
        signatures: dict[str, list[str]] = {}

        for path in sorted((self._root / "backend").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            report, module_findings, module_signatures = self._analyze_file(path)
            if report is None:
                continue
            modules.append(report)
            findings.extend(module_findings)
            for signature, location in module_signatures.items():
                signatures.setdefault(signature, []).append(location)

        findings.extend(self._find_duplicates(signatures))
        findings.extend(self._check_test_coverage(modules))

        severity_rank = {"hoch": 0, "mittel": 1, "gering": 2}
        findings.sort(key=lambda finding: severity_rank.get(finding.severity, 3))

        logger.info(
            "Codeanalyse: %d Module, %d Hinweise.", len(modules), len(findings)
        )
        return {
            "modules": [module.to_dict() for module in modules],
            "findings": [finding.to_dict() for finding in findings],
            "total_lines": sum(module.lines for module in modules),
            "total_functions": sum(module.functions for module in modules),
            "average_documentation": (
                round(sum(module.documentation_ratio for module in modules) / len(modules), 2)
                if modules
                else 0.0
            ),
        }

    # --- Einzelanalyse ---------------------------------------------------------

    def _analyze_file(
        self, path: Path
    ) -> tuple[ModuleReport | None, list[Finding], dict[str, str]]:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError) as error:
            return (
                None,
                [
                    Finding(
                        category="syntax",
                        severity="hoch",
                        message=f"Datei konnte nicht analysiert werden: {error}",
                        location=str(path.relative_to(self._root)),
                    )
                ],
                {},
            )

        relative = str(path.relative_to(self._root))
        report = ModuleReport(path=relative, lines=len(source.splitlines()))
        findings: list[Finding] = []
        signatures: dict[str, str] = {}

        if report.lines > self._max_module_lines:
            findings.append(
                Finding(
                    category="modulgröße",
                    severity="mittel",
                    message=f"Das Modul ist mit {report.lines} Zeilen sehr groß.",
                    location=relative,
                    suggestion="Aufteilen in mehrere thematisch getrennte Module.",
                )
            )

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                report.imports.extend(self._import_names(node))
            elif isinstance(node, ast.ClassDef):
                report.classes += 1
                if not ast.get_docstring(node):
                    findings.append(
                        Finding(
                            category="dokumentation",
                            severity="gering",
                            message=f"Klasse '{node.name}' ist nicht dokumentiert.",
                            location=f"{relative}:{node.lineno}",
                            suggestion="Docstring mit Zweck und Verantwortlichkeit ergänzen.",
                        )
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                report.functions += 1
                if ast.get_docstring(node):
                    report.documented_functions += 1
                else:
                    findings.append(
                        Finding(
                            category="dokumentation",
                            severity="gering",
                            message=f"Funktion '{node.name}' ist nicht dokumentiert.",
                            location=f"{relative}:{node.lineno}",
                            suggestion="Docstring mit Argumenten und Rückgabewert ergänzen.",
                        )
                    )

                length = self._function_length(node)
                if length > self._max_function_lines:
                    findings.append(
                        Finding(
                            category="funktionslänge",
                            severity="mittel",
                            message=f"Funktion '{node.name}' ist mit {length} Zeilen sehr lang.",
                            location=f"{relative}:{node.lineno}",
                            suggestion="In kleinere, benannte Teilschritte zerlegen.",
                        )
                    )

                complexity = self._complexity(node)
                report.max_complexity = max(report.max_complexity, complexity)
                if complexity > self._max_complexity:
                    findings.append(
                        Finding(
                            category="komplexität",
                            severity="mittel",
                            message=(
                                f"Funktion '{node.name}' hat eine hohe Verzweigungstiefe "
                                f"({complexity})."
                            ),
                            location=f"{relative}:{node.lineno}",
                            suggestion="Bedingungen zusammenfassen oder früh zurückkehren.",
                        )
                    )

                signature = self._signature(node)
                if signature:
                    signatures[signature] = f"{relative}:{node.lineno} ({node.name})"

            elif isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.append(
                    Finding(
                        category="fehlerquelle",
                        severity="mittel",
                        message="Es wird jede Ausnahme unterschiedslos abgefangen.",
                        location=f"{relative}:{node.lineno}",
                        suggestion="Konkrete Ausnahmetypen angeben und protokollieren.",
                    )
                )

        return report, findings, signatures

    # --- Hilfsfunktionen ---------------------------------------------------------

    @staticmethod
    def _import_names(node: ast.AST) -> list[str]:
        if isinstance(node, ast.Import):
            return [alias.name.split(".")[0] for alias in node.names]
        if isinstance(node, ast.ImportFrom) and node.module:
            return [node.module.split(".")[0]]
        return []

    @staticmethod
    def _function_length(node: ast.AST) -> int:
        end = getattr(node, "end_lineno", None)
        start = getattr(node, "lineno", 0)
        if end is None:
            return 0
        return int(end) - int(start) + 1

    @staticmethod
    def _complexity(node: ast.AST) -> int:
        """Berechnet eine vereinfachte zyklomatische Komplexität."""

        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, ast.IfExp):
                complexity += 1
        return complexity

    @staticmethod
    def _signature(node: ast.AST) -> str:
        """Erzeugt eine grobe Strukturkennung zur Duplikaterkennung."""

        body = getattr(node, "body", [])
        if len(body) < 4:
            return ""
        kinds = [type(statement).__name__ for statement in body]
        return "|".join(kinds)

    @staticmethod
    def _find_duplicates(signatures: dict[str, list[str]]) -> list[Finding]:
        """Meldet Funktionen mit identischer Struktur."""

        findings: list[Finding] = []
        for signature, locations in signatures.items():
            if len(locations) < 3:
                continue
            findings.append(
                Finding(
                    category="duplikat",
                    severity="gering",
                    message=(
                        f"{len(locations)} Funktionen haben denselben strukturellen "
                        "Aufbau und könnten zusammengefasst werden."
                    ),
                    location=", ".join(locations[:4]),
                    suggestion="Gemeinsame Logik in eine Hilfsfunktion auslagern.",
                )
            )
        return findings

    def _check_test_coverage(self, modules: list[ModuleReport]) -> list[Finding]:
        """Prüft grob, welche Pakete überhaupt Tests besitzen."""

        tests_dir = self._root / "tests"
        if not tests_dir.exists():
            return [
                Finding(
                    category="tests",
                    severity="hoch",
                    message="Es existiert kein Testverzeichnis.",
                    location="tests/",
                    suggestion="Unit- und Integrationstests anlegen.",
                )
            ]

        tested = {
            path.stem.replace("test_", "")
            for path in tests_dir.rglob("test_*.py")
        }

        packages = {Path(module.path).parent.name for module in modules}
        untested = sorted(
            package
            for package in packages
            if package not in ("backend", "__pycache__")
            and not any(name.startswith(package[:6]) for name in tested)
        )

        if not untested:
            return []

        return [
            Finding(
                category="tests",
                severity="mittel",
                message="Für diese Bereiche liegen noch keine Tests vor: "
                + ", ".join(untested[:8]),
                location="tests/",
                suggestion="Für jeden Bereich mindestens einen Test ergänzen.",
            )
        ]
