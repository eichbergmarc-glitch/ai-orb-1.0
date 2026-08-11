"""Werkzeugsystem von AI-Orb (v2 Phase 12).

Ein Sprachmodell weiß viel, aber es weiß nichts über die Gegenwart und
nichts über diesen Rechner. Werkzeuge schließen diese Lücke: Sie geben ihm
Zugang zu Uhrzeit, Dateien, Gedächtnis und Programmen – aber nur so weit,
wie die Sicherheitsschicht es erlaubt.

Der Ablauf steht in :mod:`backend.tools.tool_engine`.
"""

from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.tools.registry import ToolRegistry
from backend.tools.standard_tools import build_standard_tools, evaluate_expression
from backend.tools.tool_engine import (
    ToolCall,
    ToolEngine,
    ToolLoopResult,
    ToolRun,
    parse_tool_calls,
    strip_tool_calls,
)

__all__ = [
    "Tool",
    "ToolCall",
    "ToolEngine",
    "ToolLoopResult",
    "ToolParameter",
    "ToolRegistry",
    "ToolResult",
    "ToolRun",
    "build_standard_tools",
    "evaluate_expression",
    "parse_tool_calls",
    "strip_tool_calls",
]
