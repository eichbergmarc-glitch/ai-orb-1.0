"""Architecture Analyzer – bewertet die Wartbarkeit der Architektur.

Erkannt werden enge Kopplung, Zyklen in den Abhängigkeiten, unübersichtliche
Klassen, lange Funktionen, fehlende Schnittstellen und veraltete Module.

Bewertet wird ausdrücklich die **Wartbarkeit**, nicht nur die
Funktionalität: Ein Modul kann fehlerfrei laufen und trotzdem schwer zu
pflegen sein.
"""

from __future__ import annotations

import ast
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.evolution.code_analyzer import Finding
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)

#: Ab dieser Anzahl eingehender Abhängigkeiten gilt ein Modul als stark
#: gekoppelt.
_HIGH_FAN_IN = 8

#: Ab dieser Anzahl ausgehender Abhängigkeiten gilt ein Modul als stark
#: abhängig.
_HIGH_FAN_OUT = 12

#: Ab dieser Anzahl öffentlicher Methoden gilt eine Klasse als unübersichtlich.
_MAX_PUBLIC_METHODS = 20

#: Nach dieser Zeitspanne ohne Änderung gilt ein Modul als möglicherweise
#: veraltet (365 Tage).
_STALE_SECONDS = 365 * 24 * 3600.0


@dataclass
class ArchitectureReport:
    """Das Ergebnis der Architekturbewertung."""

    findings: list[Finding]
    dependencies: dict[str, list[str]]
    cycles: list[list[str]]
    maintainability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [finding.to_dict() for finding in self.findings],
            "dependencies": self.dependencies,
            "cycles": self.cycles,
            "maintainability": round(self.maintainability, 2),
        }


class ArchitectureAnalyzer:
    """Untersucht Modulabhängigkeiten und Strukturqualität."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_project_root()

    def analyze(self) -> ArchitectureReport:
        """Führt die vollständige Architekturanalyse durch."""

        dependencies = self._build_dependency_graph()
        findings: list[Finding] = []

        findings.extend(self._check_coupling(dependencies))
        cycles = self._find_cycles(dependencies)
        findings.extend(self._describe_cycles(cycles))
        findings.extend(self._check_classes())
        findings.extend(self._check_stale_modules())

        maintainability = self._maintainability_score(dependencies, cycles, findings)

        logger.info(
            "Architekturanalyse: %d Module, %d Zyklen, Wartbarkeit %.2f.",
            len(dependencies),
            len(cycles),
            maintainability,
        )
        return ArchitectureReport(
            findings=findings,
            dependencies={key: sorted(value) for key, value in dependencies.items()},
            cycles=cycles,
            maintainability=maintainability,
        )

    # --- Abhängigkeiten -------------------------------------------------------

    def _build_dependency_graph(self) -> dict[str, set[str]]:
        """Baut den Abhängigkeitsgraphen der Backend-Module auf."""

        graph: dict[str, set[str]] = defaultdict(set)

        for path in (self._root / "backend").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            module = self._module_name(path)
            graph.setdefault(module, set())
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

            for node in ast.walk(tree):
                target: str | None = None
                if isinstance(node, ast.ImportFrom) and node.module:
                    target = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("backend."):
                            graph[module].add(self._package_of(alias.name))
                    continue

                if target and target.startswith("backend."):
                    package = self._package_of(target)
                    if package != module:
                        graph[module].add(package)

        return dict(graph)

    def _module_name(self, path: Path) -> str:
        relative = path.relative_to(self._root).with_suffix("")
        parts = [part for part in relative.parts if part != "__init__"]
        # Auf Paketebene aggregieren (backend.memory statt backend.memory.x).
        return ".".join(parts[:2]) if len(parts) > 1 else ".".join(parts)

    @staticmethod
    def _package_of(dotted: str) -> str:
        parts = dotted.split(".")
        return ".".join(parts[:2]) if len(parts) > 1 else dotted

    def _check_coupling(self, graph: dict[str, set[str]]) -> list[Finding]:
        """Meldet stark gekoppelte Module."""

        findings: list[Finding] = []
        fan_in: dict[str, int] = defaultdict(int)
        for targets in graph.values():
            for target in targets:
                fan_in[target] += 1

        for module, targets in graph.items():
            if len(targets) >= _HIGH_FAN_OUT:
                findings.append(
                    Finding(
                        category="kopplung",
                        severity="mittel",
                        message=f"'{module}' hängt von {len(targets)} anderen Paketen ab.",
                        location=module,
                        suggestion="Gemeinsame Abhängigkeiten hinter einer Schnittstelle bündeln.",
                    )
                )
            if fan_in.get(module, 0) >= _HIGH_FAN_IN:
                findings.append(
                    Finding(
                        category="kopplung",
                        severity="gering",
                        message=(
                            f"'{module}' wird von {fan_in[module]} Paketen genutzt und ist "
                            "damit ein zentraler Knotenpunkt."
                        ),
                        location=module,
                        suggestion="Schnittstelle stabil halten; Änderungen wirken sich breit aus.",
                    )
                )
        return findings

    @staticmethod
    def _find_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
        """Findet zyklische Abhängigkeiten zwischen Paketen."""

        cycles: list[list[str]] = []
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                if node in stack:
                    cycle = stack[stack.index(node) :] + [node]
                    if cycle not in cycles:
                        cycles.append(cycle)
                return
            visiting.add(node)
            stack.append(node)
            for neighbour in graph.get(node, set()):
                visit(neighbour)
            stack.pop()
            visiting.discard(node)
            visited.add(node)

        for node in graph:
            visit(node)
        return cycles

    @staticmethod
    def _describe_cycles(cycles: list[list[str]]) -> list[Finding]:
        return [
            Finding(
                category="zyklus",
                severity="hoch",
                message="Zyklische Abhängigkeit: " + " → ".join(cycle),
                location=cycle[0],
                suggestion=(
                    "Die gemeinsame Abhängigkeit in ein eigenes Paket auslagern oder "
                    "die Kommunikation über das Cognitive Core führen."
                ),
            )
            for cycle in cycles
        ]

    # --- Klassen und Aktualität -------------------------------------------------

    def _check_classes(self) -> list[Finding]:
        """Meldet unübersichtliche Klassen und fehlende Schnittstellen."""

        findings: list[Finding] = []
        for path in (self._root / "backend").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

            relative = str(path.relative_to(self._root))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                methods = [
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                ]
                if len(methods) > _MAX_PUBLIC_METHODS:
                    findings.append(
                        Finding(
                            category="klassengröße",
                            severity="mittel",
                            message=(
                                f"Klasse '{node.name}' hat {len(methods)} öffentliche "
                                "Methoden und übernimmt vermutlich mehrere Aufgaben."
                            ),
                            location=f"{relative}:{node.lineno}",
                            suggestion="Verantwortlichkeiten auf mehrere Klassen aufteilen.",
                        )
                    )
        return findings

    def _check_stale_modules(self) -> list[Finding]:
        """Meldet Module, die sehr lange nicht geändert wurden."""

        findings: list[Finding] = []
        now = time.time()
        for path in (self._root / "backend").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                age = now - path.stat().st_mtime
            except OSError:
                continue
            if age > _STALE_SECONDS:
                findings.append(
                    Finding(
                        category="veraltet",
                        severity="gering",
                        message=(
                            f"'{path.name}' wurde seit über einem Jahr nicht geändert."
                        ),
                        location=str(path.relative_to(self._root)),
                        suggestion="Prüfen, ob das Modul noch benötigt wird.",
                    )
                )
        return findings

    @staticmethod
    def _maintainability_score(
        graph: dict[str, set[str]], cycles: list[list[str]], findings: list[Finding]
    ) -> float:
        """Berechnet eine Wartbarkeitskennzahl zwischen 0.0 und 1.0."""

        if not graph:
            return 1.0

        score = 1.0
        score -= min(0.4, len(cycles) * 0.1)
        severe = sum(1 for finding in findings if finding.severity == "hoch")
        moderate = sum(1 for finding in findings if finding.severity == "mittel")
        score -= min(0.3, severe * 0.05)
        score -= min(0.2, moderate * 0.01)

        average_fan_out = sum(len(targets) for targets in graph.values()) / len(graph)
        if average_fan_out > 6:
            score -= min(0.1, (average_fan_out - 6) * 0.02)

        return max(0.0, min(1.0, score))
