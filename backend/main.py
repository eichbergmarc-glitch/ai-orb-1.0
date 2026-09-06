"""Einstiegspunkt des AI-Orb Backend-Prozesses.

Startet den Kern und den lokalen HTTP-Server, über den die Oberfläche
angebunden ist.

Aufruf::

    python -m backend.main               gewöhnlicher Start
    python -m backend.main --launcher    über den Launcher, mit Startprüfung
    python -m backend.main --check       nur prüfen, nicht starten

Der Unterschied zwischen den ersten beiden ist die Startprüfung: Mit
``--launcher`` wird vorher geprüft, ob alles Nötige da ist, und der Bericht
in der Form aus Phase 59 auf die Standardausgabe geschrieben. Electron liest
ihn mit und zeigt ihn im Ladebildschirm.

``--check`` prüft nur und beendet sich wieder. Das braucht das
Installationsprogramm, um am Ende sagen zu können, ob die Installation
geglückt ist.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from types import FrameType


def _crash_log_path() -> Path | None:
    """Bestimmt den Ort für den Absturzbericht – ohne config oder yaml.

    Dieser Pfad muss auch dann noch stimmen, wenn ausgerechnet das Laden der
    Konfiguration der Grund des Absturzes ist. Deshalb wird hier bewusst
    nichts aus dem übrigen Backend benutzt, sondern nur die Umgebung: unter
    Windows ``%APPDATA%\\AI-Orb\\logs``, sonst ``~/.config/ai-orb/logs``.
    Schlägt selbst das fehl, wird eben kein Bericht geschrieben – ein
    fehlender Bericht darf nie ein zweiter Absturz sein.
    """

    try:
        override = os.environ.get("AI_ORB_DATA_DIR", "").strip()
        if override:
            base = Path(override).expanduser()
        elif os.name == "nt":
            appdata = os.environ.get("APPDATA", "").strip()
            base = Path(appdata) / "AI-Orb" if appdata else Path.home() / "AI-Orb"
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
            base = (Path(xdg) if xdg else Path.home() / ".config") / "ai-orb"
        logs = base / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        return logs / "kern-crash.log"
    except Exception:
        return None


def _report_fatal(summary: str, detail: str = "") -> None:
    """Meldet einen tödlichen Startfehler doppelt: in eine Datei und nach stderr.

    Der Sinn ist, dass der Grund den Benutzer erreicht. Electron fängt die
    Fehlerausgabe des Kerns ein und zeigt sie im Ladebildschirm; ohne diese
    Zeilen bliebe dort nur „Der Kern wurde unerwartet beendet (Code 1)"
    stehen – eine Feststellung ohne Erkenntnis. Zusätzlich landet der ganze
    Bericht in ``logs/kern-crash.log``, damit er auch nach dem Schließen des
    Fensters noch nachlesbar ist.
    """

    block = summary if not detail else f"{summary}\n{detail}"

    # 1. Nach stderr – von dort holt Electron die Zeile in den Ladebildschirm.
    try:
        print(block, file=sys.stderr, flush=True)
    except Exception:
        pass

    # 2. In die Absturzdatei – überdauert das Fenster.
    path = _crash_log_path()
    if path is not None:
        try:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with path.open("a", encoding="utf-8", errors="replace") as handle:
                handle.write(f"\n===== {stamp} =====\n{block}\n")
        except Exception:
            pass


from backend import __version__
from backend.system.logging_setup import get_logger, setup_logging

def _ensure_utf8_output() -> None:
    """Stellt die Ausgabe auf UTF-8 um.

    Eine Windows-Konsole arbeitet voreingestellt mit einer alten
    Codepage – meist ``cp1252``. Alles, was sich darin nicht abbilden
    lässt, führt beim Schreiben nicht zu einem Ersatzzeichen, sondern zu
    einem ``UnicodeEncodeError``, und der beendet das Programm.

    Die Startprüfung schreibt Häkchen (``✓``) und Kreuze. Ausgerechnet der
    Bericht, der sagen soll, ob alles in Ordnung ist, brachte damit den
    Aufruf zum Absturz – und zwar erst in der letzten Zeile, nachdem alle
    Prüfungen längst erfolgreich durchgelaufen waren. Der Eindruck war
    ein kaputtes AI-Orb; tatsächlich war es eine kaputte Konsole.

    ``errors="replace"`` als zweite Absicherung: Lieber ein Fragezeichen
    im Text als ein Abbruch wegen eines Zeichens.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Eine umgeleitete Ausgabe lässt sich nicht immer umstellen.
            # Das ist kein Grund, gar nicht erst zu starten.
            pass


_ensure_utf8_output()

# Die Protokollierung darf beim Hochfahren nicht der Grund des Scheiterns
# sein. Kann sie nicht eingerichtet werden – etwa weil sich der
# Protokollordner nicht anlegen lässt –, wird das gemeldet und mit einer
# nackten Konsolen-Protokollierung weitergemacht, statt gar nicht zu starten.
try:
    setup_logging()
except Exception:  # noqa: BLE001
    _report_fatal(
        "Die Protokollierung ließ sich nicht einrichten – AI-Orb läuft mit "
        "eingeschränkter Protokollierung weiter.",
        traceback.format_exc(),
    )
    import logging

    logging.basicConfig(level=logging.INFO)

logger = get_logger(__name__)

#: Diese Kennung stellt der Launcher jeder Fortschrittszeile voran, damit
#: Electron sie vom übrigen Protokoll unterscheiden kann.
PROGRESS_PREFIX = "@@ORB@@"

# Muss fuer die gesamte Prozesslebensdauer referenziert bleiben. Schliesst
# Python den Handle, verschwindet auch der benannte Windows-Mutex.
_INSTANCE_MUTEX_HANDLE: int | None = None


def _acquire_single_instance() -> bool:
    """Laesst unter Windows genau einen Orb-Kern pro Anmeldung zu.

    Die HTTP-Portpruefung kommt zu spaet: Bis der zweite Prozess dort
    scheitert, laufen Mikrofon und TTS bereits. Genau so entstanden am
    24.08.2026 zwei Stimmen und doppelte Tagebucheintraege. Der Mutex wird
    deshalb vor Launcher, Runtime und Audiogeraeten erworben.
    """

    global _INSTANCE_MUTEX_HANDLE
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, "Local\\AI-Orb-Backend-SingleInstance")
        if not handle:
            logger.warning("Einzelinstanz-Sperre konnte nicht angelegt werden.")
            return True
        _INSTANCE_MUTEX_HANDLE = int(handle)
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 - Start nicht wegen Schutzmechanismus verhindern.
        logger.exception("Einzelinstanz-Sperre ist fehlgeschlagen.")
        return True


def _emit(kind: str, payload: dict[str, object]) -> None:
    """Schreibt eine maschinenlesbare Zeile für die Oberfläche."""

    print(
        PROGRESS_PREFIX + json.dumps({"kind": kind, **payload}, ensure_ascii=False),
        flush=True,
    )


def run_check() -> int:
    """Führt nur die Startprüfung aus.

    Wird vom Installationsprogramm benutzt, um die Installation
    abschließend zu prüfen.

    Returns:
        0, wenn AI-Orb betriebsbereit ist.
    """

    from backend.launcher.health_check import run_health_check

    report = run_health_check()
    print(report.as_text(), flush=True)
    _emit("health", report.to_dict())

    return 0 if report.ready else 1


def run_with_launcher() -> int:
    """Startet AI-Orb über den Launcher, mit Startprüfung und Überwachung."""

    from backend.launcher.launcher import Launcher, StartupStep

    def on_progress(step: StartupStep) -> None:
        _emit(
            "progress",
            {"step": step.key, "label": step.label, "ok": step.ok, "detail": step.detail},
        )

    def on_recovery(event: object) -> None:
        _emit("recovery", {"event": getattr(event, "to_dict", dict)()})

    launcher = Launcher(on_progress=on_progress, on_recovery=on_recovery)
    result = launcher.start()

    _emit(
        "ready" if result.ready else "failed",
        {
            "ready": result.ready,
            "message": result.message,
            "limitations": result.limitations,
            "seconds": round(result.seconds, 2),
        },
    )

    if not result.ready:
        # Der Grund muss sichtbar werden. print() allein landet auf der
        # Standardausgabe; Electron unterscheidet aber Fehler an der
        # Fehlerausgabe. Ohne die zweite Zeile bliebe im Ladebildschirm nur
        # „Code 1" stehen, ohne zu sagen, was fehlte.
        print(result.message, flush=True)
        detail = "\n".join(str(item) for item in result.limitations)
        _report_fatal(
            f"AI-Orb ist nicht startbereit: {result.message}",
            detail,
        )
        return 1

    if result.report is not None:
        logger.info("Startbericht:\n%s", result.report.as_text())

    _wait_for_shutdown(lambda: launcher.stop())
    return 0


def run_plain() -> int:
    """Startet AI-Orb ohne Startprüfung – der schlanke Weg."""

    from backend.api.server import create_server
    from backend.runtime import get_runtime

    logger.info("=" * 60)
    logger.info("AI-Orb %s wird gestartet.", __version__)
    logger.info("=" * 60)

    runtime = get_runtime()
    runtime.start()

    server = create_server(runtime)
    try:
        server.start()
    except OSError as error:
        logger.error(
            "Der lokale Server konnte nicht gestartet werden: %s. "
            "Läuft AI-Orb bereits, oder ist der Port belegt?",
            error,
        )
        runtime.stop()
        return 1

    print(f"AI-Orb {__version__} läuft. Backend: http://127.0.0.1:{server.port}", flush=True)
    _emit("ready", {"ready": True, "message": "AI-Orb läuft.", "limitations": []})

    def shutdown() -> None:
        server.stop()
        runtime.stop()

    _wait_for_shutdown(shutdown)
    return 0


def _wait_for_shutdown(shutdown: object) -> None:
    """Hält den Prozess am Leben, bis ein Beendigungssignal kommt.

    Electron beendet den Kern über ``SIGTERM``. Darauf muss geordnet
    heruntergefahren werden – sonst bleiben Mikrofon und Dateien offen.
    """

    stopping = False

    def _handle_signal(signum: int, frame: FrameType | None) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        logger.info("Signal %s empfangen – AI-Orb wird beendet.", signum)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is not None:
            try:
                signal.signal(handler, _handle_signal)
            except (ValueError, OSError):
                # Nicht jede Plattform unterstützt jedes Signal.
                pass

    try:
        while not stopping:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Abbruch durch Benutzer.")
    finally:
        try:
            shutdown()  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            logger.exception("Fehler beim Herunterfahren.")

    logger.info("AI-Orb wurde beendet.")


def main(argv: list[str] | None = None) -> int:
    """Wertet die Aufrufparameter aus und startet entsprechend."""

    parser = argparse.ArgumentParser(
        prog="ai-orb",
        description="Startet den Kern von AI-Orb.",
    )
    parser.add_argument(
        "--launcher",
        action="store_true",
        help="Mit Startprüfung und Dienstüberwachung starten.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Nur die Startprüfung ausführen und beenden.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Die Fassung ausgeben und beenden.",
    )

    arguments = parser.parse_args(argv)

    if arguments.version:
        print(__version__)
        return 0

    if arguments.check:
        return run_check()

    if not _acquire_single_instance():
        message = "AI-Orb läuft bereits; der zweite Start wurde beendet."
        logger.warning(message)
        print(message, flush=True)
        return 0

    if arguments.launcher:
        return run_with_launcher()

    return run_plain()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        # Ein gewolltes Beenden – durchreichen, nicht als Absturz behandeln.
        raise
    except BaseException:  # noqa: BLE001 - der letzte Fangnetz vor dem Absturz.
        # Jeder sonst unbehandelte Fehler führte bisher zu einem stummen
        # „Der Kern wurde unerwartet beendet (Code 1)". Hier wird der
        # tatsächliche Grund festgehalten, bevor der Prozess endet – in der
        # Fehlerausgabe für den Ladebildschirm und in logs/kern-crash.log
        # zum Nachlesen.
        _report_fatal(
            "Der Kern von AI-Orb ist beim Start abgestürzt.",
            traceback.format_exc(),
        )
        sys.exit(1)
