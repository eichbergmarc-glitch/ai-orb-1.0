"""Beispiel-Plugin für AI-Orb.

Zeigt an zwei kleinen Werkzeugen, wie ein Plugin aufgebaut ist. Beide
kommen mit der Berechtigung ``compute`` aus – sie rechnen nur und rühren
weder Dateien noch Netz an.

Zum eigenen Plugin: Diesen Ordner kopieren, umbenennen, ``plugin.yaml``
anpassen und hier die Werkzeuge austauschen. Mehr ist nicht nötig.

Zwei Regeln, die AI-Orb durchsetzt und die man beim Bauen kennen sollte:

1. Ein Werkzeug wird nur angenommen, wenn seine Berechtigung im Manifest
   steht. Sonst weist ``register_tool`` es ab und gibt ``False`` zurück.
2. Jeder Werkzeugaufruf läuft über die Sicherheitsschicht. Ein Plugin kann
   also nichts tun, was der Benutzer nicht freigegeben hat.
"""

from __future__ import annotations

import random
from typing import Any

from backend.plugins.plugin_base import OrbPlugin
from backend.tools.base_tool import Tool, ToolParameter, ToolResult


class DiceTool(Tool):
    """Würfelt."""

    name = "wuerfeln"
    description = (
        "Würfelt mit einer beliebigen Anzahl Würfel und Seiten und nennt das "
        "Ergebnis. Benutze das, wenn nach einem Zufallsergebnis gefragt wird."
    )
    permission = "compute"
    parameters = (
        ToolParameter(
            "anzahl", "integer", "Wie viele Würfel geworfen werden.", required=False, default=1
        ),
        ToolParameter(
            "seiten", "integer", "Wie viele Seiten ein Würfel hat.", required=False, default=6
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        count = max(1, min(100, int(arguments.get("anzahl", 1))))
        sides = max(2, min(1000, int(arguments.get("seiten", 6))))

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)

        if count == 1:
            return ToolResult.success(f"Gewürfelt: {rolls[0]}", rolls=rolls, total=total)

        return ToolResult.success(
            f"Gewürfelt: {', '.join(str(value) for value in rolls)} – zusammen {total}",
            rolls=rolls,
            total=total,
        )


#: Umrechnungsfaktoren, jeweils bezogen auf die Grundeinheit.
_UNITS: dict[str, tuple[str, float]] = {
    "km": ("laenge", 1000.0),
    "m": ("laenge", 1.0),
    "cm": ("laenge", 0.01),
    "mm": ("laenge", 0.001),
    "meile": ("laenge", 1609.344),
    "fuss": ("laenge", 0.3048),
    "zoll": ("laenge", 0.0254),
    "kg": ("masse", 1.0),
    "g": ("masse", 0.001),
    "t": ("masse", 1000.0),
    "pfund": ("masse", 0.45359237),
    "unze": ("masse", 0.028349523125),
    "l": ("volumen", 1.0),
    "ml": ("volumen", 0.001),
    "gallone": ("volumen", 3.785411784),
}


class ConvertUnitTool(Tool):
    """Rechnet Einheiten um."""

    name = "einheit_umrechnen"
    description = (
        "Rechnet zwischen Längen-, Massen- und Volumeneinheiten um, etwa "
        "Meilen in Kilometer oder Pfund in Kilogramm."
    )
    permission = "compute"
    parameters = (
        ToolParameter("wert", "number", "Der umzurechnende Zahlenwert."),
        ToolParameter(
            "von", "string", "Die Ausgangseinheit.", choices=tuple(sorted(_UNITS))
        ),
        ToolParameter(
            "nach", "string", "Die Zieleinheit.", choices=tuple(sorted(_UNITS))
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        value = float(arguments["wert"])
        source = str(arguments["von"]).strip().lower()
        target = str(arguments["nach"]).strip().lower()

        source_kind, source_factor = _UNITS[source]
        target_kind, target_factor = _UNITS[target]

        if source_kind != target_kind:
            return ToolResult.failure(
                f"'{source}' und '{target}' messen Verschiedenes "
                f"({source_kind} gegen {target_kind}) und lassen sich nicht "
                "ineinander umrechnen."
            )

        converted = value * source_factor / target_factor
        return ToolResult.success(
            f"{value:g} {source} sind {converted:.6g} {target}",
            value=converted,
        )


class Plugin(OrbPlugin):
    """Das Beispiel-Plugin."""

    async def setup(self) -> None:
        """Meldet die Werkzeuge an."""

        accepted = 0
        for tool in (DiceTool(), ConvertUnitTool()):
            if self.context.register_tool(tool):
                accepted += 1

        self.context.log(f"{accepted} Werkzeuge angemeldet.")

    async def teardown(self) -> None:
        """Hier wäre aufzuräumen – dieses Plugin hat nichts offen."""

        self.context.log("Wird entladen.")

    def info(self) -> dict[str, Any]:
        return {"werkzeuge": ["wuerfeln", "einheit_umrechnen"]}
