"""Sichtbare CMD-/PowerShell-Auftraege aus Sprache und Chat."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from backend.memory.memory_engine import MemoryEngine
from backend.orchestrator.orchestrator import Orchestrator
from backend.system.terminal_control import TerminalControl, parse_terminal_request
from backend.tools.base_tool import ToolResult
from backend.tools.tool_engine import ToolRun


@pytest.mark.parametrize(
    ("text", "shell", "command"),
    [
        ("Oeffne CMD", "cmd", ""),
        ("Öffne bitte PowerShell", "powershell", ""),
        ("Öffne CMD und führe dort dir aus", "cmd", "dir"),
        ("Führe Get-Process in PowerShell aus", "powershell", "Get-Process"),
        ("Gib in CMD ipconfig ein", "cmd", "ipconfig"),
        (
            'Führe in PowerShell Write-Host "Hallo Welt" aus',
            "powershell",
            'Write-Host "Hallo Welt"',
        ),
        ("Starte PowerShell und führe `Get-Date | Format-List` aus", "powershell", "Get-Date | Format-List"),
    ],
)
def test_terminalauftrag_wird_lokal_erkannt(text: str, shell: str, command: str):
    request = parse_terminal_request(text)
    assert request is not None
    assert request.shell == shell
    assert request.command == command


@pytest.mark.parametrize(
    "text",
    [
        "Wie funktioniert PowerShell?",
        "Was ist der Unterschied zwischen CMD und Bash?",
        "Erkläre mir Kommandozeilenprogramme.",
    ],
)
def test_erklaerfragen_starten_keine_shell(text: str):
    assert parse_terminal_request(text) is None


def test_cmd_wird_sichtbar_mit_befehl_und_k_geoeffnet(monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    class _Process:
        pid = 321

    def fake_popen(argv, **kwargs):
        calls.append((list(argv), dict(kwargs)))
        return _Process()

    monkeypatch.setattr("backend.system.terminal_control.shutil.which", lambda name: "C:/Windows/System32/cmd.exe")
    monkeypatch.setattr("backend.system.terminal_control.subprocess.Popen", fake_popen)
    control = TerminalControl()
    control._is_windows = True

    ok, _message, pid = control.open("cmd", command="dir")

    assert ok is True and pid == 321
    assert calls[0][0][-2:] == ["/K", "dir"]


def test_powershell_bleibt_nach_befehl_offen(monkeypatch):
    calls: list[list[str]] = []

    class _Process:
        pid = 654

    monkeypatch.setattr(
        "backend.system.terminal_control.shutil.which",
        lambda name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    )
    monkeypatch.setattr(
        "backend.system.terminal_control.subprocess.Popen",
        lambda argv, **kwargs: calls.append(list(argv)) or _Process(),
    )
    control = TerminalControl()
    control._is_windows = True

    ok, _message, _pid = control.open("powershell", command="Get-Date")

    assert ok is True
    assert "-NoExit" in calls[0]
    assert calls[0][-2:] == ["-Command", "Get-Date"]


class _Providers:
    active_name = "test"

    def begin_conversation(self) -> None:
        pass


class _ToolEngine:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str]] = []

    async def direkt_ausfuehren(self, name: str, arguments: dict, *, actor: str):
        self.calls.append((name, arguments, actor))
        return ToolRun(
            name,
            arguments,
            ToolResult.success("powershell wurde geoeffnet und der Befehl wurde darin gestartet."),
        )


def test_orchestrator_fuehrt_terminalauftrag_ohne_modell_aus():
    tools = _ToolEngine()
    orchestrator = Orchestrator(
        memory=MemoryEngine(),
        provider_manager=_Providers(),  # type: ignore[arg-type]
    )
    orchestrator.attach_tool_engine(tools)

    result = asyncio.run(
        orchestrator.handle("Öffne PowerShell und führe dort Get-Date aus")
    )

    assert result.used_llm is False
    assert result.module == "terminal"
    assert tools.calls == [
        (
            "terminal_befehl_ausfuehren",
            {"shell": "powershell", "befehl": "Get-Date"},
            "terminal_sprachbefehl",
        )
    ]


def test_standardwerkzeuge_enthalten_beide_terminalwege():
    from backend.tools.terminal_tools import build_terminal_tools

    tools = {tool.name: tool for tool in build_terminal_tools()}
    assert tools["terminal_oeffnen"].permission == "launch_application"
    assert tools["terminal_befehl_ausfuehren"].permission == "system_commands"
