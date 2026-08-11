"""Sichere Desktop-Steuerung unter Windows (und plattformübergreifend).

Dieses Modul ist die **einzige** Stelle im Backend, die Programme startet
oder Dateien öffnet. Der Orchestrator führt niemals selbst Systembefehle
aus (Sicherheitsvorgabe), sondern ruft ausschließlich die hier definierten
Funktionen auf.

Zwei Schutzmechanismen sind fest eingebaut:

1. **Allowlist**: Es werden ausschließlich Programme gestartet, die in
   ``config.yaml`` unter ``desktop.applications`` hinterlegt sind. Freie
   Kommandozeilen aus Benutzereingaben werden nicht ausgeführt.
2. **Bestätigungspflicht**: Aktionen, die als riskant eingestuft sind
   (z. B. das Beenden von Programmen), liefern eine Rückfrage statt sie
   sofort auszuführen.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ActionResult:
    """Ergebnis einer Desktop-Aktion."""

    success: bool
    message: str
    requires_confirmation: bool = False
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "requires_confirmation": self.requires_confirmation,
            "details": self.details or {},
        }


class DesktopControl:
    """Führt kontrollierte Desktop-Aktionen aus."""

    def __init__(self) -> None:
        config = get_config()
        self._config = config
        self._desktop_config = config.section("desktop")
        self._applications: dict[str, Any] = dict(self._desktop_config.get("applications", {}) or {})
        self._allow_close = bool(self._desktop_config.get("allow_process_termination", False))
        self._search_roots = [
            Path(os.path.expandvars(os.path.expanduser(str(root))))
            for root in (self._desktop_config.get("file_search_roots", []) or [])
        ]
        self._is_windows = platform.system() == "Windows"

    # --- Programme --------------------------------------------------------------

    @property
    def known_applications(self) -> list[str]:
        """Namen aller freigegebenen Programme."""

        return sorted(self._applications)

    def resolve_application(self, name: str) -> dict[str, Any] | None:
        """Sucht ein freigegebenes Programm anhand seines Namens oder Alias."""

        needle = name.strip().lower()
        for key, entry in self._applications.items():
            if key.lower() == needle:
                return {"key": key, **self._normalize_entry(entry)}
            aliases = [str(alias).lower() for alias in (self._normalize_entry(entry).get("aliases") or [])]
            if needle in aliases:
                return {"key": key, **self._normalize_entry(entry)}
        return None

    def find_in_text(self, text: str) -> list[str]:
        """Findet freigegebene Programme, die in einem Satz genannt werden.

        Durchsucht den Satz nach Programmnamen UND ihren Aliasen. Der
        frühere Weg prüfte nur die Namen – „öffne den Editor“ blieb deshalb
        wirkungslos, weil „Editor“ nur ein Alias von „notepad“ ist und
        „notepad“ im Satz nicht vorkam.

        Längere Treffer gewinnen: „visual studio code“ soll nicht an „code“
        hängenbleiben, und „windows terminal“ nicht am bloßen „terminal“.

        Returns:
            Die kanonischen Programmnamen, längster Treffer zuerst.
        """

        lowered = f" {text.lower()} "
        treffer: list[tuple[int, str]] = []

        for key, entry in self._applications.items():
            normalized = self._normalize_entry(entry)
            # Der Name selbst und alle Aliase sind gültige Suchbegriffe.
            candidates = [key.lower()] + [
                str(alias).lower() for alias in (normalized.get("aliases") or [])
            ]
            best = 0
            for candidate in candidates:
                # Auf Wortgrenzen achten, damit „code“ nicht in „Rekorder“
                # oder „Dekodieren“ anschlägt.
                if f" {candidate} " in lowered or f" {candidate}." in lowered or f" {candidate}," in lowered:
                    best = max(best, len(candidate))
            if best:
                treffer.append((best, key))

        treffer.sort(reverse=True)
        return [key for _, key in treffer]

    @staticmethod
    def _normalize_entry(entry: Any) -> dict[str, Any]:
        """Erlaubt sowohl Kurzform (String) als auch Langform (Mapping)."""

        if isinstance(entry, str):
            return {"command": entry, "aliases": [], "args": []}
        if isinstance(entry, dict):
            return {
                "command": str(entry.get("command", "")),
                "aliases": list(entry.get("aliases", []) or []),
                "args": [str(arg) for arg in (entry.get("args", []) or [])],
            }
        return {"command": "", "aliases": [], "args": []}

    def launch(self, name: str) -> ActionResult:
        """Startet ein freigegebenes Programm.

        Args:
            name: Name oder Alias des Programms, wie in ``config.yaml``
                unter ``desktop.applications`` hinterlegt.

        Returns:
            Das Ergebnis der Aktion. Unbekannte Programme werden nicht
            gestartet, sondern mit einer erklärenden Meldung abgelehnt.
        """

        entry = self.resolve_application(name)
        if entry is None:
            # Nicht in der Liste – im offenen Modus ist das kein Nein.
            #
            # Die Liste in config.yaml kennt acht Programme. Wer den Orb als
            # Assistenten benutzt, will aber jedes Programm starten können,
            # das auf seinem Rechner liegt, ohne es vorher eintragen zu
            # müssen. Im offenen Modus wird deshalb versucht, den Namen
            # selbst aufzulösen; nur wenn auch das misslingt, gibt es ein
            # Nein – und dann eines, das den Grund nennt.
            if self._open_mode():
                return self._launch_unlisted(name)

            return ActionResult(
                success=False,
                message=(
                    f"'{name}' ist nicht freigegeben. Freigegebene Programme: "
                    + (", ".join(self.known_applications) or "(keine)")
                ),
                details={"known": self.known_applications},
            )

        command = str(entry.get("command", "")).strip()
        if not command:
            return ActionResult(success=False, message=f"Für '{name}' ist kein Befehl hinterlegt.")

        expanded = os.path.expandvars(os.path.expanduser(command))
        executable = (
            shutil.which(expanded)
            or (expanded if Path(expanded).exists() else None)
            # Der Windows-Weg fuer Programme ausserhalb des Suchpfads.
            or self._resolve_via_app_paths(expanded)
        )
        if executable is None:
            # Ein Eintrag, dessen Programm sich nicht aufloesen laesst, ist
            # kein Grund aufzugeben: Windows selbst findet es womoeglich
            # trotzdem. Frueher endete es hier mit „nicht gefunden", obwohl
            # das Programm installiert war.
            if self._open_mode():
                ergebnis = self._launch_unlisted(command)
                if ergebnis.success:
                    return ergebnis
            logger.warning(
                "Programm '%s' nicht gefunden (Befehl '%s'). Gesucht wurde im "
                "Suchpfad, als Dateipfad und in der Windows-Registrierung.",
                name, command,
            )
            return ActionResult(
                success=False,
                message=f"Programm '{name}' wurde auf diesem System nicht gefunden ({command}).",
            )

        argv = [executable, *entry.get("args", [])]
        try:
            creation_flags = 0
            if self._is_windows:
                # Startet das Programm losgelöst, damit AI-Orb nicht blockiert
                # und das Fenster des Programms eigenständig bleibt.
                creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            prozess = subprocess.Popen(  # noqa: S603 - argv stammt ausschließlich aus der Allowlist.
                argv,
                creationflags=creation_flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            self._nach_vorn(prozess.pid)
        except OSError as error:
            logger.exception("Start von '%s' fehlgeschlagen.", name)
            return ActionResult(success=False, message=f"Start fehlgeschlagen: {error}")

        logger.info("Programm gestartet: %s (%s)", entry["key"], executable)
        return ActionResult(
            success=True,
            message=f"{entry['key']} wurde gestartet.",
            details={"executable": executable},
        )

    def _nach_vorn(self, pid: int) -> None:
        """Holt das Fenster eines frisch gestarteten Prozesses in den Vordergrund.

        Der Benutzer sah neue Fenster im Hintergrund erscheinen. Grund:
        Ein losgelöst gestartetes Programm (``DETACHED_PROCESS``) bekommt
        von Windows nicht automatisch den Vordergrund. Das wird hier
        nachgeholt – in einem eigenen Faden, damit der Start nicht wartet.

        Nur auf Windows, und nur, wenn es eingeschaltet ist: Wer den Orb
        etwas im Hintergrund vorbereiten lässt, während er weiterarbeitet,
        will nicht, dass ihm das Fenster vor die Nase springt.
        """

        if not self._is_windows:
            return
        if not bool(self._config.get("desktop.fenster_in_vordergrund", True)):
            return
        try:
            from backend.system.vordergrund import in_den_vordergrund

            in_den_vordergrund(pid)
        except Exception:  # noqa: BLE001 - der Vordergrund ist Kür, kein Muss.
            logger.debug("Das Fenster liess sich nicht nach vorn holen.", exc_info=True)

    @staticmethod
    def _resolve_via_app_paths(command: str) -> str | None:
        """Sucht ein Programm dort, wo Windows es fuehrt.

        Der Grund fuer diese Methode: ``shutil.which`` durchsucht nur den
        Suchpfad (PATH). Viele Windows-Programme stehen dort NICHT – Edge
        etwa liegt unter ``Program Files`` und wird ueber den
        Registrierungsschluessel „App Paths" aufgeloest. Genau daran
        scheiterte „oeffne Edge": Der Eintrag war da, das Programm war
        installiert, und trotzdem hiess es „nicht gefunden" – weil an der
        falschen Stelle gesucht wurde.
        """

        if os.name != "nt":
            return None

        name = Path(command).name
        if not name.lower().endswith(".exe"):
            name += ".exe"

        try:
            import winreg
        except ImportError:  # pragma: no cover - nur auf Windows vorhanden.
            return None

        schluessel = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}"
        for wurzel in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(wurzel, schluessel) as key:
                    pfad, _typ = winreg.QueryValueEx(key, "")
            except OSError:
                continue
            pfad = str(pfad).strip().strip('"')
            if pfad and Path(pfad).exists():
                return pfad
        return None

    @staticmethod
    def _open_mode() -> bool:
        """Ob die Sicherheitsschicht im offenen Modus läuft."""

        try:
            from backend.config import get_config

            return str(get_config().get("security.mode", "")).strip().lower() in {
                "offen", "open", "frei"
            }
        except Exception:  # noqa: BLE001 - im Zweifel die vorsichtige Antwort.
            return False

    #: Geläufige deutsche Namen und wie das Programm wirklich heißt.
    _COMMON_NAMES: dict[str, str] = {
        "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
        "outlook": "outlook", "rechner": "calc", "taschenrechner": "calc",
        "editor": "notepad", "texteditor": "notepad", "schreibblock": "notepad",
        "paint": "mspaint", "malen": "mspaint", "zeichnen": "mspaint",
        "edge": "msedge", "microsoft edge": "msedge", "browser": "msedge",
        "terminal": "wt", "eingabeaufforderung": "cmd", "konsole": "cmd",
        "powershell": "powershell", "kommandozeile": "cmd",
        "internet": "msedge", "firefox": "firefox", "chrome": "chrome",
        "einstellungen": "ms-settings:", "systemsteuerung": "control",
        "aufgabenmanager": "taskmgr", "taskmanager": "taskmgr",
        "dateien": "explorer", "dateimanager": "explorer", "ordner": "explorer",
        "musik": "spotify", "kamera": "microsoft.windows.camera:",
    }

    def _launch_unlisted(self, name: str) -> ActionResult:
        """Startet ein Programm, das nicht in der Freigabeliste steht.

        Drei Wege, vom Genauen zum Allgemeinen:

        1. Ein geläufiger deutscher Name wird übersetzt („Word" → winword).
        2. Liegt eine ausführbare Datei dieses Namens im Suchpfad, wird sie
           gestartet.
        3. Sonst übernimmt Windows selbst: ``start`` findet auch Programme,
           die nur in der Registrierung stehen (Spotify, Office und die
           meisten installierten Anwendungen) sowie Systemeinstellungen.
        """

        wanted = name.strip().strip('"')
        if not wanted:
            return ActionResult(success=False, message="Es fehlt der Programmname.")

        target = self._COMMON_NAMES.get(wanted.lower(), wanted)

        # Weg 2: eine ausführbare Datei im Suchpfad oder in der Registrierung.
        executable = shutil.which(target) or self._resolve_via_app_paths(target)
        if executable is not None:
            try:
                flags = 0
                if self._is_windows:
                    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                    )
                prozess = subprocess.Popen(  # noqa: S603 - der Benutzer hat den offenen Modus gewählt.
                    [executable],
                    creationflags=flags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                self._nach_vorn(prozess.pid)
            except OSError as error:
                return ActionResult(success=False, message=f"Start fehlgeschlagen: {error}")

            logger.info("Programm gestartet (nicht gelistet): %s", executable)
            return ActionResult(
                success=True,
                message=f"{wanted} wurde gestartet.",
                details={"executable": executable, "gelistet": False},
            )

        # Weg 3: Windows selbst suchen lassen.
        if self._is_windows:
            try:
                subprocess.Popen(  # noqa: S603 - siehe oben.
                    ["cmd", "/c", "start", "", target],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except OSError as error:
                return ActionResult(success=False, message=f"Start fehlgeschlagen: {error}")

            logger.info("Programm über Windows gestartet: %s", target)
            return ActionResult(
                success=True,
                message=f"{wanted} wurde gestartet.",
                details={"ziel": target, "gelistet": False, "weg": "windows-start"},
            )

        return ActionResult(
            success=False,
            message=(
                f"'{wanted}' wurde auf diesem System nicht gefunden. Prüfe die "
                "Schreibweise, oder nenne den genauen Programmnamen."
            ),
        )

    def close(self, name: str, *, confirmed: bool = False) -> ActionResult:
        """Beendet ein laufendes Programm.

        Das Beenden von Programmen kann zu Datenverlust führen und gilt
        daher als riskante Aktion: Ohne ausdrückliche Bestätigung wird die
        Aktion nicht ausgeführt. Zusätzlich muss sie in ``config.yaml``
        über ``desktop.allow_process_termination`` freigeschaltet sein.
        """

        if not self._allow_close:
            return ActionResult(
                success=False,
                message=(
                    "Das Beenden von Programmen ist deaktiviert. Du kannst es in "
                    "config.yaml unter desktop.allow_process_termination aktivieren."
                ),
            )

        entry = self.resolve_application(name)
        if entry is None:
            return ActionResult(success=False, message=f"'{name}' ist nicht freigegeben.")

        if not confirmed:
            return ActionResult(
                success=False,
                requires_confirmation=True,
                message=f"Soll ich {entry['key']} wirklich beenden? Nicht gespeicherte Daten gehen möglicherweise verloren.",
                details={"action": "close", "target": entry["key"]},
            )

        process_name = Path(str(entry.get("command", ""))).name
        if not process_name:
            return ActionResult(success=False, message="Kein Prozessname ermittelbar.")

        try:
            if self._is_windows:
                subprocess.run(  # noqa: S603 - Prozessname stammt aus der Allowlist.
                    ["taskkill", "/IM", process_name, "/F"],
                    check=False,
                    capture_output=True,
                )
            else:
                subprocess.run(["pkill", "-f", process_name], check=False, capture_output=True)  # noqa: S603, S607
        except OSError as error:
            return ActionResult(success=False, message=f"Beenden fehlgeschlagen: {error}")

        logger.info("Programm beendet: %s", process_name)
        return ActionResult(success=True, message=f"{entry['key']} wurde beendet.")

    # --- Dateien ------------------------------------------------------------------

    def open_url(self, url: str) -> ActionResult:
        """Öffnet eine Internetadresse im Standardbrowser.

        Der Weg über ``webbrowser`` funktioniert auf jedem System und
        benutzt den Browser, den der Benutzer als Standard eingerichtet
        hat – niemand will, dass der Orb ihm einen anderen aufdrängt.
        """

        address = url.strip()
        if not address:
            return ActionResult(success=False, message="Es fehlt die Adresse.")
        if not address.startswith(("http://", "https://")):
            address = "https://" + address

        try:
            import webbrowser

            opened = webbrowser.open(address, new=2)
        except Exception as error:  # noqa: BLE001 - eine Meldung ist besser als ein Absturz.
            return ActionResult(success=False, message=f"Browser nicht startbar: {error}")

        if not opened:
            return ActionResult(success=False, message="Es wurde kein Browser gefunden.")
        return ActionResult(success=True, message=f"Im Browser geöffnet: {address}")

    def open_path(self, path: str) -> ActionResult:
        """Öffnet eine Datei oder einen Ordner mit dem Standardprogramm."""

        target = Path(os.path.expandvars(os.path.expanduser(path)))
        if not target.exists():
            return ActionResult(success=False, message=f"Nicht gefunden: {target}")

        try:
            if self._is_windows:
                os.startfile(str(target))  # type: ignore[attr-defined]  # noqa: S606 - Windows-Standardöffnen
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(target)])  # noqa: S603, S607
            else:
                subprocess.Popen(["xdg-open", str(target)])  # noqa: S603, S607
        except OSError as error:
            return ActionResult(success=False, message=f"Öffnen fehlgeschlagen: {error}")

        return ActionResult(success=True, message=f"Geöffnet: {target.name}")

    def find_files(self, pattern: str, *, limit: int = 20) -> ActionResult:
        """Sucht Dateien in den in ``config.yaml`` freigegebenen Verzeichnissen.

        Es wird ausschließlich in ``desktop.file_search_roots`` gesucht;
        ein Zugriff auf beliebige Systempfade findet nicht statt.
        """

        if not self._search_roots:
            return ActionResult(
                success=False,
                message=(
                    "Es sind keine Suchverzeichnisse freigegeben. Trage sie in "
                    "config.yaml unter desktop.file_search_roots ein."
                ),
            )

        needle = pattern.strip().lower()
        if not needle:
            return ActionResult(success=False, message="Kein Suchbegriff angegeben.")

        matches: list[str] = []
        for root in self._search_roots:
            if not root.exists():
                continue
            try:
                for candidate in root.rglob("*"):
                    if len(matches) >= limit:
                        break
                    if candidate.is_file() and needle in candidate.name.lower():
                        matches.append(str(candidate))
            except (PermissionError, OSError):
                logger.debug("Verzeichnis nicht lesbar: %s", root)
            if len(matches) >= limit:
                break

        if not matches:
            return ActionResult(success=False, message=f"Keine Datei gefunden, die zu '{pattern}' passt.")

        return ActionResult(
            success=True,
            message=f"{len(matches)} Treffer gefunden.",
            details={"matches": matches},
        )

    # --- Systemstatus ---------------------------------------------------------------

    def system_status(self) -> dict[str, Any]:
        """Liefert grundlegende Systeminformationen ohne Zusatzbibliotheken."""

        usage = shutil.disk_usage(str(Path.home()))
        return {
            "platform": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "disk_total_gb": round(usage.total / 1024**3, 1),
            "disk_free_gb": round(usage.free / 1024**3, 1),
        }
