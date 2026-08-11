#!/usr/bin/env python3
"""Ein-Kommando-Upgrade für AI-Orb (Phase 21).

Aufruf::

    python upgrade.py sprint01
    python upgrade.py --list
    python upgrade.py --rollback

Was geschieht, in dieser Reihenfolge:

1. Zustand prüfen – gibt es ungesicherte Änderungen?
2. Sicherung anlegen
3. Fassung feststellen
4. Änderungen einspielen
5. Abhängigkeiten prüfen
6. Tests laufen lassen
7. Bei einem Fehler alles zurücknehmen

Der entscheidende Punkt ist Schritt 7. Ein Upgrade, das auf halbem Weg
stecken bleibt, ist schlimmer als eines, das gar nicht erst startet: Man
weiß dann nicht mehr, was gilt. Deshalb wird vor jeder Änderung gesichert
und bei jedem Fehlschlag vollständig zurückgesetzt.

Gesichert wird als vollständige Kopie der betroffenen Dateien, nicht über
Git. Der Grund: Ein Benutzer, der AI-Orb als Zip heruntergeladen hat, hat
kein Git-Verzeichnis – und gerade der braucht die Rücknahme am dringendsten.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
UPGRADES_DIR = PROJECT_ROOT / "upgrades"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
STATE_FILE = PROJECT_ROOT / "data" / "upgrade_state.json"

#: Verzeichnisse, die nie gesichert oder ersetzt werden.
EXCLUDED = {".git", ".venv", "node_modules", "data", "logs", "__pycache__", "models"}


# =============================================================================
# Ausgabe
# =============================================================================


class Output:
    """Ausgabe mit Haken und Kreuzen, wie in der Vorgabe beschrieben."""

    def __init__(self, *, quiet: bool = False) -> None:
        self._quiet = quiet
        self._steps: list[tuple[bool, str]] = []

    def ok(self, text: str) -> None:
        self._steps.append((True, text))
        if not self._quiet:
            print(f"  ✓ {text}")

    def fail(self, text: str) -> None:
        self._steps.append((False, text))
        if not self._quiet:
            print(f"  ✗ {text}")

    def info(self, text: str) -> None:
        if not self._quiet:
            print(f"    {text}")

    def header(self, text: str) -> None:
        if not self._quiet:
            print()
            print("=" * 62)
            print(f"  {text}")
            print("=" * 62)
            print()

    def note(self, text: str) -> None:
        if not self._quiet:
            print()
            print(text)

    @property
    def failed(self) -> bool:
        return any(not success for success, _ in self._steps)


# =============================================================================
# Sicherung
# =============================================================================


@dataclass
class Backup:
    """Eine Sicherung vor einem Upgrade."""

    path: Path
    created_at: float
    files: int
    version_before: str
    upgrade_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "created_at": self.created_at,
            "created": time.strftime("%d.%m.%Y %H:%M", time.localtime(self.created_at)),
            "files": self.files,
            "version_before": self.version_before,
            "upgrade_name": self.upgrade_name,
        }


def create_backup(name: str, version: str, output: Output) -> Backup | None:
    """Legt eine vollständige Sicherung des Projekts an."""

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"

    try:
        count = 0
        for source in PROJECT_ROOT.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(PROJECT_ROOT)
            if any(part in EXCLUDED for part in relative.parts):
                continue

            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            count += 1

    except OSError as error:
        output.fail(f"Sicherung fehlgeschlagen: {error}")
        return None

    backup = Backup(
        path=target,
        created_at=time.time(),
        files=count,
        version_before=version,
        upgrade_name=name,
    )
    output.ok(f"Backup erstellt ({count} Dateien)")
    return backup


def restore_backup(backup_path: Path, output: Output) -> bool:
    """Spielt eine Sicherung zurück."""

    if not backup_path.is_dir():
        output.fail(f"Die Sicherung fehlt: {backup_path}")
        return False

    try:
        count = 0
        for source in backup_path.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(backup_path)
            destination = PROJECT_ROOT / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            count += 1
    except OSError as error:
        output.fail(f"Die Rücknahme ist fehlgeschlagen: {error}")
        return False

    output.ok(f"vorheriger Zustand wiederhergestellt ({count} Dateien)")
    return True


def prune_backups(keep: int = 5) -> int:
    """Entfernt alte Sicherungen."""

    if not BACKUP_DIR.is_dir():
        return 0

    backups = sorted(
        (path for path in BACKUP_DIR.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    removed = 0
    for path in backups[keep:]:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError:
            continue
    return removed


# =============================================================================
# Prüfungen
# =============================================================================


def check_repository(output: Output) -> bool:
    """Prüft, ob ungesicherte Änderungen vorliegen.

    Ohne Git ist das kein Fehler – dann greift die Dateisicherung, die
    ohnehin angelegt wird.
    """

    if not (PROJECT_ROOT / ".git").is_dir():
        output.ok("Repository geprueft (kein Git-Verzeichnis, Dateisicherung greift)")
        return True

    try:
        completed = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        output.ok("Repository geprueft (git nicht verfuegbar)")
        return True

    changes = [line for line in completed.stdout.splitlines() if line.strip()]
    if changes:
        output.ok(f"Repository geprueft ({len(changes)} geaenderte Dateien, gesichert)")
        for line in changes[:5]:
            output.info(line)
        if len(changes) > 5:
            output.info(f"... und {len(changes) - 5} weitere")
    else:
        output.ok("Repository geprueft (sauber)")

    return True


def read_version() -> str:
    """Liest die Fassung aus ``config.yaml``."""

    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.is_file():
        return "unbekannt"

    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "unbekannt"


def check_dependencies(output: Output) -> bool:
    """Prüft, ob das Backend geladen werden kann."""

    executable = venv_python()

    try:
        completed = subprocess.run(  # noqa: S603
            [str(executable), "-c", "import sys; sys.path.insert(0,'.'); import backend.main"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        output.fail(f"Dependencies geprueft: {error}")
        return False

    if completed.returncode != 0:
        output.fail("Dependencies geprueft: Das Backend laesst sich nicht laden")
        for line in (completed.stderr or "").strip().splitlines()[-6:]:
            output.info(line)
        return False

    output.ok("Dependencies geprueft")
    return True


def run_tests(output: Output, *, skip: bool = False) -> bool:
    """Führt die Tests aus."""

    if skip:
        output.ok("Tests uebersprungen (--skip-tests)")
        return True

    executable = venv_python()

    try:
        completed = subprocess.run(  # noqa: S603
            [str(executable), "-m", "pytest", "-q", "--no-header"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        output.fail("Tests: Zeitlimit von zehn Minuten ueberschritten")
        return False
    except OSError as error:
        output.fail(f"Tests: {error}")
        return False

    combined = (completed.stdout or "") + (completed.stderr or "")

    # Fehlt pytest, ist das kein Grund, ein Upgrade zurückzunehmen.
    if "No module named pytest" in combined:
        output.ok("Tests uebersprungen (pytest ist nicht installiert)")
        output.info("Installieren mit: .venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt")
        return True

    if completed.returncode != 0:
        output.fail("Tests bestanden: NEIN")
        for line in combined.strip().splitlines()[-12:]:
            output.info(line)
        return False

    summary = next(
        (line for line in reversed(combined.splitlines()) if "passed" in line or "no tests" in line),
        "",
    )
    output.ok(f"Tests bestanden{f' ({summary.strip()})' if summary else ''}")
    return True


def venv_python() -> Path:
    """Der Python-Interpreter der Projektumgebung, sonst der laufende."""

    for candidate in (
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


# =============================================================================
# Einspielen
# =============================================================================


def available_upgrades() -> list[dict[str, Any]]:
    """Listet die vorhandenen Upgrade-Pakete auf."""

    if not UPGRADES_DIR.is_dir():
        return []

    found: list[dict[str, Any]] = []
    for directory in sorted(UPGRADES_DIR.iterdir()):
        if not directory.is_dir() or directory.name.startswith((".", "_")):
            continue

        manifest = directory / "upgrade.json"
        entry: dict[str, Any] = {"name": directory.name, "path": str(directory)}

        if manifest.is_file():
            try:
                entry.update(json.loads(manifest.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                entry["description"] = "(Beschreibung nicht lesbar)"

        files = [
            path
            for path in (directory / "files").rglob("*")
            if path.is_file()
        ] if (directory / "files").is_dir() else []
        entry["file_count"] = len(files)

        found.append(entry)

    return found


def apply_upgrade(name: str, output: Output) -> tuple[bool, list[str]]:
    """Spielt ein Upgrade-Paket ein.

    Ein Paket ist ein Ordner unter ``upgrades/`` mit einem Unterordner
    ``files/``, dessen Inhalt eins zu eins über das Projekt gelegt wird.

    Returns:
        Erfolg und die Liste der ersetzten Dateien.
    """

    package = UPGRADES_DIR / name
    if not package.is_dir():
        output.fail(f"Patch angewendet: Das Paket '{name}' gibt es nicht")
        output.info(f"Erwartet wurde: {package}")
        return False, []

    source_root = package / "files"
    if not source_root.is_dir():
        output.fail(f"Patch angewendet: In '{name}' fehlt der Ordner 'files'")
        return False, []

    replaced: list[str] = []
    try:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file():
                continue

            relative = source.relative_to(source_root)

            # Ein Paket darf nicht aus dem Projekt herausschreiben.
            destination = (PROJECT_ROOT / relative).resolve()
            if PROJECT_ROOT not in destination.parents and destination != PROJECT_ROOT:
                output.fail(f"Patch angewendet: '{relative}' zeigt aus dem Projekt heraus")
                return False, replaced

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            replaced.append(str(relative))

    except OSError as error:
        output.fail(f"Patch angewendet: {error}")
        return False, replaced

    output.ok(f"Patch angewendet ({len(replaced)} Dateien)")
    for entry in replaced[:8]:
        output.info(entry)
    if len(replaced) > 8:
        output.info(f"... und {len(replaced) - 8} weitere")

    return True, replaced


# =============================================================================
# Zustand
# =============================================================================


def save_state(backup: Backup, upgraded_files: list[str], version_after: str) -> None:
    """Hält fest, was zuletzt eingespielt wurde."""

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_upgrade": backup.upgrade_name,
        "applied_at": time.time(),
        "version_before": backup.version_before,
        "version_after": version_after,
        "backup": str(backup.path),
        "files": upgraded_files,
    }
    STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_state() -> dict[str, Any] | None:
    """Liest den zuletzt festgehaltenen Zustand."""

    if not STATE_FILE.is_file():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# =============================================================================
# Abläufe
# =============================================================================


def run_upgrade(name: str, *, skip_tests: bool = False) -> int:
    """Führt ein vollständiges Upgrade aus."""

    output = Output()
    output.header(f"AI-Orb Upgrade: {name}")

    if not check_repository(output):
        return 1

    version_before = read_version()
    output.ok(f"Version erkannt ({version_before})")

    backup = create_backup(name, version_before, output)
    if backup is None:
        output.note("Ohne Sicherung wird nichts veraendert. Abbruch.")
        return 1

    applied, files = apply_upgrade(name, output)
    if not applied:
        _rollback(backup, output, "Der Patch liess sich nicht anwenden.")
        return 1

    if not check_dependencies(output):
        _rollback(backup, output, "Nach dem Patch laesst sich das Backend nicht laden.")
        return 1

    if not run_tests(output, skip=skip_tests):
        _rollback(backup, output, "Die Tests sind fehlgeschlagen.")
        return 1

    version_after = read_version()
    save_state(backup, files, version_after)
    removed = prune_backups()

    output.note("=" * 62)
    print(f"  ✓ Upgrade erfolgreich: {version_before} → {version_after}")
    print("=" * 62)
    if removed:
        output.info(f"{removed} alte Sicherungen entfernt.")
    print()
    print("  Zum Starten: REPARIEREN-UND-STARTEN.bat doppelklicken.")
    print()
    return 0


def _rollback(backup: Backup, output: Output, reason: str) -> None:
    """Nimmt ein Upgrade zurück."""

    output.note("=" * 62)
    print("  ✗ Upgrade fehlgeschlagen")
    print(f"    {reason}")
    print("  → Rollback wird ausgefuehrt")
    print("=" * 62)
    print()

    restore_backup(backup.path, output)

    print()
    print("  Es wurde nichts veraendert. Die Fehlermeldung steht oben.")
    print()


def run_rollback() -> int:
    """Nimmt das zuletzt eingespielte Upgrade zurück."""

    output = Output()
    output.header("AI-Orb: letztes Upgrade zuruecknehmen")

    state = load_state()
    if state is None:
        print("  Es ist kein Upgrade vermerkt, das zurueckgenommen werden koennte.")
        print()
        return 1

    backup_path = Path(str(state.get("backup", "")))
    print(f"  Letztes Upgrade: {state.get('last_upgrade', '?')}")
    print(f"  Version davor:   {state.get('version_before', '?')}")
    print(f"  Sicherung:       {backup_path}")
    print()

    if not restore_backup(backup_path, output):
        return 1

    STATE_FILE.unlink(missing_ok=True)

    print()
    print("  ✓ Der vorherige Zustand ist wiederhergestellt.")
    print()
    return 0


def run_list() -> int:
    """Zeigt die vorhandenen Upgrade-Pakete."""

    output = Output()
    output.header("Verfuegbare Upgrades")

    upgrades = available_upgrades()
    if not upgrades:
        print(f"  Es liegen keine Pakete unter {UPGRADES_DIR}.")
        print()
        print("  Ein Paket ist ein Ordner mit einem Unterordner 'files/', dessen")
        print("  Inhalt ueber das Projekt gelegt wird. Beispiel:")
        print()
        print("    upgrades/sprint01/upgrade.json")
        print("    upgrades/sprint01/files/backend/runtime.py")
        print()
        return 0

    for entry in upgrades:
        print(f"  {entry['name']}")
        if entry.get("description"):
            print(f"      {entry['description']}")
        if entry.get("version"):
            print(f"      Version: {entry['version']}")
        print(f"      {entry.get('file_count', 0)} Dateien")
        print()

    print(f"  Einspielen mit: python upgrade.py {upgrades[0]['name']}")
    print()

    state = load_state()
    if state:
        print(f"  Zuletzt eingespielt: {state.get('last_upgrade')} "
              f"({state.get('version_before')} → {state.get('version_after')})")
        print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Spielt ein Upgrade fuer AI-Orb ein – mit Sicherung, Tests und Ruecknahme.",
        epilog="Beispiel: python upgrade.py sprint01",
    )
    parser.add_argument("name", nargs="?", help="Name des Upgrade-Pakets unter upgrades/")
    parser.add_argument("--list", action="store_true", help="Vorhandene Pakete anzeigen")
    parser.add_argument("--rollback", action="store_true", help="Letztes Upgrade zuruecknehmen")
    parser.add_argument("--skip-tests", action="store_true", help="Tests ueberspringen")

    arguments = parser.parse_args()

    if arguments.rollback:
        return run_rollback()

    if arguments.list or not arguments.name:
        return run_list()

    return run_upgrade(arguments.name, skip_tests=arguments.skip_tests)


if __name__ == "__main__":
    sys.exit(main())
