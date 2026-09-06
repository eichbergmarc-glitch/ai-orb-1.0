"""Zentrale Pfadauflösung für das AI-Orb Backend.

Alle Module, die auf Dateien zugreifen, verwenden ausschließlich die
Funktionen dieses Moduls. Dadurch wird an genau einer Stelle entschieden,
wo etwas liegt – und diese Entscheidung ist für eine installierte
Anwendung eine andere als für ein Projektverzeichnis.

**Programmdateien und Benutzerdaten sind getrennt.** Das ist keine
Ordnungsliebe, sondern Voraussetzung für dreierlei: Ein Update darf das
Programm ersetzen, ohne Erinnerungen zu löschen. Eine Deinstallation muss
zwischen „Programm entfernen" und „Benutzerdaten löschen" unterscheiden
können. Und unter ``C:\\Program Files`` darf ein gewöhnliches Programm
ohnehin nicht schreiben.

Daraus ergeben sich zwei Orte:

* **Programmordner** – der Ort, an dem AI-Orb installiert ist. Wird nur
  gelesen.
* **Benutzerordner** – ``%APPDATA%\\AI-Orb`` unter Windows. Dort liegen
  Konfiguration, Gedächtnis, Protokolle, Modelle und alles andere, was
  entsteht, während man AI-Orb benutzt.

Im Entwicklungsbetrieb – also wenn AI-Orb aus dem Quellverzeichnis läuft –
bleibt alles im Projektordner. Sonst müsste man beim Entwickeln ständig
zwischen zwei Orten hin- und herspringen. Erkannt wird das daran, ob eine
Datei ``.entwicklung`` neben ``config.yaml`` liegt oder ob die
Umgebungsvariable ``AI_ORB_PORTABLE`` gesetzt ist.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

#: Name des Anwendungsordners unterhalb von %APPDATA%.
APP_FOLDER_NAME = "AI-Orb"

#: Liegt diese Datei neben config.yaml, bleibt alles im Projektordner.
DEVELOPMENT_MARKER = ".entwicklung"

#: Diese Umgebungsvariable erzwingt den tragbaren Betrieb.
PORTABLE_ENVIRONMENT_VARIABLE = "AI_ORB_PORTABLE"

#: Diese Umgebungsvariable überschreibt den Benutzerordner vollständig.
DATA_DIRECTORY_ENVIRONMENT_VARIABLE = "AI_ORB_DATA_DIR"

#: Overrides only the log directory. Tests and diagnostics use this so their
#: synthetic events can never contaminate real runtime logs.
LOG_DIRECTORY_ENVIRONMENT_VARIABLE = "AI_ORB_LOG_DIR"

#: Unterordner, die im Benutzerordner angelegt werden.
USER_SUBDIRECTORIES: tuple[str, ...] = (
    "logs",
    "data",
    "models",
    "plugins",
    "skills",
)


def get_project_root() -> Path:
    """Gibt den Ordner zurück, in dem AI-Orb installiert ist.

    Dorthin wird nicht geschrieben. Hier liegen Programmcode, mitgelieferte
    Vorlagen und die Standardkonfiguration.
    """

    return Path(__file__).resolve().parents[2]


#: Merkt sich das Ergebnis der Schreibprobe je Ordner. Die Pfadfragen werden
#: bei jedem Protokolleintrag gestellt; die Probe muss nicht jedes Mal eine
#: Datei anfassen. Mit TTL zur automatischen Invalidierung nach 10 Minuten.
_write_probe_cache: dict[str, tuple[bool, float]] = {}
_PROBE_CACHE_TTL: float = 600.0  # 10 Minuten


def _directory_is_writable(directory: Path) -> bool:
    """Ob sich in einem Ordner tatsächlich schreiben lässt.
    
    Nutzt Caching mit TTL um wiederholte Prüfungen zu vermeiden.
    Windows beantwortet diese Frage verlässlich nur durch Ausprobieren –
    Zugriffsrechte theoretisch auszuwerten scheitert an UAC und
    Virtualisierung. Also wird kurz eine Probedatei angelegt und wieder
    entfernt.
    """
    import time
    
    key = str(directory)
    cached = _write_probe_cache.get(key)
    
    # Prüfe Cache-Gültigkeit (TTL)
    if cached is not None:
        result, timestamp = cached
        if time.time() - timestamp < _PROBE_CACHE_TTL:
            return result
        else:
            # Cache abgelaufen
            del _write_probe_cache[key]

    probe = directory / ".schreibprobe"
    try:
        probe.touch()
        probe.unlink()
        result = True
    except OSError:
        result = False

    _write_probe_cache[key] = (result, time.time())
    return result


def is_portable() -> bool:
    """Ob AI-Orb aus dem Projektordner heraus läuft.

    In diesem Fall liegen Programm und Daten zusammen – so, wie es beim
    Entwickeln praktisch ist und wie es für einen USB-Stick taugt.

    Die Entscheidung stützt sich bewusst auf mehrere Anzeichen. Die
    Kennzeichnung ``.installiert`` legt der Installer an – aber genau darauf
    allein darf man sich nicht verlassen: Fehlt sie (abgebrochene
    Installation, von Hand kopierte Ordner), hielte sich eine Installation
    unter ``C:\\Program Files`` für tragbar und versuchte, ihre Daten in den
    Programmordner zu schreiben. Windows verbietet das – und AI-Orb
    startete mit ``PermissionError`` gar nicht erst. Deshalb gilt
    zusätzlich: Wer unter ``resources\\app`` liegt, ist eine Installation,
    und wo sich nicht schreiben lässt, wird nicht geschrieben.
    """

    if os.environ.get(PORTABLE_ENVIRONMENT_VARIABLE, "").strip().lower() in {"1", "true", "ja"}:
        return True

    root = get_project_root()

    if (root / DEVELOPMENT_MARKER).exists():
        return True

    if (root / ".installiert").exists():
        return False

    # Eine von Electron installierte oder entpackte Fassung liegt immer
    # unter resources\app – auch dann, wenn die Kennzeichnung fehlt.
    if root.name.lower() == "app" and root.parent.name.lower() == "resources":
        return False

    # Geschützte Orte wie C:\Program Files sind nie tragbar.
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(variable, "").strip()
        if base:
            try:
                root.relative_to(Path(base))
                return False
            except ValueError:
                pass

    # Letzte Instanz: Nur wo sich schreiben lässt, kann tragbar gearbeitet
    # werden. Sonst gehören die Daten nach %APPDATA%.
    return _directory_is_writable(root)


def get_user_dir() -> Path:
    """Gibt den Ordner für Benutzerdaten zurück und legt ihn an.

    Unter Windows ``%APPDATA%\\AI-Orb``, sonst ``~/.config/ai-orb``. Im
    tragbaren Betrieb der Projektordner selbst.
    """

    override = os.environ.get(DATA_DIRECTORY_ENVIRONMENT_VARIABLE, "").strip()
    if override:
        directory = Path(override).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    if is_portable():
        return get_project_root()

    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", "")
        directory = Path(base) / APP_FOLDER_NAME if base else Path.home() / APP_FOLDER_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME", "")
        directory = (Path(base) if base else Path.home() / ".config") / "ai-orb"

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_cache_dir() -> Path:
    """Gibt den Ordner für Zwischengespeichertes zurück.

    Unter Windows ``%LOCALAPPDATA%\\AI-Orb\\cache``. Der Unterschied zu
    ``%APPDATA%`` ist bedeutsam: ``%APPDATA%`` wandert in Netzwerken mit dem
    Benutzerprofil mit, ``%LOCALAPPDATA%`` nicht. Sprachmodelle von einigen
    hundert Megabyte gehören deshalb hierher, Erinnerungen dagegen nicht.
    """

    if is_portable():
        directory = get_project_root() / "data" / "cache"
    elif platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", "")
        directory = (
            Path(base) / APP_FOLDER_NAME / "cache" if base else get_user_dir() / "cache"
        )
    else:
        base = os.environ.get("XDG_CACHE_HOME", "")
        directory = (Path(base) if base else Path.home() / ".cache") / "ai-orb"

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_config_path() -> Path:
    """Gibt den Pfad zur wirksamen ``config.yaml`` zurück.

    Die Reihenfolge ist wichtig: Zuerst die Fassung des Benutzers, dann die
    mitgelieferte. So überlebt eine angepasste Konfiguration jedes Update,
    und wer nie etwas geändert hat, bekommt beim Update die neuen
    Vorgabewerte.
    """

    user_config = get_user_dir() / "config.yaml"
    if user_config.is_file():
        return user_config
    return get_project_root() / "config.yaml"


def get_bundled_config_path() -> Path:
    """Gibt den Pfad zur mitgelieferten Standardkonfiguration zurück."""

    return get_project_root() / "config.yaml"


def get_env_path() -> Path:
    """Gibt den Pfad zur ``.env`` mit den Zugangsdaten zurück.

    Zugangsdaten gehören zum Benutzer, nicht zum Programm – ein Update
    darf sie nicht anfassen, eine Deinstallation nicht ungefragt löschen.
    """

    user_env = get_user_dir() / ".env"
    if user_env.is_file():
        return user_env
    return get_project_root() / ".env"


def get_logs_dir() -> Path:
    """Gibt den Ordner für Protokolldateien zurück und legt ihn an."""

    override = os.environ.get(LOG_DIRECTORY_ENVIRONMENT_VARIABLE, "").strip()
    directory = Path(override).expanduser() if override else get_user_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_data_dir() -> Path:
    """Gibt den Ordner für Anwendungsdaten zurück und legt ihn an.

    Hier liegen Gedächtnis, Wissensbasis, Knowledge Graph, Karteikarten,
    Prüfprotokoll und alles Weitere, was beim Benutzen entsteht.
    """

    directory = get_user_dir() / "data"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_models_dir() -> Path:
    """Gibt den Ordner für heruntergeladene Sprachmodelle zurück.

    Liegt im Zwischenspeicher, nicht bei den Benutzerdaten: Ein Modell ist
    jederzeit wieder herunterladbar und hat in einem wandernden
    Benutzerprofil nichts verloren.
    """

    directory = get_cache_dir() / "models"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_plugins_dir() -> Path:
    """Gibt den Ordner für Plugins des Benutzers zurück.

    Getrennt von den mitgelieferten Beispielen, damit ein Update eigene
    Plugins nicht überschreibt.
    """

    directory = get_user_dir() / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_bundled_plugins_dir() -> Path:
    """Gibt den Ordner der mitgelieferten Plugins zurück."""

    return get_project_root() / "plugins"


def get_skills_dir() -> Path:
    """Gibt den Ordner für Skills des Benutzers zurück."""

    directory = get_user_dir() / "skills"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_user_directories() -> list[Path]:
    """Legt alle Benutzerordner an.

    Wird beim ersten Start aufgerufen.

    Returns:
        Die angelegten Ordner.
    """

    created: list[Path] = []
    base = get_user_dir()

    for name in USER_SUBDIRECTORIES:
        directory = base / name
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created.append(directory)

    return created


def ensure_user_config() -> tuple[Path, bool]:
    """Stellt sicher, dass eine Konfiguration des Benutzers vorliegt.

    Beim ersten Start wird die mitgelieferte Fassung kopiert. Danach gehört
    sie dem Benutzer und wird von keinem Update mehr angefasst.

    Returns:
        Der Pfad und ob die Datei neu angelegt wurde.
    """

    if is_portable():
        return get_bundled_config_path(), False

    target = get_user_dir() / "config.yaml"
    if target.is_file():
        return target, False

    source = get_bundled_config_path()
    if not source.is_file():
        return target, False

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target, True


def migrate_from_project(*, dry_run: bool = False) -> dict[str, object]:
    """Übernimmt Daten einer früheren Installation aus dem Projektordner.

    Wer AI-Orb bisher aus dem Quellverzeichnis betrieben hat, soll bei der
    Umstellung auf die installierte Fassung sein Gedächtnis behalten. Es
    wird kopiert und nicht verschoben – bei einem Fehlschlag ist der alte
    Stand noch da.

    Args:
        dry_run: Nur prüfen, nichts kopieren.

    Returns:
        Was übernommen wurde oder würde.
    """

    if is_portable():
        return {"migrated": False, "reason": "Tragbarer Betrieb – nichts zu übernehmen."}

    project = get_project_root()
    user = get_user_dir()

    if project == user:
        return {"migrated": False, "reason": "Programm und Daten liegen am selben Ort."}

    moved: list[str] = []
    skipped: list[str] = []

    for name in ("data", "logs"):
        source = project / name
        target = user / name

        if not source.is_dir():
            continue

        # Nichts überschreiben, was am Zielort schon steht.
        for item in source.rglob("*"):
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            destination = target / relative

            if destination.exists():
                skipped.append(str(relative))
                continue

            if dry_run:
                moved.append(str(relative))
                continue

            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
                moved.append(str(relative))
            except OSError:
                skipped.append(str(relative))

    for name in ("config.yaml", ".env"):
        source = project / name
        destination = user / name
        if source.is_file() and not destination.exists():
            if dry_run:
                moved.append(name)
            else:
                try:
                    shutil.copy2(source, destination)
                    moved.append(name)
                except OSError:
                    skipped.append(name)

    return {
        "migrated": bool(moved),
        "dry_run": dry_run,
        "files": moved,
        "skipped": skipped,
        "source": str(project),
        "target": str(user),
    }


def describe() -> dict[str, str]:
    """Wo alles liegt – für die Transparenzansicht und die Fehlersuche."""

    return {
        "modus": "tragbar" if is_portable() else "installiert",
        "programm": str(get_project_root()),
        "benutzerdaten": str(get_user_dir()),
        "konfiguration": str(get_config_path()),
        "zugangsdaten": str(get_env_path()),
        "protokolle": str(get_logs_dir()),
        "daten": str(get_data_dir()),
        "zwischenspeicher": str(get_cache_dir()),
        "modelle": str(get_models_dir()),
    }
