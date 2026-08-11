"""Tests von Pfadtrennung, Startprüfung und Absturzbehandlung.

Diese Tests decken die Phasen 45, 52, 57, 58 und 59 ab. Der Schwerpunkt
liegt auf dem, was bei einer Installation schiefgehen kann und teuer wäre:
dass Benutzerdaten am falschen Ort landen, dass ein entbehrlicher Ausfall
den ganzen Orb beendet, oder dass eine Absturzschleife den Rechner
lahmlegt.
"""

from __future__ import annotations

import os
import time

import pytest

from backend.launcher.health_check import (
    CheckResult,
    CheckState,
    HealthCheck,
    HealthReport,
)
from backend.launcher.ollama_service import OllamaService
from backend.launcher.supervisor import Service, ServiceState, Supervisor
from backend.utils import paths


# --- Pfadtrennung (Phase 52) --------------------------------------------------


def test_portable_mode_keeps_everything_together() -> None:
    """Im Quellbetrieb liegen Programm und Daten zusammen."""

    assert paths.is_portable()
    assert paths.get_user_dir() == paths.get_project_root()
    assert paths.get_data_dir() == paths.get_project_root() / "data"


def test_environment_variable_overrides_data_directory(tmp_path, monkeypatch) -> None:
    """Der Ort der Benutzerdaten lässt sich erzwingen – für Tests und Sonderfälle."""

    target = tmp_path / "eigene-daten"
    monkeypatch.setenv(paths.DATA_DIRECTORY_ENVIRONMENT_VARIABLE, str(target))

    assert paths.get_user_dir() == target
    assert target.is_dir()


def test_installed_mode_uses_appdata(tmp_path, monkeypatch) -> None:
    """Installiert landen die Daten in %APPDATA%, nicht im Programmordner."""

    monkeypatch.delenv(paths.DATA_DIRECTORY_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv(paths.PORTABLE_ENVIRONMENT_VARIABLE, "0")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setattr(paths, "is_portable", lambda: False)
    monkeypatch.setattr(paths.platform, "system", lambda: "Windows")

    user_dir = paths.get_user_dir()
    assert user_dir.name == paths.APP_FOLDER_NAME
    assert "Roaming" in str(user_dir)
    assert user_dir != paths.get_project_root()


def test_models_go_to_cache_not_roaming(tmp_path, monkeypatch) -> None:
    """Sprachmodelle gehören in den lokalen Zwischenspeicher.

    In einem Netzwerk wandert %APPDATA% mit dem Benutzerprofil mit. Ein
    Sprachmodell von mehreren hundert Megabyte hätte dort nichts verloren.
    """

    monkeypatch.delenv(paths.DATA_DIRECTORY_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setattr(paths, "is_portable", lambda: False)
    monkeypatch.setattr(paths.platform, "system", lambda: "Windows")

    models = paths.get_models_dir()
    assert "Local" in str(models)
    assert "Roaming" not in str(models)


def test_user_directories_are_created(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(paths.DATA_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / "orb"))

    paths.ensure_user_directories()
    for name in paths.USER_SUBDIRECTORIES:
        assert (tmp_path / "orb" / name).is_dir(), name


def test_user_config_is_copied_once(tmp_path, monkeypatch) -> None:
    """Beim ersten Start wird die Konfiguration kopiert, danach nie wieder.

    Das ist die Voraussetzung dafür, dass ein Update eigene Einstellungen
    nicht überschreibt.
    """

    monkeypatch.setenv(paths.DATA_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / "orb"))
    monkeypatch.setattr(paths, "is_portable", lambda: False)

    path, created = paths.ensure_user_config()
    assert created
    assert path.is_file()

    # Der Benutzer ändert etwas.
    path.write_text("app:\n  name: 'Mein Orb'\n", encoding="utf-8")

    path_again, created_again = paths.ensure_user_config()
    assert not created_again
    assert "Mein Orb" in path_again.read_text(encoding="utf-8")


def test_migration_never_overwrites(tmp_path, monkeypatch) -> None:
    """Die Übernahme alter Daten überschreibt nichts am Zielort."""

    monkeypatch.setenv(paths.DATA_DIRECTORY_ENVIRONMENT_VARIABLE, str(tmp_path / "ziel"))
    monkeypatch.setattr(paths, "is_portable", lambda: False)

    existing = tmp_path / "ziel" / "data" / "memory.json"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("neu", encoding="utf-8")

    outcome = paths.migrate_from_project(dry_run=True)
    assert isinstance(outcome, dict)
    # Die vorhandene Datei darf in keinem Fall angefasst werden.
    assert existing.read_text(encoding="utf-8") == "neu"


def test_describe_lists_all_locations() -> None:
    """Für die Fehlersuche muss ablesbar sein, wo alles liegt."""

    described = paths.describe()
    for key in ("modus", "programm", "benutzerdaten", "konfiguration", "protokolle"):
        assert key in described
        assert described[key]


# --- Startprüfung (Phase 59) ---------------------------------------------------


def test_health_report_format_matches_specification() -> None:
    """Der Bericht hat die in der Vorgabe verlangte Form."""

    report = HealthReport(
        results=[
            CheckResult("Windows", CheckState.OK, "Windows 11"),
            CheckResult("Backend", CheckState.OK, "Fassung 0.4.0"),
        ]
    )
    text = report.as_text()

    assert text.startswith("AI-ORB STARTUP")
    assert "[✓] Windows" in text
    assert "STATUS: READY" in text


def test_optional_failure_does_not_block_readiness() -> None:
    """Ohne Kokoro läuft AI-Orb – ohne Backend nicht."""

    report = HealthReport(
        results=[
            CheckResult("Backend", CheckState.OK, required=True),
            CheckResult("Kokoro", CheckState.WARNING, "keine Stimme", required=False),
        ]
    )
    assert report.ready

    report.results.append(CheckResult("Runtime", CheckState.FAILED, required=True))
    assert not report.ready
    assert "NICHT BEREIT" in report.as_text()


def test_degraded_state_is_visible() -> None:
    """Eine Einschränkung wird benannt, nicht verschwiegen."""

    report = HealthReport(
        results=[
            CheckResult("Backend", CheckState.OK, required=True),
            CheckResult("Whisper", CheckState.WARNING, "fehlt", required=False),
        ]
    )
    assert report.ready
    assert report.degraded
    assert "eingeschränkt" in report.status_word()


def test_remedies_are_shown_for_failures() -> None:
    """Was fehlt, wird mit dem nächsten Schritt erklärt."""

    report = HealthReport(
        results=[
            CheckResult(
                "Whisper",
                CheckState.FAILED,
                "fehlt",
                remedy="Die Neuinstallation bringt sie mit.",
                required=False,
            )
        ]
    )
    assert "Die Neuinstallation bringt sie mit." in report.as_text()


def test_check_never_raises() -> None:
    """Eine abstürzende Prüfung wird zum Ergebnis, nicht zum Absturz."""

    check = HealthCheck()

    def broken() -> tuple[CheckState, str, str]:
        raise RuntimeError("kaputt")

    result = check._run("Kaputt", broken)  # noqa: SLF001
    assert result.state is CheckState.FAILED
    assert "kaputt" in result.remedy


def test_full_health_check_runs() -> None:
    """Die vollständige Prüfung läuft durch und liefert alle Abschnitte."""

    report = HealthCheck().run()
    names = {result.name for result in report.results}

    for expected in ("Runtime", "Backend", "ProviderManager", "Konfiguration"):
        assert expected in names, expected

    assert report.seconds > 0
    assert "AI-ORB STARTUP" in report.as_text()


# --- Absturzbehandlung (Phase 58) --------------------------------------------------


def test_supervisor_restarts_failed_service() -> None:
    """Ein ausgefallener Dienst wird neu gestartet."""

    alive = {"value": True}
    starts = {"count": 0}

    def start() -> bool:
        starts["count"] += 1
        alive["value"] = True
        return True

    supervisor = Supervisor(check_interval=0.1)
    supervisor.register(
        Service(name="Probe", start=start, is_alive=lambda: alive["value"], required=False)
    )

    assert supervisor.start_service("Probe")
    assert starts["count"] == 1

    alive["value"] = False
    events = supervisor.check_once()

    assert len(events) == 1
    assert events[0].recovered
    assert starts["count"] == 2


def test_supervisor_gives_up_after_limit() -> None:
    """Ein dauerhaft kaputter Dienst wird nicht endlos neu gestartet."""

    supervisor = Supervisor(check_interval=0.05)
    supervisor.register(
        Service(
            name="Kaputt",
            start=lambda: False,
            is_alive=lambda: False,
            required=False,
            max_restarts=1,
            failure_message="Bleibt aus.",
        )
    )

    # Der erste Start scheitert bereits.
    assert not supervisor.start_service("Kaputt")
    assert supervisor._services["Kaputt"].state is ServiceState.UNAVAILABLE  # noqa: SLF001

    # Ein nicht laufender Dienst wird nicht weiter geprüft.
    assert supervisor.check_once() == []


def test_optional_failure_keeps_orb_healthy() -> None:
    """Ein entbehrlicher Ausfall macht AI-Orb nicht ungesund."""

    supervisor = Supervisor()
    supervisor.register(
        Service(name="Kern", start=lambda: True, is_alive=lambda: True, required=True)
    )
    supervisor.register(
        Service(name="Stimme", start=lambda: False, is_alive=lambda: False, required=False)
    )

    supervisor.start_all()

    assert supervisor.is_healthy()
    assert "Stimme" in supervisor.failed_services()


def test_required_failure_makes_orb_unhealthy() -> None:
    supervisor = Supervisor()
    supervisor.register(
        Service(name="Kern", start=lambda: False, is_alive=lambda: False, required=True)
    )
    supervisor.start_all()

    assert not supervisor.is_healthy()


def test_crashing_liveness_check_counts_as_dead() -> None:
    """Eine abstürzende Lebensprüfung darf die Überwachung nicht mitreißen."""

    def broken_check() -> bool:
        raise RuntimeError("kaputt")

    supervisor = Supervisor(check_interval=0.05)
    supervisor.register(
        Service(
            name="Wackelig",
            start=lambda: True,
            is_alive=broken_check,
            required=False,
            max_restarts=0,
        )
    )
    supervisor.start_service("Wackelig")

    events = supervisor.check_once()
    assert len(events) == 1
    assert not events[0].recovered


def test_recovery_history_is_kept() -> None:
    alive = {"value": True}
    supervisor = Supervisor(check_interval=0.05)
    supervisor.register(
        Service(
            name="Probe",
            start=lambda: True,
            is_alive=lambda: alive["value"],
            required=False,
        )
    )
    supervisor.start_service("Probe")

    alive["value"] = False
    supervisor.check_once()

    history = supervisor.history()
    assert len(history) == 1
    assert history[0]["service"] == "Probe"
    assert "time" in history[0]


# --- Ollama (Phase 49) ---------------------------------------------------------------


def test_ollama_reads_configured_model() -> None:
    service = OllamaService()
    assert service.configured_model()
    assert service.base_url().startswith("http")


def test_ollama_explicit_values_win() -> None:
    service = OllamaService(base_url="http://beispiel:1234/", model="testmodell")
    assert service.base_url() == "http://beispiel:1234"
    assert service.configured_model() == "testmodell"


def test_ollama_reports_missing_installation() -> None:
    """Fehlt Ollama, wird das erklärt statt stillschweigend übergangen."""

    service = OllamaService()
    state = service.prepare()

    assert "ready" in state
    assert "message" in state
    if not state["installed"]:
        assert state["remedy"]
        assert not state["ready"]


def test_ollama_status_is_complete() -> None:
    status = OllamaService().status()
    for key in ("installed", "running", "base_url", "model"):
        assert key in status
