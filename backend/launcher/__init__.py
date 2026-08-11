"""Der AI-Orb Launcher (Phasen 44, 45, 49, 58, 59).

Die zentrale Startkomponente der Windows-Fassung. Ein Klick im Startmenü,
und alles Weitere geschieht hier: prüfen, starten, überwachen, bei einem
Ausfall neu starten und am Ende geordnet beenden.

* :mod:`backend.launcher.health_check` – die Startprüfung mit dem Bericht
* :mod:`backend.launcher.ollama_service` – Offline-Rückfall finden und starten
* :mod:`backend.launcher.supervisor` – Ausfälle erkennen und beheben
* :mod:`backend.launcher.launcher` – alles zusammen

Der Benutzer bekommt davon nichts zu sehen außer einem Ladebildschirm und
danach dem Orb.
"""

from backend.launcher.health_check import (
    CheckResult,
    CheckState,
    HealthCheck,
    HealthReport,
    run_health_check,
)
from backend.launcher.launcher import Launcher, StartupResult, StartupStep
from backend.launcher.ollama_service import OllamaService
from backend.launcher.supervisor import RecoveryEvent, Service, ServiceState, Supervisor

__all__ = [
    "CheckResult",
    "CheckState",
    "HealthCheck",
    "HealthReport",
    "Launcher",
    "OllamaService",
    "RecoveryEvent",
    "Service",
    "ServiceState",
    "StartupResult",
    "StartupStep",
    "Supervisor",
    "run_health_check",
]
