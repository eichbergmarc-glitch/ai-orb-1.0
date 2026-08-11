"""Execution Manager – geplante Ausführung von Desktop-Aktionen.

Jede Desktop-Aktion durchläuft denselben Ablauf:

Befehl verstehen → Programm finden → Aktion ausführen → Erfolg prüfen →
Benutzer informieren.

Schlägt ein Schritt fehl, wird eine Alternative versucht (z. B. ein anderer
freigegebener Browser), bevor der Fehler gemeldet wird. Stille Fehler gibt
es nicht.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.system.desktop_control import ActionResult, DesktopControl
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)

#: Alternativen, die versucht werden, wenn das gewünschte Programm fehlt.
_ALTERNATIVES: dict[str, tuple[str, ...]] = {
    "browser": ("firefox", "chrome", "browser"),
    "firefox": ("browser", "chrome"),
    "chrome": ("browser", "firefox"),
    "terminal": ("powershell", "terminal"),
    "powershell": ("terminal",),
    "vscode": ("notepad",),
}


@dataclass
class ExecutionStep:
    """Ein Schritt der Ausführung."""

    name: str
    success: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "success": self.success, "detail": self.detail}


@dataclass
class ExecutionReport:
    """Der vollständige Ablauf einer Desktop-Aktion."""

    action: str
    target: str
    success: bool = False
    steps: list[ExecutionStep] = field(default_factory=list)
    used_alternative: str | None = None
    message: str = ""
    requires_confirmation: bool = False
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "success": self.success,
            "steps": [step.to_dict() for step in self.steps],
            "used_alternative": self.used_alternative,
            "message": self.message,
            "requires_confirmation": self.requires_confirmation,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class ExecutionManager:
    """Führt Desktop-Aktionen geplant und nachvollziehbar aus."""

    def __init__(self, desktop: DesktopControl | None = None) -> None:
        self._desktop = desktop or DesktopControl()

    def launch(self, target: str, *, risk_confirmed: bool = True) -> ExecutionReport:
        """Startet ein Programm mit vollständiger Ablaufkontrolle.

        Args:
            target: Name oder Alias des Programms.
            risk_confirmed: Ob eine gegebenenfalls nötige Bestätigung
                bereits vorliegt.

        Returns:
            Der Ausführungsbericht.
        """

        started = time.perf_counter()
        report = ExecutionReport(action="starten", target=target)

        # Schritt 1: Befehl verstehen.
        if not target.strip():
            report.steps.append(ExecutionStep("Befehl verstehen", False, "Kein Ziel angegeben."))
            report.message = "Ich habe nicht erkannt, welches Programm gemeint ist."
            report.duration_seconds = time.perf_counter() - started
            return report
        report.steps.append(ExecutionStep("Befehl verstehen", True, f"Ziel: {target}"))

        # Schritt 2: Programm finden.
        entry = self._desktop.resolve_application(target)
        if entry is None:
            report.steps.append(
                ExecutionStep(
                    "Programm finden",
                    False,
                    f"'{target}' ist nicht freigegeben.",
                )
            )
            report.message = (
                f"'{target}' ist nicht freigegeben. Freigegeben sind: "
                + (", ".join(self._desktop.known_applications) or "(keine)")
            )
            report.duration_seconds = time.perf_counter() - started
            return report
        report.steps.append(ExecutionStep("Programm finden", True, str(entry.get("command"))))

        if not risk_confirmed:
            report.requires_confirmation = True
            report.message = f"Soll ich {entry['key']} starten?"
            report.duration_seconds = time.perf_counter() - started
            return report

        # Schritt 3: Aktion ausführen (mit Alternativen bei Fehlschlag).
        result = self._desktop.launch(target)
        if not result.success:
            for alternative in _ALTERNATIVES.get(str(entry["key"]).lower(), ()):
                if alternative == entry["key"]:
                    continue
                fallback = self._desktop.launch(alternative)
                if fallback.success:
                    report.used_alternative = alternative
                    result = fallback
                    report.steps.append(
                        ExecutionStep(
                            "Aktion ausführen",
                            True,
                            f"'{target}' war nicht verfügbar, '{alternative}' wurde stattdessen gestartet.",
                        )
                    )
                    break
            else:
                report.steps.append(ExecutionStep("Aktion ausführen", False, result.message))
                report.message = (
                    f"{result.message} Ich habe auch keine Alternative gefunden."
                )
                report.duration_seconds = time.perf_counter() - started
                logger.warning("Ausführung fehlgeschlagen: %s", result.message)
                return report
        else:
            report.steps.append(ExecutionStep("Aktion ausführen", True, result.message))

        # Schritt 4: Erfolg prüfen.
        report.steps.append(ExecutionStep("Erfolg prüfen", True, "Prozess wurde gestartet."))
        report.success = True

        # Schritt 5: Benutzer informieren.
        if report.used_alternative:
            report.message = (
                f"{target} war nicht verfügbar – ich habe stattdessen "
                f"{report.used_alternative} gestartet."
            )
        else:
            report.message = result.message
        report.steps.append(ExecutionStep("Benutzer informieren", True, report.message))

        report.duration_seconds = time.perf_counter() - started
        return report

    def close(self, target: str, *, confirmed: bool = False) -> ExecutionReport:
        """Beendet ein Programm – nur nach ausdrücklicher Bestätigung."""

        started = time.perf_counter()
        report = ExecutionReport(action="beenden", target=target)
        report.steps.append(ExecutionStep("Befehl verstehen", True, f"Ziel: {target}"))

        result: ActionResult = self._desktop.close(target, confirmed=confirmed)
        report.requires_confirmation = result.requires_confirmation
        report.success = result.success
        report.message = result.message
        report.steps.append(
            ExecutionStep("Aktion ausführen", result.success, result.message)
        )
        report.duration_seconds = time.perf_counter() - started
        return report

    def open_document(self, path: str) -> ExecutionReport:
        """Öffnet ein Dokument mit dem Standardprogramm."""

        started = time.perf_counter()
        report = ExecutionReport(action="öffnen", target=path)
        result = self._desktop.open_path(path)
        report.success = result.success
        report.message = result.message
        report.steps.append(ExecutionStep("Aktion ausführen", result.success, result.message))
        report.duration_seconds = time.perf_counter() - started
        return report
