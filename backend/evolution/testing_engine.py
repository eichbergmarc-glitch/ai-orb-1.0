"""Testing Engine – prüft jede Änderung vor der Freigabe.

Vor jeder Freigabe laufen Unit-Tests, Integrationstests, Regressionstests,
Leistungstests und Sicherheitsprüfungen. Bestehende Funktionen dürfen nicht
unbeabsichtigt beeinträchtigt werden.

Getestet wird ausschließlich in der isolierten Arbeitskopie – niemals im
produktiven Code.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class TestRun:
    """Das Ergebnis eines Testlaufs."""

    kind: str
    passed: bool
    total: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    output: str = ""
    skipped_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "passed": self.passed,
            "total": self.total,
            "failed": self.failed,
            "duration_seconds": round(self.duration_seconds, 2),
            "skipped_reason": self.skipped_reason,
            "output": self.output[-2000:],
        }


@dataclass
class TestReport:
    """Der Gesamtbericht aller Testarten."""

    runs: list[TestRun] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Ob alle durchgeführten Tests bestanden wurden."""

        return all(run.passed for run in self.runs)

    @property
    def summary(self) -> str:
        """Kurzfassung des Ergebnisses."""

        parts = []
        for run in self.runs:
            if run.skipped_reason:
                parts.append(f"{run.kind}: übersprungen ({run.skipped_reason})")
            else:
                parts.append(
                    f"{run.kind}: {'bestanden' if run.passed else 'fehlgeschlagen'} "
                    f"({run.total - run.failed}/{run.total})"
                )
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "runs": [run.to_dict() for run in self.runs],
        }


class TestingEngine:
    """Führt alle Testarten in der Arbeitskopie aus."""

    def __init__(self, timeout_seconds: float = 600.0) -> None:
        self._timeout = timeout_seconds

    def run_all(self, workspace: Path) -> TestReport:
        """Führt alle Prüfungen für eine Arbeitskopie aus.

        Args:
            workspace: Die isolierte Arbeitskopie mit den Änderungen.

        Returns:
            Der Gesamtbericht.
        """

        report = TestReport()
        report.runs.append(self.syntax_check(workspace))
        report.runs.append(self.unit_tests(workspace))
        report.runs.append(self.integration_tests(workspace))
        report.runs.append(self.regression_tests(workspace))
        report.runs.append(self.performance_tests(workspace))
        report.runs.append(self.security_check(workspace))

        logger.info("Testlauf abgeschlossen: %s", report.summary)
        return report

    # --- Einzelne Testarten ---------------------------------------------------

    def syntax_check(self, workspace: Path) -> TestRun:
        """Prüft, ob sämtlicher Python-Code fehlerfrei übersetzt werden kann."""

        started = time.perf_counter()
        files = [
            path
            for path in (workspace / "backend").rglob("*.py")
            if "__pycache__" not in path.parts
        ]
        failed = 0
        messages: list[str] = []

        for path in files:
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (SyntaxError, OSError) as error:
                failed += 1
                messages.append(f"{path.name}: {error}")

        return TestRun(
            kind="syntax",
            passed=failed == 0,
            total=len(files),
            failed=failed,
            duration_seconds=time.perf_counter() - started,
            output="\n".join(messages),
        )

    def unit_tests(self, workspace: Path) -> TestRun:
        """Führt die Unit-Tests aus."""

        return self._run_pytest(workspace, "tests", kind="unit")

    def integration_tests(self, workspace: Path) -> TestRun:
        """Führt Integrationstests aus (falls vorhanden)."""

        target = workspace / "tests" / "integration"
        if not target.exists():
            return TestRun(
                kind="integration",
                passed=True,
                skipped_reason="keine Integrationstests vorhanden",
            )
        return self._run_pytest(workspace, "tests/integration", kind="integration")

    def regression_tests(self, workspace: Path) -> TestRun:
        """Prüft, ob bestehende Funktionen weiterhin importierbar sind.

        Der Test importiert sämtliche Backend-Pakete. Schlägt ein Import
        fehl, wurde eine bestehende Funktion beeinträchtigt.
        """

        started = time.perf_counter()
        script = (
            "import importlib, pkgutil, sys\n"
            "sys.path.insert(0, '.')\n"
            "import backend\n"
            "failed = []\n"
            "for module in pkgutil.walk_packages(backend.__path__, 'backend.'):\n"
            "    try:\n"
            "        importlib.import_module(module.name)\n"
            "    except Exception as error:\n"
            "        failed.append(f'{module.name}: {error}')\n"
            "print('FAILED:' + '|'.join(failed))\n"
        )

        try:
            result = subprocess.run(  # noqa: S603 - feste Argumentliste.
                [sys.executable, "-c", script],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            output = result.stdout + result.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            return TestRun(
                kind="regression",
                passed=False,
                duration_seconds=time.perf_counter() - started,
                output=str(error),
            )

        marker = "FAILED:"
        failures: list[str] = []
        for line in output.splitlines():
            if line.startswith(marker):
                payload = line[len(marker) :].strip()
                failures = [item for item in payload.split("|") if item]

        return TestRun(
            kind="regression",
            passed=not failures and result.returncode == 0,
            total=1,
            failed=len(failures),
            duration_seconds=time.perf_counter() - started,
            output="\n".join(failures) or output,
        )

    def performance_tests(self, workspace: Path) -> TestRun:
        """Misst die Startzeit der Backend-Importe als Leistungstest."""

        started = time.perf_counter()
        script = (
            "import sys, time\n"
            "sys.path.insert(0, '.')\n"
            "begin = time.perf_counter()\n"
            "import backend.cognitive, backend.memory, backend.orchestrator\n"
            "print(f'IMPORT_SECONDS={time.perf_counter() - begin:.4f}')\n"
        )

        try:
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-c", script],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return TestRun(
                kind="leistung",
                passed=False,
                duration_seconds=time.perf_counter() - started,
                output=str(error),
            )

        seconds = 0.0
        for line in result.stdout.splitlines():
            if line.startswith("IMPORT_SECONDS="):
                try:
                    seconds = float(line.split("=", 1)[1])
                except ValueError:
                    seconds = 0.0

        # Ein Start, der länger als fünf Sekunden dauert, gilt als Rückschritt.
        return TestRun(
            kind="leistung",
            passed=result.returncode == 0 and seconds < 5.0,
            total=1,
            failed=0 if seconds < 5.0 else 1,
            duration_seconds=time.perf_counter() - started,
            output=f"Importdauer: {seconds:.3f} s\n{result.stderr}",
        )

    def security_check(self, workspace: Path) -> TestRun:
        """Prüft den geänderten Code auf sicherheitskritische Muster."""

        started = time.perf_counter()
        risky_patterns = (
            ("eval(", "Ausführung beliebigen Codes"),
            ("exec(", "Ausführung beliebigen Codes"),
            ("shell=True", "Shell-Aufruf mit Injektionsrisiko"),
            ("pickle.loads", "Deserialisierung nicht vertrauenswürdiger Daten"),
            ("verify=False", "Deaktivierte Zertifikatsprüfung"),
        )

        findings: list[str] = []
        for path in (workspace / "backend").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern, reason in risky_patterns:
                if pattern in source:
                    findings.append(f"{path.name}: {pattern} – {reason}")

        return TestRun(
            kind="sicherheit",
            passed=not findings,
            total=1,
            failed=len(findings),
            duration_seconds=time.perf_counter() - started,
            output="\n".join(findings),
        )

    # --- Hilfsfunktionen ---------------------------------------------------------

    def _run_pytest(self, workspace: Path, target: str, *, kind: str) -> TestRun:
        """Führt pytest in der Arbeitskopie aus."""

        started = time.perf_counter()
        try:
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "pytest", target, "-q", "--no-header"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError:
            return TestRun(kind=kind, passed=True, skipped_reason="pytest ist nicht installiert")
        except (OSError, subprocess.TimeoutExpired) as error:
            return TestRun(
                kind=kind,
                passed=False,
                duration_seconds=time.perf_counter() - started,
                output=str(error),
            )

        output = result.stdout + result.stderr
        if "No module named pytest" in output:
            return TestRun(kind=kind, passed=True, skipped_reason="pytest ist nicht installiert")

        total, failed = self._parse_pytest_output(output)
        return TestRun(
            kind=kind,
            passed=result.returncode == 0,
            total=total,
            failed=failed,
            duration_seconds=time.perf_counter() - started,
            output=output,
        )

    @staticmethod
    def _parse_pytest_output(output: str) -> tuple[int, int]:
        """Liest Anzahl und Fehlschläge aus der pytest-Zusammenfassung."""

        passed = failed = 0
        for line in reversed(output.splitlines()):
            if " passed" in line or " failed" in line:
                for part in line.replace("=", " ").split(","):
                    tokens = part.strip().split()
                    if len(tokens) >= 2 and tokens[0].isdigit():
                        if tokens[1].startswith("passed"):
                            passed = int(tokens[0])
                        elif tokens[1].startswith("failed") or tokens[1].startswith("error"):
                            failed += int(tokens[0])
                break
        return passed + failed, failed
