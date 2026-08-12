"""Das Werkzeug, mit dem der Orb einen Browser bedient.

Ein einziges Werkzeug mit mehreren Aktionen – ``oeffnen``, ``elemente``,
``klicken``, ``tippen``, ``scrollen``, ``lesen``, ``taste``, ``zurueck``,
``schliessen``. Ein Werkzeug und nicht zehn, weil sie alle auf DASSELBE
Browserfenster wirken und nur so in der richtigen Reihenfolge zusammenspielen:
erst ``oeffnen``, dann ``elemente`` ansehen, dann ``klicken`` – Schritt für
Schritt, wie ein Mensch es täte.

Der eigentliche Kniff steckt in ``elemente`` und ``klicken``: ``elemente``
zählt alles Anklickbare durch, ``klicken`` und ``tippen`` sprechen die Nummer
an. So muss der Orb keine unsichtbaren CSS-Pfade raten, sondern arbeitet mit
dem, was er sieht.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.browser.steuerung import Browsersteuerung, BrowserNichtBereit, Element
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

_AKTIONEN = (
    "oeffnen", "elemente", "klicken", "tippen", "scrollen",
    "lesen", "taste", "zurueck", "stand", "schliessen",
)


def _liste(elemente: list[Element]) -> str:
    if not elemente:
        return (
            "Auf der Seite ist gerade nichts Anklickbares zu erkennen. "
            "Vielleicht laedt sie noch, oder scroll ein Stueck."
        )
    zeilen = [el.zeile() for el in elemente]
    return (
        "Anklickbar auf der Seite (mit 'klicken'/'tippen' und der Nummer in "
        "'ziel' ansprechen):\n" + "\n".join(zeilen)
    )


class BrowserBedienenTool(Tool):
    """Öffnet und bedient ein Browserfenster – klicken, scrollen, tippen."""

    name = "browser_bedienen"
    description = (
        "Bedient einen echten Browser, um eine Website zu benutzen wie ein "
        "Mensch. Aktionen: 'oeffnen' (url) oeffnet eine Seite; 'elemente' "
        "zeigt alles Anklickbare mit Nummern; 'klicken' (ziel = Nummer oder "
        "sichtbarer Text) klickt darauf; 'tippen' (ziel = Nummer eines Feldes, "
        "text = was hinein soll, absenden = ob Enter folgt) schreibt in ein "
        "Feld; 'scrollen' (ziel = hoch/runter/anfang/ende) blaettert; 'lesen' "
        "gibt den sichtbaren Text; 'taste' (ziel = z.B. Enter, Escape) drueckt "
        "eine Taste; 'zurueck' geht eine Seite zurueck; 'schliessen' schliesst "
        "den Browser. Typischer Ablauf: oeffnen -> elemente -> klicken/tippen. "
        "Benutze das, wenn eine Seite Anmeldung, Klicks oder JavaScript "
        "braucht - sonst genuegt 'webseite_lesen'."
    )
    permission = "launch_application"
    parameters = (
        ToolParameter(
            "aktion", "string",
            "Was zu tun ist: " + ", ".join(_AKTIONEN) + ".",
            choices=list(_AKTIONEN),
        ),
        ToolParameter(
            "ziel", "string",
            "Je nach Aktion: bei 'oeffnen' die Adresse; bei 'klicken'/'tippen' "
            "die Nummer (oder der Text) des Elements; bei 'scrollen' "
            "hoch/runter/anfang/ende; bei 'taste' der Tastenname.",
            required=False, default="",
        ),
        ToolParameter(
            "text", "string", "Bei 'tippen': der Text, der ins Feld soll.",
            required=False, default="",
        ),
        ToolParameter(
            "absenden", "boolean",
            "Bei 'tippen': ob danach Enter gedrueckt wird (ja/nein).",
            required=False, default=False,
        ),
    )

    def __init__(self, steuerung: Browsersteuerung) -> None:
        super().__init__()
        self._browser = steuerung

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        aktion = str(arguments.get("aktion", "")).strip().lower()
        ziel = str(arguments.get("ziel", "")).strip()
        text = str(arguments.get("text", ""))
        absenden = bool(arguments.get("absenden", False))

        try:
            if aktion == "oeffnen":
                if not ziel:
                    return ToolResult.failure("Wohin? Gib eine Adresse in 'ziel' an.")
                stand = await self._browser.oeffnen(ziel)
                return ToolResult.success(
                    f"Geoeffnet: {stand['titel']}\n{stand['url']}", **stand
                )

            if aktion == "elemente":
                elemente = await self._browser.elemente()
                return ToolResult.success(_liste(elemente), anzahl=len(elemente))

            if aktion == "klicken":
                if not ziel:
                    return ToolResult.failure(
                        "Worauf? Gib die Nummer oder den Text in 'ziel' an "
                        "(erst 'elemente' zeigt die Nummern)."
                    )
                stand = await self._browser.klicken(ziel)
                return ToolResult.success(
                    f"Geklickt. Jetzt: {stand['titel']}\n{stand['url']}", **stand
                )

            if aktion == "tippen":
                if not ziel or not text:
                    return ToolResult.failure(
                        "Zum Tippen brauche ich 'ziel' (das Feld) und 'text'."
                    )
                stand = await self._browser.tippen(ziel, text, absenden=absenden)
                nachwort = " und abgeschickt" if absenden else ""
                return ToolResult.success(
                    f"Geschrieben{nachwort}. Jetzt: {stand['titel']}\n{stand['url']}",
                    **stand,
                )

            if aktion == "scrollen":
                stand = await self._browser.scrollen(ziel or "runter")
                return ToolResult.success(f"Gescrollt ({ziel or 'runter'}).", **stand)

            if aktion == "lesen":
                return ToolResult.success(await self._browser.lesen())

            if aktion == "taste":
                if not ziel:
                    return ToolResult.failure("Welche Taste? Z.B. Enter, Escape, Tab.")
                stand = await self._browser.taste(ziel)
                return ToolResult.success(f"Taste '{ziel}' gedrueckt.", **stand)

            if aktion == "zurueck":
                stand = await self._browser.zurueck()
                return ToolResult.success(
                    f"Zurueck. Jetzt: {stand['titel']}\n{stand['url']}", **stand
                )

            if aktion == "stand":
                stand = await self._browser.stand()
                return ToolResult.success(f"{stand['titel']}\n{stand['url']}", **stand)

            if aktion == "schliessen":
                return ToolResult.success(await self._browser.schliessen())

            return ToolResult.failure(
                f"Unbekannte Aktion '{aktion}'. Moeglich: {', '.join(_AKTIONEN)}."
            )

        except BrowserNichtBereit as fehler:
            # Der Ausweichweg, der dem Benutzer wochenlang gefehlt hat:
            # Ist die STEUERUNG nicht eingerichtet (Playwright fehlt), soll
            # "oeffne den Browser" trotzdem einen Browser oeffnen - den
            # normalen Standardbrowser des Systems. Das kann Windows immer.
            # Nur Klicken/Tippen/Lesen brauchen wirklich die Einrichtung.
            if aktion == "oeffnen" and ziel:
                adresse = ziel if ziel.startswith(("http://", "https://")) else "https://" + ziel
                try:
                    import webbrowser

                    geoeffnet = await asyncio.to_thread(webbrowser.open, adresse)
                except Exception:  # noqa: BLE001
                    geoeffnet = False
                if geoeffnet:
                    logger.info(
                        "Browsersteuerung fehlt - Ausweich: Standardbrowser "
                        "geoeffnet (%s).", adresse
                    )
                    return ToolResult.success(
                        f"Ich habe {adresse} im normalen Browser geöffnet. "
                        "Klicken, Tippen und Mitlesen kann ich dort noch nicht - "
                        "dafür muss einmal 'BROWSER-EINRICHTEN.bat' im "
                        "AI-Orb-Ordner ausgeführt werden.",
                        url=adresse, steuerung=False,
                    )
            return ToolResult.failure(str(fehler))
        except Exception as fehler:  # noqa: BLE001 - ein Werkzeug darf nie den Kern reissen.
            logger.exception("browser_bedienen fehlgeschlagen")
            return ToolResult.failure(f"Im Browser ging etwas schief: {fehler}")


def build_browser_tools(steuerung: Browsersteuerung) -> list[Tool]:
    """Baut die Browser-Werkzeuge um eine geteilte Steuerung."""

    return [BrowserBedienenTool(steuerung)]
