"""Sichtbare CMD- und PowerShell-Fenster kontrolliert starten.

Das Modul trifft keine Berechtigungsentscheidung. Es wird ausschliesslich
von Werkzeugen aufgerufen, deren Ausfuehrung vorher durch die zentrale
Sicherheitsschicht gegangen ist.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TerminalRequest:
    """Ein lokal erkannter Terminalauftrag aus Sprache oder Chat."""

    shell: str
    command: str = ""


_SHELL_WORDS = {
    "powershell": "powershell",
    "power shell": "powershell",
    "cmd": "cmd",
    "cmd.exe": "cmd",
    "eingabeaufforderung": "cmd",
    "kommandozeile": "cmd",
}


def parse_terminal_request(text: str) -> TerminalRequest | None:
    """Erkennt ausdrueckliche Auftraege fuer CMD oder PowerShell.

    Nur Saetze mit genanntem Shelltyp und einer Handlungsabsicht werden
    erkannt. Eine Erklaerfrage ueber PowerShell bleibt dadurch eine normale
    Frage. Befehle in Anfuehrungszeichen haben Vorrang; danach folgen die
    gesprochenen Formen "Befehl X ausfuehren" und "gib X ein".
    """

    raw = " ".join((text or "").strip().split())
    lowered = raw.lower()
    shell = ""
    for marker, value in _SHELL_WORDS.items():
        if re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", lowered):
            shell = value
            break
    if not shell:
        return None

    action = re.search(
        r"\b(oeffne|öffne|starte|starten|ausfuehren|ausführen|fuehre|führe|"
        r"gib|tippe|schreib|schreibe|benutze|nutze)\b",
        lowered,
    )
    if action is None:
        return None

    command = ""
    quoted = re.search(r"`([^`]+)`", raw)
    if quoted is None:
        quoted = re.search(
            r"\b(?:befehl|kommando|fuehre|führe)\s+[\"']([^\"']+)[\"']",
            raw,
            flags=re.IGNORECASE,
        )
    if quoted:
        command = quoted.group(1).strip()

    if not command:
        patterns = (
            r"\b(?:fuehre|führe)\s+(?:dort\s+|in\s+(?:der\s+)?(?:powershell|power shell|cmd|eingabeaufforderung)\s+)?(?:den\s+)?(?:befehl\s+)?(.+?)\s+aus\b",
            r"\b(?:befehl|kommando)\s+(.+?)\s+(?:ausfuehren|ausführen|aus)\b",
            r"\b(?:gib|tippe|schreib|schreibe)\s+(?:dort\s+|in\s+(?:der\s+)?(?:powershell|power shell|cmd|eingabeaufforderung)\s+)?(.+?)\s+(?:ein|hinein)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if match:
                command = match.group(1).strip(" .")
                break

    # Diese Woerter sind Platzhalter, kein tatsaechlicher Befehl.
    if command.lower() in {"einen befehl", "den befehl", "befehl", "etwas"}:
        command = ""
    command = re.sub(
        r"\s+in\s+(?:der\s+)?(?:powershell|power shell|cmd|eingabeaufforderung)$",
        "",
        command,
        flags=re.IGNORECASE,
    ).strip()
    return TerminalRequest(shell=shell, command=command)


class TerminalControl:
    """Oeffnet eine sichtbare Windows-Shell, optional mit Startbefehl."""

    def __init__(self) -> None:
        self._is_windows = os.name == "nt"

    @staticmethod
    def _normalize_shell(shell: str) -> str:
        normalized = str(shell).strip().lower().replace(".exe", "")
        if normalized in {"powershell", "power shell", "pwsh"}:
            return "powershell"
        if normalized in {"cmd", "eingabeaufforderung", "kommandozeile"}:
            return "cmd"
        raise ValueError("Als Shell sind nur cmd und powershell erlaubt.")

    def open(
        self,
        shell: str,
        *,
        command: str = "",
        working_directory: str = "",
    ) -> tuple[bool, str, int | None]:
        """Startet die Shell sichtbar und laesst sie nach dem Befehl offen."""

        if not self._is_windows:
            return False, "CMD und PowerShell werden derzeit nur unter Windows unterstuetzt.", None

        try:
            normalized = self._normalize_shell(shell)
        except ValueError as error:
            return False, str(error), None

        cwd: str | None = None
        if working_directory.strip():
            path = Path(os.path.expandvars(os.path.expanduser(working_directory))).resolve()
            if not path.is_dir():
                return False, f"Der Arbeitsordner existiert nicht: {path}", None
            cwd = str(path)

        if normalized == "cmd":
            executable = shutil.which("cmd.exe") or os.environ.get("COMSPEC", "cmd.exe")
            argv = [executable]
            if command.strip():
                argv.extend(["/K", command.strip()])
        else:
            executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
            if not executable:
                return False, "PowerShell wurde auf diesem Rechner nicht gefunden.", None
            argv = [executable, "-NoLogo", "-NoExit"]
            if command.strip():
                argv.extend(["-Command", command.strip()])

        try:
            process = subprocess.Popen(  # noqa: S603 - nach kritischer Benutzerfreigabe.
                argv,
                cwd=cwd,
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                close_fds=True,
            )
        except OSError as error:
            logger.exception("Terminalstart fehlgeschlagen.")
            return False, f"Das Terminal liess sich nicht starten: {error}", None

        if command.strip():
            message = f"{normalized} wurde geoeffnet und der Befehl wurde darin gestartet."
        else:
            message = f"{normalized} wurde geoeffnet."
        return True, message, process.pid
