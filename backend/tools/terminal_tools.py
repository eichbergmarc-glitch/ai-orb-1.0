"""Werkzeuge fuer sichtbare CMD- und PowerShell-Sitzungen."""

from __future__ import annotations

from typing import Any

from backend.system.terminal_control import TerminalControl
from backend.tools.base_tool import Tool, ToolParameter, ToolResult


class OpenTerminalTool(Tool):
    name = "terminal_oeffnen"
    description = (
        "Oeffnet ein sichtbares CMD- oder PowerShell-Fenster und laesst es offen. "
        "Benutze dies, wenn der Benutzer ausdruecklich eine dieser Konsolen oeffnen will."
    )
    permission = "launch_application"
    parameters = (
        ToolParameter("shell", "string", "Welche Shell geoeffnet wird.", choices=("cmd", "powershell")),
        ToolParameter("arbeitsordner", "string", "Optionaler Startordner.", required=False, default=""),
    )

    def __init__(self, control: TerminalControl) -> None:
        self._control = control

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ok, message, pid = self._control.open(
            str(arguments["shell"]),
            working_directory=str(arguments.get("arbeitsordner", "")),
        )
        return ToolResult.success(message, pid=pid) if ok else ToolResult.failure(message)


class RunTerminalCommandTool(Tool):
    name = "terminal_befehl_ausfuehren"
    description = (
        "Oeffnet CMD oder PowerShell sichtbar, fuehrt darin genau den vom Benutzer "
        "genannten Befehl aus und laesst das Fenster danach offen. Verwende keine "
        "erfundenen Zusatzbefehle. Diese Aktion braucht fuer jeden Aufruf Zustimmung."
    )
    permission = "system_commands"
    parameters = (
        ToolParameter("shell", "string", "Shell fuer den Befehl.", choices=("cmd", "powershell")),
        ToolParameter("befehl", "string", "Der unveraenderte auszufuehrende Befehl."),
        ToolParameter("arbeitsordner", "string", "Optionaler Arbeitsordner.", required=False, default=""),
    )

    def __init__(self, control: TerminalControl) -> None:
        self._control = control

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = str(arguments["befehl"]).strip()
        if not command:
            return ToolResult.failure("Es wurde kein Befehl angegeben.")
        if len(command) > 4000:
            return ToolResult.failure("Der Befehl ist zu lang.")
        ok, message, pid = self._control.open(
            str(arguments["shell"]),
            command=command,
            working_directory=str(arguments.get("arbeitsordner", "")),
        )
        return (
            ToolResult.success(message, pid=pid, command=command)
            if ok
            else ToolResult.failure(message)
        )


def build_terminal_tools() -> list[Tool]:
    control = TerminalControl()
    return [OpenTerminalTool(control), RunTerminalCommandTool(control)]
