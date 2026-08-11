"""Benchmark Engine – vergleicht alte und neue Version.

Verglichen werden Startzeit, Arbeitsspeicher, CPU-Zeit, Antwortzeit und
Stabilität.

**Nur Verbesserungen dürfen vorgeschlagen werden**: Ein Patch, der eine
Messgröße spürbar verschlechtert, wird nicht zur Übernahme empfohlen.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_project_root

logger = get_logger(__name__)

#: Ab dieser relativen Verschlechterung gilt eine Messgröße als Rückschritt.
_REGRESSION_TOLERANCE = 0.10

#: Messskript, das in beiden Versionen identisch ausgeführt wird.
_MEASURE_SCRIPT = """
import json, resource, sys, time
sys.path.insert(0, '.')

start = time.perf_counter()
import backend.cognitive, backend.memory, backend.orchestrator, backend.reasoning
startup = time.perf_counter() - start

begin = time.perf_counter()
from backend.orchestrator.intent_classifier import IntentClassifier
classifier = IntentClassifier()
for _ in range(200):
    classifier.classify("Erkläre mir den Investiturstreit und öffne danach Firefox")
response = (time.perf_counter() - begin) / 200

usage = resource.getrusage(resource.RUSAGE_SELF)
print("BENCHMARK=" + json.dumps({
    "startup_seconds": round(startup, 4),
    "response_seconds": round(response, 6),
    "memory_mb": round(usage.ru_maxrss / 1024, 1),
    "cpu_seconds": round(usage.ru_utime + usage.ru_stime, 4),
}))
"""


@dataclass
class BenchmarkResult:
    """Die Messwerte einer Version."""

    startup_seconds: float = 0.0
    response_seconds: float = 0.0
    memory_mb: float = 0.0
    cpu_seconds: float = 0.0
    stable: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "startup_seconds": self.startup_seconds,
            "response_seconds": self.response_seconds,
            "memory_mb": self.memory_mb,
            "cpu_seconds": self.cpu_seconds,
            "stable": self.stable,
            "error": self.error,
        }


@dataclass
class BenchmarkComparison:
    """Der Vergleich zweier Versionen."""

    before: BenchmarkResult
    after: BenchmarkResult
    improvements: list[str] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)

    @property
    def is_improvement(self) -> bool:
        """Ob die neue Version insgesamt besser oder mindestens gleichwertig ist."""

        return self.after.stable and not self.regressions

    def to_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "improvements": self.improvements,
            "regressions": self.regressions,
            "is_improvement": self.is_improvement,
        }

    def summary(self) -> str:
        """Fasst den Vergleich verständlich zusammen."""

        if not self.after.stable:
            return f"Die neue Version ist nicht stabil: {self.after.error}"
        if self.regressions:
            return "Verschlechterungen festgestellt: " + "; ".join(self.regressions)
        if self.improvements:
            return "Verbesserungen: " + "; ".join(self.improvements)
        return "Keine messbaren Unterschiede – die Änderung ist leistungsneutral."


class BenchmarkEngine:
    """Misst und vergleicht zwei Versionen von AI-Orb."""

    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._timeout = timeout_seconds

    def measure(self, workspace: Path) -> BenchmarkResult:
        """Misst die Kennzahlen einer Version.

        Args:
            workspace: Verzeichnis der zu messenden Version.

        Returns:
            Die Messwerte; bei einem Fehler ist ``stable`` ``False``.
        """

        try:
            result = subprocess.run(  # noqa: S603 - feste Argumentliste.
                [sys.executable, "-c", _MEASURE_SCRIPT],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return BenchmarkResult(stable=False, error=str(error))

        if result.returncode != 0:
            return BenchmarkResult(
                stable=False, error=(result.stderr or "Messlauf fehlgeschlagen")[-500:]
            )

        for line in result.stdout.splitlines():
            if line.startswith("BENCHMARK="):
                try:
                    data = json.loads(line.split("=", 1)[1])
                except json.JSONDecodeError:
                    continue
                return BenchmarkResult(
                    startup_seconds=float(data.get("startup_seconds", 0.0)),
                    response_seconds=float(data.get("response_seconds", 0.0)),
                    memory_mb=float(data.get("memory_mb", 0.0)),
                    cpu_seconds=float(data.get("cpu_seconds", 0.0)),
                    stable=True,
                )

        return BenchmarkResult(stable=False, error="Es wurden keine Messwerte geliefert.")

    def compare(self, patch_workspace: Path, *, baseline: Path | None = None) -> BenchmarkComparison:
        """Vergleicht die geänderte Version mit der aktuellen Fassung.

        Args:
            patch_workspace: Arbeitskopie mit der Änderung.
            baseline: Vergleichsversion (Standard: das laufende Projekt).

        Returns:
            Der Vergleich mit Verbesserungen und Verschlechterungen.
        """

        base_path = baseline or get_project_root()
        started = time.perf_counter()

        before = self.measure(base_path)
        after = self.measure(patch_workspace)

        comparison = BenchmarkComparison(before=before, after=after)

        if not after.stable or not before.stable:
            comparison.regressions.append("Die Messung konnte nicht abgeschlossen werden.")
            return comparison

        metrics = (
            ("Startzeit", "startup_seconds", "s"),
            ("Antwortzeit", "response_seconds", "s"),
            ("Arbeitsspeicher", "memory_mb", "MB"),
            ("CPU-Zeit", "cpu_seconds", "s"),
        )

        for label, attribute, unit in metrics:
            old_value = float(getattr(before, attribute))
            new_value = float(getattr(after, attribute))
            if old_value <= 0:
                continue
            change = (new_value - old_value) / old_value

            if change <= -_REGRESSION_TOLERANCE:
                comparison.improvements.append(
                    f"{label} {abs(change) * 100:.0f} % besser "
                    f"({old_value:.3f} → {new_value:.3f} {unit})"
                )
            elif change >= _REGRESSION_TOLERANCE:
                comparison.regressions.append(
                    f"{label} {change * 100:.0f} % schlechter "
                    f"({old_value:.3f} → {new_value:.3f} {unit})"
                )

        logger.info(
            "Benchmark in %.1f s: %d Verbesserung(en), %d Verschlechterung(en).",
            time.perf_counter() - started,
            len(comparison.improvements),
            len(comparison.regressions),
        )
        return comparison
