"""Werkzeug für einen vollständigen Entwicklungsauftrag im laufenden Orb."""

from __future__ import annotations

from typing import Any

from backend.tools.base_tool import Tool, ToolParameter, ToolResult


class LiveDevelopmentTool(Tool):
    """Plant, testet und übernimmt eine gewünschte Codeänderung."""

    name = "entwicklungsauftrag_umsetzen"
    description = (
        "Setzt einen Entwicklungswunsch am AI-Orb kontrolliert um: erst in "
        "einer isolierten Kopie, dann Tests und Review, danach Übernahme mit "
        "Sicherung sowie automatischem Neuladen oder Neustart."
    )
    permission = "modify_own_code"
    parameters = (
        ToolParameter(
            "wunsch",
            "string",
            "Die gewünschte Änderung in den ursprünglichen Worten des Benutzers.",
        ),
    )

    def __init__(self, service: Any) -> None:
        self._service = service

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        result = await self._service.implement(str(arguments.get("wunsch", "")))
        context = {
            "files": result.files,
            "patch_id": result.patch_id,
            "restore_point": result.restore_point,
            "needs_restart": result.needs_restart,
            "renderer_reloaded": result.renderer_reloaded,
        }
        if not result.ok:
            return ToolResult.failure(result.message, **context)
        return ToolResult.success(result.message, **context)


def build_development_tools(service: Any) -> list[Tool]:
    return [LiveDevelopmentTool(service)]
