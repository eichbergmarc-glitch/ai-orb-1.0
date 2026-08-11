"""Performance Analyzer – sucht Leistungsprobleme im eigenen Code.

Gesucht werden langsame Funktionen, hoher Speicherverbrauch, unnötige
Hintergrundprozesse, blockierende Aufrufe sowie ungenutztes GPU-/CPU-
Potenzial. Daraus entstehen konkrete Optimierungsvorschläge.

Ergänzend erfasst der Analyzer Laufzeitmessungen, die andere Module über
:meth:`PerformanceAnalyzer.record` melden.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.evolution.code_analyzer import Finding
from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)

#: Aufrufe, die in asynchronem Code die Event-Loop blockieren.
_BLOCKING_CALLS: dict[str, str] = {
    "sleep": "time.sleep blockiert die Event-Loop; asyncio.sleep verwenden.",
    "urlopen": "urllib.request.urlopen blockiert; in asyncio.to_thread auslagern.",
    "run": "subprocess.run blockiert; asyncio.create_subprocess_exec verwenden.",
    "read": "Blockierendes Lesen großer Dateien; in asyncio.to_thread auslagern.",
}

#: Ab dieser Laufzeit gilt eine Funktion als langsam.
_SLOW_SECONDS = 1.0


@dataclass
class Measurement:
    """Eine Laufzeitmessung."""

    name: str
    samples: list[float] = field(default_factory=list)

    @property
    def average(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    @property
    def worst(self) -> float:
        return max(self.samples) if self.samples else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "calls": len(self.samples),
            "average": round(self.average, 4),
            "worst": round(self.worst, 4),
        }


class PerformanceAnalyzer:
    """Analysiert Laufzeitverhalten und blockierende Aufrufe."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_project_root()
        self._measurements: dict[str, Measurement] = defaultdict(lambda: Measurement(name=""))

    # --- Laufzeitmessungen ----------------------------------------------------

    def record(self, name: str, duration: float) -> None:
        """Meldet eine gemessene Laufzeit."""

        measurement = self._measurements.get(name)
        if measurement is None or not measurement.name:
            measurement = Measurement(name=name)
            self._measurements[name] = measurement
        measurement.samples.append(duration)
        if len(measurement.samples) > 200:
            measurement.samples.pop(0)

    def slow_operations(self) -> list[Measurement]:
        """Alle Operationen, die im Schnitt zu lange dauern."""

        return [
            measurement
            for measurement in self._measurements.values()
            if measurement.average >= _SLOW_SECONDS
        ]

    # --- Statische Analyse -----------------------------------------------------

    def analyze(self) -> dict[str, Any]:
        """Untersucht den Code auf Leistungsprobleme."""

        findings: list[Finding] = []
        findings.extend(self._find_blocking_calls())
        findings.extend(self._find_background_loops())
        findings.extend(self._find_memory_risks())
        findings.extend(self._describe_slow_operations())

        logger.info("Leistungsanalyse: %d Hinweise.", len(findings))
        return {
            "findings": [finding.to_dict() for finding in findings],
            "measurements": [m.to_dict() for m in self._measurements.values() if m.name],
            "suggestions": self._optimization_suggestions(findings),
        }

    def _iter_trees(self):
        for path in (self._root / "backend").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                yield path, ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue

    def _find_blocking_calls(self) -> list[Finding]:
        """Sucht blockierende Aufrufe innerhalb asynchroner Funktionen."""

        findings: list[Finding] = []
        for path, tree in self._iter_trees():
            relative = str(path.relative_to(self._root))
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                for child in ast.walk(node):
                    if not isinstance(child, ast.Call):
                        continue
                    name = ""
                    if isinstance(child.func, ast.Attribute):
                        name = child.func.attr
                    elif isinstance(child.func, ast.Name):
                        name = child.func.id
                    hint = _BLOCKING_CALLS.get(name)
                    if hint and not self._is_in_thread(child):
                        findings.append(
                            Finding(
                                category="blockierend",
                                severity="mittel",
                                message=(
                                    f"Blockierender Aufruf '{name}' in der asynchronen "
                                    f"Funktion '{node.name}'."
                                ),
                                location=f"{relative}:{child.lineno}",
                                suggestion=hint,
                            )
                        )
        return findings

    @staticmethod
    def _is_in_thread(node: ast.Call) -> bool:
        """Prüft grob, ob ein Aufruf bereits ausgelagert wurde."""

        parent_source = getattr(node, "_ai_orb_parent", None)
        return parent_source is not None

    def _find_background_loops(self) -> list[Finding]:
        """Sucht Endlosschleifen ohne Wartezeit (unnötige CPU-Last)."""

        findings: list[Finding] = []
        for path, tree in self._iter_trees():
            relative = str(path.relative_to(self._root))
            for node in ast.walk(tree):
                if not isinstance(node, ast.While):
                    continue
                is_infinite = isinstance(node.test, ast.Constant) and node.test.value is True
                if not is_infinite:
                    continue
                has_wait = any(
                    isinstance(child, ast.Await)
                    or (
                        isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr in ("sleep", "get", "wait", "recv", "accept")
                    )
                    for child in ast.walk(node)
                )
                if not has_wait:
                    findings.append(
                        Finding(
                            category="hintergrundlast",
                            severity="hoch",
                            message="Endlosschleife ohne Wartepunkt erzeugt dauerhafte CPU-Last.",
                            location=f"{relative}:{node.lineno}",
                            suggestion="Eine Wartezeit oder ein blockierendes Warten einbauen.",
                        )
                    )
        return findings

    def _find_memory_risks(self) -> list[Finding]:
        """Sucht unbegrenzt wachsende Sammlungen."""

        findings: list[Finding] = []
        for path, tree in self._iter_trees():
            relative = str(path.relative_to(self._root))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                appends = [
                    child
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "append"
                ]
                trims = [
                    child
                    for child in ast.walk(node)
                    if isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in ("pop", "clear")
                ]
                if len(appends) >= 2 and not trims:
                    findings.append(
                        Finding(
                            category="speicher",
                            severity="gering",
                            message=(
                                f"In '{node.name}' wächst eine Sammlung, ohne dass sie "
                                "wieder begrenzt wird."
                            ),
                            location=f"{relative}:{node.lineno}",
                            suggestion="Obergrenze einführen und älteste Einträge verwerfen.",
                        )
                    )
        return findings

    def _describe_slow_operations(self) -> list[Finding]:
        """Erzeugt Hinweise zu gemessenen langsamen Operationen."""

        return [
            Finding(
                category="laufzeit",
                severity="mittel",
                message=(
                    f"'{measurement.name}' dauert im Schnitt {measurement.average:.2f} s "
                    f"(schlechtester Wert {measurement.worst:.2f} s)."
                ),
                location=measurement.name,
                suggestion="Zwischenergebnisse zwischenspeichern oder parallelisieren.",
            )
            for measurement in self.slow_operations()
        ]

    @staticmethod
    def _optimization_suggestions(findings: list[Finding]) -> list[str]:
        """Leitet allgemeine Optimierungsvorschläge aus den Befunden ab."""

        suggestions: list[str] = []
        categories = {finding.category for finding in findings}

        if "blockierend" in categories:
            suggestions.append(
                "Blockierende Aufrufe konsequent in Worker-Threads auslagern, damit "
                "die Oberfläche flüssig bleibt."
            )
        if "hintergrundlast" in categories:
            suggestions.append(
                "Hintergrundschleifen mit Wartezeiten versehen und bei Inaktivität "
                "pausieren."
            )
        if "speicher" in categories:
            suggestions.append(
                "Für alle wachsenden Sammlungen Obergrenzen festlegen."
            )
        if "laufzeit" in categories:
            suggestions.append(
                "Häufig genutzte Ergebnisse zwischenspeichern, statt sie neu zu berechnen."
            )
        if not suggestions:
            suggestions.append("Es wurden keine auffälligen Leistungsprobleme gefunden.")
        return suggestions
