"""Werkzeuge, mit denen der Orb seine eigene Animation verändert.

Der Benutzer will die Animation dem Orb erklären, statt Werte von Hand zu
ändern – „mach die Punkte grösser", „die Fäden länger", „andere Farben".
Und für Grösseres soll der Orb den Code selbst umschreiben.

Zwei Wege, und die Trennung ist wichtig:

* ``animation_anpassen`` – der SICHERE Weg. Er ändert nur Werte unter
  ``orb.animation`` in der config.yaml und lädt die Anzeige neu. Es wird
  nichts neu gebaut, es kann nichts kaputtgehen. Deckt „grösser, schneller,
  heller, andere Farben, längere Fäden" ab.

* ``oberflaeche_neu_bauen`` – der Werkzeugschritt für den MÄCHTIGEN Weg.
  Für Wünsche, die keine Werteänderung sind („lass sie wie ein Herzschlag
  pulsieren"), schreibt der Orb die Datei ``desktop/renderer/zwei_punkte.ts``
  mit ``eigenen_code_aendern`` um und ruft DANN dieses Werkzeug: Es baut die
  Oberfläche neu. Scheitert der Bau, sagt es das mit der Fehlermeldung –
  dann nimmt der Orb seine Änderung mit ``letzte_selbstaenderung_zuruecknehmen``
  zurück, damit die Anzeige heil bleibt.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from backend.animation.config_schreiber import (
    lies_animationswerte,
    schreibe_animationswerte,
)
from backend.animation.wunsch_deuter import deute
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.utils.paths import get_project_root

logger = get_logger(__name__)

#: Das Ereignis, auf das die Oberfläche mit einem Neuladen reagiert.
NEU_LADEN = "orb.oberflaeche.neu_laden"


class AnimationAnpassenTool(Tool):
    """Ändert die Animation über ihre Werte – der sichere Weg."""

    name = "animation_anpassen"
    description = (
        "Aendert die Animation des Orb nach einem gesprochenen Wunsch: "
        "groesser/kleiner, schneller/langsamer, heller/dunkler, laengere "
        "Faeden, weiter auseinander, staerker verschmelzen, andere Farben "
        "(z.B. 'gruen und gelb'). Benutze das immer, wenn der Benutzer die "
        "Animation, die Punkte, die Kugeln, die Farben oder die Faeden "
        "aendern will. Gib seinen Wunsch woertlich weiter."
    )
    permission = "modify_own_code"
    parameters = (
        ToolParameter(
            "wunsch", "string",
            "Was der Benutzer geaendert haben will, in seinen eigenen Worten.",
        ),
    )

    def __init__(self, event_bus: Any, config_pfad: Path | None = None) -> None:
        self._bus = event_bus
        self._pfad = config_pfad or (get_project_root() / "config.yaml")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        wunsch = str(arguments.get("wunsch", "")).strip()
        if not wunsch:
            return ToolResult.failure("Es fehlt der Wunsch.")

        aktuell = await asyncio.to_thread(lies_animationswerte, self._pfad)
        deutung = deute(wunsch, aktuell=aktuell)

        if not deutung.erkannt:
            # Kein Werte-Wunsch. Der Orb soll den anderen Weg nehmen.
            return ToolResult.success(
                "Das ist keine einfache Werteanpassung. Schreibe dafuer die "
                "Datei 'desktop/renderer/zwei_punkte.ts' mit dem Werkzeug "
                "'eigenen_code_aendern' um und rufe danach 'oberflaeche_neu_bauen'. "
                "Geht der Bau schief, nimm die Aenderung mit "
                "'letzte_selbstaenderung_zuruecknehmen' zurueck.",
                weg="code",
            )

        # Die Änderungen auf die aktuellen Werte anwenden.
        neu: dict[str, float] = {}
        for aenderung in deutung.aenderungen:
            basis = aktuell.get(aenderung.schluessel, _VORGABE.get(aenderung.schluessel, 1.0))
            neu[aenderung.schluessel] = round(aenderung.anwenden(basis), 4)

        erfolg, fehlend = await asyncio.to_thread(
            schreibe_animationswerte, self._pfad, neu
        )
        if not erfolg:
            return ToolResult.failure(
                "Die Animationswerte liessen sich nicht schreiben "
                f"(nicht gefunden: {', '.join(fehlend) or 'unbekannt'})."
            )

        # Die Anzeige neu laden, damit die neuen Werte greifen.
        await self._bus.publish(NEU_LADEN, {"grund": "animation_anpassen"})

        beschreibung = deutung.erklaerung
        return ToolResult.success(
            f"Erledigt: {beschreibung}. Die Animation wurde neu geladen.",
            geaendert=neu,
        )


class OberflaecheNeuBauenTool(Tool):
    """Baut die Oberfläche neu – nach einer Code-Änderung an der Animation."""

    name = "oberflaeche_neu_bauen"
    description = (
        "Baut die Orb-Oberflaeche neu und laedt sie. Rufe das NUR, nachdem du "
        "eine Renderer-Datei (z.B. desktop/renderer/zwei_punkte.ts) mit "
        "'eigenen_code_aendern' umgeschrieben hast. Scheitert der Bau, bekommst "
        "du die Fehlermeldung - dann nimm deine Aenderung mit "
        "'letzte_selbstaenderung_zuruecknehmen' zurueck und melde es dem Benutzer."
    )
    permission = "system_commands"
    parameters = ()

    def __init__(self, event_bus: Any, projekt: Path | None = None) -> None:
        self._bus = event_bus
        self._projekt = projekt or get_project_root()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        logger.info("Baue die Oberflaeche neu ...")
        try:
            ergebnis = await asyncio.to_thread(self._bauen)
        except FileNotFoundError:
            return ToolResult.failure(
                "npm wurde nicht gefunden - die Oberflaeche laesst sich von "
                "hier nicht neu bauen."
            )
        except subprocess.TimeoutExpired:
            return ToolResult.failure("Der Bau hat zu lange gedauert und wurde abgebrochen.")

        if ergebnis.returncode != 0:
            fehler = (ergebnis.stderr or ergebnis.stdout or "").strip()
            # Nur das Ende: Baufehler stehen unten, und der Anfang ist Lärm.
            fehler = "\n".join(fehler.splitlines()[-12:])[-1200:]
            logger.warning("Bau der Oberflaeche gescheitert:\n%s", fehler)
            return ToolResult.failure(
                "Der Bau ist gescheitert. Nimm deine letzte Aenderung zurueck. "
                f"Meldung:\n{fehler}"
            )

        await self._bus.publish(NEU_LADEN, {"grund": "oberflaeche_neu_bauen"})
        logger.info("Oberflaeche neu gebaut und neu geladen.")
        return ToolResult.success(
            "Die Oberflaeche wurde neu gebaut und neu geladen. Sieh nach, ob es "
            "so aussieht wie gewollt."
        )

    def _bauen(self) -> subprocess.CompletedProcess:
        # Nur den Renderer bauen - das ist der Teil, an dem die Animation
        # haengt, und es dauert Sekunden statt einer Minute.
        npm = "npm.cmd" if _ist_windows() else "npm"
        return subprocess.run(  # noqa: S603
            [npm, "run", "build:renderer"],
            cwd=str(self._projekt),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )


def _ist_windows() -> bool:
    import sys

    return sys.platform.startswith("win")


#: Vorgaben, falls ein Wert (noch) nicht in der config steht.
_VORGABE: dict[str, float] = {
    "abstand": 0.68,
    "punkt_groesse": 1.0,
    "verschmelzen": 1.15,
    "schweif_laenge": 26,
    "tempo": 1.0,
    "helligkeit": 1.0,
    "farbe_a": 1.0,
    "farbe_b": 0.62,
    "scale": 0.65,
}


#: Gesprochene Namen -> Darstellung (13.11.2026).
_DARSTELLUNGEN = (
    ("drei_kugeln", ("kugel", "baell", "bäll", "bälle", "baelle", "drei", "rgb", "farbkugel")),
    ("synaptix", ("gehirn", "hirn", "synaptix", "neuron", "netz")),
    ("energie", ("energie", "energy", "auge", "augen")),
    ("klassisch", ("klassisch", "punkte", "zwei punkte", "einfach", "schlicht")),
)


def darstellung_aus(wunsch: str) -> str:
    text = str(wunsch or "").lower()
    for name, woerter in _DARSTELLUNGEN:
        if name in text or any(wort in text for wort in woerter):
            return name
    return ""


def darstellung_schreiben(pfad: Path, darstellung: str) -> None:
    """Setzt ``orb.darstellung`` in der config.yaml - Kommentare bleiben."""

    zeilen = pfad.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, z in enumerate(zeilen) if z.rstrip() == "orb:"), None)
    if start is None:
        zeilen.append(f"\norb:\n  darstellung: {darstellung}\n")
    else:
        ende = next(
            (i for i in range(start + 1, len(zeilen))
             if zeilen[i].strip() and not zeilen[i].startswith((" ", "\t", "#"))),
            len(zeilen),
        )
        for i in range(start + 1, ende):
            if zeilen[i].startswith("  darstellung:"):
                zeilen[i] = f"  darstellung: {darstellung}\n"
                break
        else:
            zeilen.insert(start + 1, f"  darstellung: {darstellung}\n")
    pfad.write_text("".join(zeilen), encoding="utf-8")


class AnimationWechselnTool(Tool):
    """Wechselt die Darstellung des Orb (Kugeln, Gehirn, Energie, klassisch)."""

    name = "animation_wechseln"
    description = (
        "Wechselt die ganze Animation des Orb: 'drei Kugeln' (rot, gruen, blau, "
        "verschmelzend), 'Gehirn' (Synaptix), 'Energie' (Energie-Orb mit Augen) "
        "oder 'klassisch'. Fuer 'wechsle zur Kugel-Animation', 'zeig das Gehirn' usw."
    )
    permission = "modify_own_code"
    parameters = (ToolParameter("darstellung", "string", "Welche Animation, in Marcs Worten."),)

    def __init__(self, event_bus: Any) -> None:
        self._bus = event_bus

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ziel = darstellung_aus(str(arguments.get("darstellung", "")))
        if not ziel:
            return ToolResult.failure(
                "Diese Animation kenne ich nicht. Es gibt: drei Kugeln, Gehirn, Energie, klassisch."
            )
        from backend.config import get_config

        konfig = get_config()
        pfad = Path(getattr(konfig, "_config_path", get_project_root() / "config.yaml"))
        try:
            await asyncio.to_thread(darstellung_schreiben, pfad, ziel)
            konfig.reload()
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Die Einstellung liess sich nicht schreiben: {fehler}")
        await self._bus.publish(NEU_LADEN, {"grund": "animation_wechseln"})
        namen = {"drei_kugeln": "die drei Kugeln", "synaptix": "das Gehirn",
                 "energie": "den Energie-Orb", "klassisch": "die klassische Animation"}
        return ToolResult.success(f"Erledigt, ich zeige jetzt {namen[ziel]}.")


def build_animation_tools(event_bus: Any) -> list[Tool]:
    """Baut die Animations-Werkzeuge."""

    return [
        AnimationAnpassenTool(event_bus),
        OberflaecheNeuBauenTool(event_bus),
        AnimationWechselnTool(event_bus),
    ]
