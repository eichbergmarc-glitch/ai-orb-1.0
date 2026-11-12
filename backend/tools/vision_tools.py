"""Werkzeuge für den Bildschirm: aufnehmen und auswerten.

Die Bildverarbeitung war vollständig gebaut – Aufnahme, Texterkennung,
Beschreibung durch ein Sprachmodell –, aber wie schon bei der
Internetsuche fehlte das Bindeglied: Es gab kein Werkzeug, mit dem das
Sprachmodell sie hätte aufrufen können. Auf „mach ein Bildschirmfoto und
sag mir, was da steht" konnte der Orb deshalb nur antworten, er könne das
nicht – obwohl der Apparat dafür bereitlag.

Zwei Werkzeuge schließen die Lücke:

* ``bildschirm_lesen`` nimmt den Bildschirm auf und liest den Text darauf
  aus. Das geschieht **vollständig auf dem Rechner** – das Bild wird
  nirgendwohin geschickt. Für alles, wo Text zu sehen ist (ein Dokument,
  eine Fehlermeldung, eine Webseite), ist das der richtige Weg.
* ``bildschirm_ansehen`` lässt ein Sprachmodell beschreiben, was zu sehen
  ist. Dafür verlässt das Bild den Rechner, weshalb es eigens freigegeben
  sein muss. Es ist der Weg für alles, was sich nicht als Text auslesen
  lässt: Diagramme, Karten, Fotos, Bildquellen.
"""

from __future__ import annotations

from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


class ReadScreenTool(Tool):
    """Nimmt den Bildschirm auf und liest den Text darauf aus."""

    name = "bildschirm_lesen"
    description = (
        "Macht ein Bildschirmfoto und liest den Text darauf aus - komplett "
        "auf diesem Rechner, das Bild wird nirgendwohin geschickt. Benutze "
        "das, wenn der Benutzer fragt, was auf dem Bildschirm steht, was in "
        "einer Fehlermeldung steht, oder dich bittet, ein Dokument oder eine "
        "Seite zu lesen, die er gerade offen hat."
    )
    permission = "screen_capture"
    parameters = (
        ToolParameter(
            "bildschirm", "integer", "Welcher Bildschirm (1 ist der erste).",
            required=False, default=1,
        ),
    )

    def __init__(self, vision: Any | None = None) -> None:
        super().__init__()
        self._vision = vision

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._vision is None:
            return ToolResult.failure("Die Bildschirmauswertung ist nicht verfügbar.")

        monitor = int(arguments.get("bildschirm", 1) or 1)
        try:
            result = await self._vision.read_screen(monitor=monitor, actor="werkzeug")
        except Exception as error:  # noqa: BLE001 - ein Werkzeug darf nie den Kern reissen.
            logger.exception("Das Auslesen des Bildschirms ist fehlgeschlagen.")
            return ToolResult.failure(f"Bildschirm nicht lesbar: {error}")

        if not getattr(result, "ok", False):
            return ToolResult.failure(getattr(result, "error", "Unbekannter Fehler."))

        text = (getattr(result, "answer", "") or "").strip()
        if not text:
            return ToolResult.success("Auf dem Bildschirm war kein lesbarer Text.")
        return ToolResult.success(text, zeichen=len(text))


class DescribeScreenTool(Tool):
    """Lässt beschreiben, was auf dem Bildschirm zu sehen ist."""

    name = "bildschirm_ansehen"
    description = (
        "Macht ein Bildschirmfoto und beschreibt, was darauf ZU SEHEN ist - "
        "fuer Bilder, Diagramme, Karten, Grafiken und Bildquellen, also "
        "alles, was sich nicht als Text auslesen laesst. Dafuer wird das "
        "Bild an ein Sprachmodell geschickt. Geht es nur um Text, nimm "
        "bildschirm_lesen: das bleibt auf dem Rechner."
    )
    permission = "screen_capture"
    parameters = (
        ToolParameter(
            "frage", "string",
            "Was genau wissenswert ist. Leer heisst: allgemein beschreiben.",
            required=False, default="",
        ),
        ToolParameter(
            "bildschirm", "integer", "Welcher Bildschirm (1 ist der erste).",
            required=False, default=1,
        ),
    )

    def __init__(self, vision: Any | None = None) -> None:
        super().__init__()
        self._vision = vision

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._vision is None:
            return ToolResult.failure("Die Bildschirmauswertung ist nicht verfügbar.")

        question = str(arguments.get("frage", "")).strip()
        monitor = int(arguments.get("bildschirm", 1) or 1)

        try:
            result = await self._vision.describe_screen(
                question, monitor=monitor, actor="werkzeug"
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("Die Bildbeschreibung ist fehlgeschlagen.")
            return ToolResult.failure(f"Bildschirm nicht auswertbar: {error}")

        if not getattr(result, "ok", False):
            # Der häufigste Fall: Das Übertragen an ein Modell ist
            # ausgeschaltet. Dann den lokalen Weg anbieten statt bloß
            # abzulehnen.
            reason = getattr(result, "error", "Unbekannter Fehler.")
            return ToolResult.failure(
                f"{reason}\nHinweis: Text auf dem Bildschirm lässt sich mit "
                "bildschirm_lesen auch ohne diese Freigabe auslesen."
            )

        return ToolResult.success(getattr(result, "answer", ""))


class KameraAnsehenTool(Tool):
    """Sieht durch die Webcam (07.11.2026)."""

    name = "kamera_ansehen"
    description = (
        "Macht ein Standbild mit der WEBCAM und beschreibt, was zu sehen ist - "
        "wer vor dem Rechner sitzt, was er in der Hand haelt, was im Raum "
        "passiert. Erkennt Marc, wenn ein Referenzfoto gespeichert ist. Das "
        "Bild geht zur Auswertung an das Sprachmodell und wird nicht "
        "gespeichert. NUR benutzen, wenn der Benutzer ausdruecklich will, dass "
        "du durch die Kamera schaust."
    )
    permission = "camera"
    parameters = (
        ToolParameter(
            "frage", "string",
            "Was genau wissenswert ist, z. B. 'Wer sitzt da?' oder 'Was halte ich hoch?'.",
            required=False, default="",
        ),
    )

    def __init__(self, kamera: Any | None = None) -> None:
        super().__init__()
        self._kamera = kamera

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._kamera is None:
            return ToolResult.failure("Die Kamera ist nicht eingerichtet.")
        try:
            antwort = await self._kamera.ansehen(str(arguments.get("frage", "") or ""))
        except Exception as error:  # noqa: BLE001
            logger.warning("Kamerabild nicht auswertbar: %s", error)
            return ToolResult.failure(
                f"Die Webcam liess sich nicht nutzen: {error}. Pruefe, ob sie "
                "eingesteckt ist und kein anderes Programm (Kamera-App, Teams) "
                "sie gerade benutzt."
            )
        return ToolResult.success(antwort or "Auf dem Kamerabild war nichts zu erkennen.")


class GesichtMerkenTool(Tool):
    """Speichert ein Referenzfoto, damit Synapse Marc wiedererkennt."""

    name = "gesicht_merken"
    description = (
        "Macht mit der Webcam ein Referenzfoto des Benutzers und speichert es "
        "auf diesem Rechner, damit du ihn spaeter auf Kamerabildern "
        "wiedererkennst. Benutzen, wenn der Benutzer sagt 'merk dir mein "
        "Gesicht' oder 'lerne, wie ich aussehe'. Vorher bitten, gerade in die "
        "Kamera zu schauen."
    )
    permission = "camera"
    parameters = ()

    def __init__(self, kamera: Any | None = None) -> None:
        super().__init__()
        self._kamera = kamera

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if self._kamera is None:
            return ToolResult.failure("Die Kamera ist nicht eingerichtet.")
        try:
            pfad = await self._kamera.referenz_speichern()
        except Exception as error:  # noqa: BLE001
            return ToolResult.failure(f"Die Webcam liess sich nicht nutzen: {error}")
        return ToolResult.success(
            "Ich habe mir dein Gesicht gemerkt. Das Foto liegt nur auf diesem "
            f"Rechner ({pfad.name}).",
        )
