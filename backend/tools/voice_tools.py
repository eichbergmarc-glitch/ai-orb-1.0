"""Werkzeuge rund um die Stimme des Benutzers.

Der Orb soll auf eine Stimme hören und nicht auf jede. Damit er das lernen,
vergessen und Auskunft darüber geben kann, braucht er dafür Werkzeuge –
sonst bliebe die Fähigkeit zwar eingebaut, aber unerreichbar.

Das Lernen läuft dabei nicht in einem Zug ab: Der Orb sagt, was er
braucht, und nimmt dann die nächsten Äusserungen als Proben entgegen. Das
Werkzeug stösst diesen Vorgang nur an; die Sammlung selbst geschieht in
der Sprachschicht, die die Aufnahmen ohnehin bekommt.
"""

from __future__ import annotations

from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


class LearnVoiceTool(Tool):
    """Merkt sich die Stimme des Benutzers."""

    name = "stimme_lernen"
    description = (
        "Merkt sich die Stimme des Benutzers, damit der Orb nur noch auf "
        "ihn hört und nicht auf andere Stimmen im Raum oder aus dem "
        "Fernseher. Benutze das, wenn der Benutzer sinngemäss sagt: 'lern "
        "dir meine Stimme', 'hör nur auf mich', 'reagier nicht auf andere "
        "Stimmen'. Danach sagt der Orb dem Benutzer, was er sprechen soll."
    )
    permission = "microphone"
    parameters = ()

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        starten = getattr(self._pipeline, "stimme_lernen_starten", None)
        if starten is None:
            return ToolResult.failure("Die Sprachsteuerung läuft gerade nicht.")
        return ToolResult.success(await starten())


class ForgetVoiceTool(Tool):
    """Vergisst die hinterlegte Stimme."""

    name = "stimme_vergessen"
    description = (
        "Löscht die hinterlegte Stimme. Danach hört der Orb wieder auf "
        "jeden, der spricht. Benutze das, wenn der Benutzer sagt, du sollst "
        "wieder auf alle hören oder seine Stimme vergessen."
    )
    permission = "microphone"
    parameters = ()

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        vergessen = getattr(self._pipeline, "stimme_vergessen", None)
        if vergessen is None:
            return ToolResult.failure("Die Sprachsteuerung läuft gerade nicht.")
        return ToolResult.success(vergessen())


class VoiceStatusTool(Tool):
    """Sagt, auf wen der Orb gerade hört."""

    name = "stimme_status"
    description = (
        "Sagt, ob der Orb eine Stimme hinterlegt hat und nur auf sie hört – "
        "oder ob er auf jeden reagiert."
    )
    permission = "compute"
    parameters = (
        ToolParameter(
            "ausfuehrlich",
            "boolean",
            "Ob auch die Zahlenwerte genannt werden.",
            required=False,
            default=False,
        ),
    )

    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        status_fn = getattr(self._pipeline, "stimme_status", None)
        if status_fn is None:
            return ToolResult.failure("Die Sprachsteuerung läuft gerade nicht.")

        status = status_fn()

        if status.get("lernt_gerade"):
            fehlt = int(status.get("benoetigt", 0)) - int(status.get("gesammelt", 0))
            return ToolResult.success(
                f"Ich lerne gerade deine Stimme – es fehlen noch {max(0, fehlt)} Sätze.",
                **status,
            )

        if not status.get("gelernt"):
            return ToolResult.success(
                "Es ist keine Stimme hinterlegt; ich höre auf jeden, der "
                "spricht. Sag 'lern dir meine Stimme', wenn ich nur noch auf "
                "dich hören soll.",
                **status,
            )

        text = (
            f"Ich habe deine Stimme aus {status.get('aufnahmen', 0)} Aufnahmen "
            "hinterlegt und höre nur auf dich."
        )
        if bool(arguments.get("ausfuehrlich", False)):
            text += f" Die Erkennungsschwelle liegt bei {status.get('schwelle', 0)}."
        return ToolResult.success(text, **status)


def build_voice_tools(pipeline: Any) -> list[Tool]:
    """Stellt die Stimmwerkzeuge zusammen."""

    return [
        LearnVoiceTool(pipeline),
        ForgetVoiceTool(pipeline),
        VoiceStatusTool(pipeline),
    ]
