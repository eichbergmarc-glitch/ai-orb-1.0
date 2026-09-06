"""Die Werkzeuge zum Tagebuch - schreiben, nachsehen, aufschlagen, streichen.

Der Weg des Diktats: Der Benutzer sagt "Orb, neuer Tagebucheintrag: ..."
- das Sprachmodell reicht den Wortlaut an ``tagebuch_schreiben`` weiter,
und zwar UNVERÄNDERT. Die Beschreibung der Werkzeuge sagt das
ausdrücklich, denn ein Tagebuch, das die Maschine glättet, gehört nicht
mehr dem, der es führt.
"""

from __future__ import annotations

from typing import Any

from backend.system.logging_setup import get_logger
from backend.tagebuch import Tagebuch, TagebuchFehler, _datum_lang
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


class TagebuchSchreiben(Tool):
    """Nimmt einen diktierten Eintrag wortgetreu auf."""

    name = "tagebuch_schreiben"
    description = (
        "Traegt einen vom Benutzer diktierten Eintrag in sein Tagebuch ein. "
        "Benutze das, sobald der Benutzer einen Tagebucheintrag diktiert "
        "('neuer Tagebucheintrag', 'schreib in mein Tagebuch', 'notier im "
        "Tagebuch'). Gib den Wortlaut UNVERAENDERT weiter - nicht "
        "zusammenfassen, nicht umformulieren, nicht verschoenern; nur das "
        "Vorgeplaenkel ('schreib ins Tagebuch:') weglassen. Absaetze kannst "
        "du mit ' | ' trennen. Der Eintrag bekommt Datum und Uhrzeit von "
        "selbst."
    )
    parameters = (
        ToolParameter("text", "string", "Der diktierte Eintrag im Wortlaut."),
        ToolParameter(
            "titel", "string",
            "Eine Ueberschrift, falls der Benutzer eine nennt.",
            required=False, default="",
        ),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            eintrag = self._tagebuch.eintragen(
                str(arguments.get("text", "") or ""),
                titel=str(arguments.get("titel", "") or ""),
            )
        except TagebuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        return ToolResult.success(
            f"Eingetragen unter {_datum_lang(eintrag.zeitpunkt)}, "
            f"{eintrag.zeitpunkt.strftime('%H:%M')} Uhr. Das Buch liegt als "
            f"Datei unter {self._tagebuch.ansicht} (Verknüpfung 'Tagebuch' "
            "auf dem Desktop) - der Benutzer kann es jederzeit selbst "
            "aufschlagen. Sag ihm kurz, dass es steht - lies ihm den "
            "Eintrag nicht noch einmal vor. War es ein Versehen: 'streich "
            "den letzten Eintrag'.",
            zeit=eintrag.zeit,
            datei=str(self._tagebuch.ansicht),
        )


class TagebuchZeigen(Tool):
    """Schlaegt das Tagebuch auf dem Bildschirm auf."""

    name = "tagebuch_zeigen"
    description = (
        "Oeffnet das Tagebuch des Benutzers als EIGENES App-Fenster ('zeig "
        "mir mein Tagebuch', 'oeffne meine Tagebuch-App'). Die diktierten "
        "Eintraege stehen darin in gesetzter Computerschrift, die "
        "juengsten oben - keine Handschrift, kein Browser-Drumherum. Mit "
        "als='pdf' oeffnet stattdessen die stets aktuelle PDF-Fassung "
        "(die liesse sich z.B. in Microsoft Journal importieren; direkt "
        "hineinschreiben kann in Journal kein Programm, die App hat "
        "dafuer keine Schnittstelle)."
    )
    parameters = (
        ToolParameter(
            "als", "string",
            "'buch' (Browser, Standard) oder 'pdf' (PDF-Fassung, auch fuer "
            "Microsoft Journal).",
            required=False, default="buch",
        ),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import asyncio

        als = str(arguments.get("als", "buch") or "buch").strip().lower()
        if als in ("pdf", "journal", "microsoft journal"):
            try:
                self._tagebuch.pdf.parent.mkdir(parents=True, exist_ok=True)
                self._tagebuch.pdf.write_bytes(self._tagebuch.als_pdf_bytes())
            except Exception as fehler:  # noqa: BLE001
                return ToolResult.failure(f"Die PDF liess sich nicht bauen: {fehler}")
            geoeffnet = await asyncio.to_thread(
                _im_browser_oeffnen, self._tagebuch.pdf
            )
            if not geoeffnet:
                return ToolResult.failure(
                    f"Die PDF liegt unter {self._tagebuch.pdf}, liess sich "
                    "aber nicht oeffnen. Sag dem Benutzer den Pfad."
                )
            return ToolResult.success(
                f"Die PDF-Fassung ist geoeffnet ({len(self._tagebuch.eintraege)} "
                "Eintraege). Wer sie in Microsoft Journal weiterfuehren will: "
                f"dort 'Importieren' waehlen und {self._tagebuch.pdf} angeben."
            )
        try:
            # Frisch schreiben, damit die Ansicht sicher den letzten Stand
            # traegt - auch wenn sie zwischendurch geloescht wurde.
            self._tagebuch.ansicht.parent.mkdir(parents=True, exist_ok=True)
            self._tagebuch.ansicht.write_text(
                self._tagebuch.als_html(), encoding="utf-8"
            )
        except OSError as fehler:
            return ToolResult.failure(f"Die Ansicht liess sich nicht schreiben: {fehler}")
        geoeffnet = await asyncio.to_thread(_im_browser_oeffnen, self._tagebuch.ansicht)
        if not geoeffnet:
            return ToolResult.failure(
                f"Das Tagebuch liegt unter {self._tagebuch.ansicht}, aber der "
                "Browser liess sich nicht oeffnen. Sag dem Benutzer den Pfad."
            )
        anzahl = len(self._tagebuch.eintraege)
        return ToolResult.success(
            f"Das Tagebuch ist aufgeschlagen ({anzahl} Eintraege, die "
            f"juengsten oben). Es liegt als Datei unter "
            f"{self._tagebuch.ansicht} und laesst sich dort jederzeit auch "
            "ohne den Orb oeffnen."
            + (
                " Es ist noch leer - der Benutzer kann einfach einen "
                "Eintrag diktieren."
                if anzahl == 0
                else ""
            )
        )


class TagebuchTitelblatt(Tool):
    """Setzt die Zeile auf dem Titelblatt des Buches."""

    name = "tagebuch_titelblatt"
    description = (
        "Setzt die Titelblatt-Zeile des Tagebuchs - Name und Jahr, z.B. "
        "'Daniel Peter Glor, 2026'. Benutze es, wenn der Benutzer sagt, "
        "was auf dem Titelblatt stehen soll. Der Buchtitel selbst bleibt "
        "'Tagebuch'."
    )
    parameters = (
        ToolParameter("text", "string", "Die Zeile fuer das Titelblatt."),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            gesetzt = self._tagebuch.titelblatt_setzen(
                str(arguments.get("text", "") or "")
            )
        except TagebuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        if not gesetzt:
            return ToolResult.success("Das Titelblatt traegt jetzt keine Zusatzzeile mehr.")
        return ToolResult.success(f"Auf dem Titelblatt steht jetzt: {gesetzt}.")


class TagebuchNachsehen(Tool):
    """Liest im Tagebuch nach - fuers Vorlesen und Erinnern."""

    name = "tagebuch_nachsehen"
    description = (
        "Holt die juengsten Tagebucheintraege als Text - zum Vorlesen oder "
        "um eine Frage wie 'was habe ich letzte Woche geschrieben?' zu "
        "beantworten. Mit 'suchwort' nur Eintraege, die es enthalten. "
        "Zitiere woertlich; es sind die Worte des Benutzers."
    )
    parameters = (
        ToolParameter(
            "suchwort", "string", "Nur Eintraege mit diesem Wort.",
            required=False, default="",
        ),
        ToolParameter(
            "anzahl", "integer", "Wie viele hoechstens (1 bis 20).",
            required=False, default=5,
        ),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            anzahl = max(1, min(int(arguments.get("anzahl", 5) or 5), 20))
        except (TypeError, ValueError):
            anzahl = 5
        suchwort = str(arguments.get("suchwort", "") or "")
        gefunden = self._tagebuch.nachsehen(suchwort=suchwort, hoechstens=anzahl)
        if not gefunden:
            return ToolResult.success(
                "Kein Eintrag"
                + (f" mit {suchwort!r}" if suchwort.strip() else "")
                + " im Tagebuch - auch das ist eine Auskunft."
            )
        zeilen = []
        for e in gefunden:
            kopf = f"{_datum_lang(e.zeitpunkt)}, {e.zeitpunkt.strftime('%H:%M')} Uhr"
            if e.titel:
                kopf += f" - {e.titel}"
            zeilen.append(f"{kopf}:\n{e.text}")
        return ToolResult.success(
            f"{len(gefunden)} Eintrag/Eintraege (die juengsten zuerst):\n\n"
            + "\n\n".join(zeilen)
        )


class TagebuchStreichen(Tool):
    """Entfernt den letzten oder einen eindeutig beschriebenen Eintrag."""

    name = "tagebuch_streichen"
    description = (
        "Entfernt einen Tagebucheintrag auf ausdruecklichen Wunsch. Ohne "
        "Beschreibung wird der juengste Eintrag entfernt. Mit 'suchtext' "
        "wird der juengste Eintrag entfernt, dessen Titel oder Text diese "
        "Woerter enthaelt."
    )
    parameters = (
        ToolParameter(
            "suchtext", "string",
            "Woerter aus dem zu entfernenden Eintrag; leer bedeutet letzter Eintrag.",
            required=False, default="",
        ),
        ToolParameter(
            "position", "string", "'letzter' oder 'erster'.",
            required=False, default="letzter",
        ),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            suchtext = str(arguments.get("suchtext", "") or "").strip()
            eintrag = self._tagebuch.eintrag_streichen(
                suchtext,
                position=str(arguments.get("position", "letzter") or "letzter"),
            )
        except TagebuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        if eintrag is None:
            return ToolResult.failure(
                "Kein passender Tagebucheintrag gefunden."
                if suchtext else "Das Tagebuch ist leer - nichts zu streichen."
            )
        anfang = eintrag.text[:60] + ("..." if len(eintrag.text) > 60 else "")
        return ToolResult.success(
            f"Gestrichen: der Eintrag von "
            f"{eintrag.zeitpunkt.strftime('%H:%M')} Uhr ({anfang!r})."
        )


class TagebuchAendern(Tool):
    """Ersetzt, ergänzt oder kürzt einen vorhandenen Tagebucheintrag."""

    name = "tagebuch_aendern"
    description = (
        "Aendert einen vorhandenen Tagebucheintrag auf ausdruecklichen Wunsch. "
        "Moegliche Modi: 'ersetzen_gesamt', 'anhaengen', 'ersetzen' und "
        "'entfernen'. Der Wortlaut in text/alt/neu muss unveraendert bleiben."
    )
    parameters = (
        ToolParameter("modus", "string", "Art der Änderung."),
        ToolParameter("text", "string", "Neue Gesamtfassung, Ergänzung oder zu entfernender Text.", required=False, default=""),
        ToolParameter("alt", "string", "Bisheriger Wortlaut.", required=False, default=""),
        ToolParameter("neu", "string", "Neuer Wortlaut.", required=False, default=""),
        ToolParameter("suchtext", "string", "Beschreibung, Datum oder Uhrzeit des Eintrags.", required=False, default=""),
        ToolParameter("position", "string", "'letzter' oder 'erster'.", required=False, default="letzter"),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            eintrag = self._tagebuch.eintrag_aendern(
                modus=str(arguments.get("modus", "") or ""),
                text=str(arguments.get("text", "") or ""),
                alt=str(arguments.get("alt", "") or ""),
                neu=str(arguments.get("neu", "") or ""),
                suchtext=str(arguments.get("suchtext", "") or ""),
                position=str(arguments.get("position", "letzter") or "letzter"),
            )
        except TagebuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        return ToolResult.success(
            "Der Tagebucheintrag wurde geändert.",
            zeit=eintrag.zeit,
            datei=str(self._tagebuch.ansicht),
        )


class TagebuchBildEinfuegen(Tool):
    """Fuegt eine lokale Bilddatei dauerhaft beim juengsten Eintrag ein."""

    name = "tagebuch_bild_einfuegen"
    description = (
        "Fuegt ein zuvor gesuchtes und vom Benutzer ausgewaehltes Bild in "
        "den juengsten Tagebucheintrag ein. Der Bildnachweis muss mitgegeben werden."
    )
    parameters = (
        ToolParameter("pfad", "string", "Lokaler Pfad des ausgewählten Bildes."),
        ToolParameter(
            "nachweis", "string", "Urheber- und Lizenznachweis.",
            required=False, default="",
        ),
    )

    def __init__(self, tagebuch: Tagebuch) -> None:
        self._tagebuch = tagebuch

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            eintrag = self._tagebuch.bild_einfuegen(
                str(arguments.get("pfad", "") or ""),
                nachweis=str(arguments.get("nachweis", "") or ""),
            )
        except TagebuchFehler as fehler:
            return ToolResult.failure(str(fehler))
        return ToolResult.success(
            "Das ausgewählte Bild wurde in den jüngsten Tagebucheintrag eingefügt.",
            zeit=eintrag.zeit,
            datei=str(self._tagebuch.ansicht),
        )


def _im_browser_oeffnen(pfad) -> bool:
    """Oeffnet das Tagebuch als EIGENES App-Fenster - in Computerschrift.

    Der Benutzer will "eine Tagebuch-App, die die Texte, die ich diktiere,
    in Computerschrift schreibt, nicht in Handschrift" (23.08.2026). Genau
    das ist der App-Modus von Edge: ein rahmenloses, eigenstaendiges
    Fenster mit eigenem Eintrag in der Taskleiste - keine Tabs, keine
    Adressleiste, nur das Buch. Der Text darin ist gesetzte Schrift, keine
    Handschrift. Faellt Edge aus, oeffnet der Standardbrowser - besser ein
    Tab als gar kein Tagebuch. PDFs gehen immer an die Standard-App.
    """

    import os
    import subprocess
    import webbrowser

    ziel = f"file:///{str(pfad).lstrip('/')}"
    if str(pfad).lower().endswith((".html", ".htm")):
        for roh in (
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe",
        ):
            edge = os.path.expandvars(roh)
            if "%" not in edge and os.path.isfile(edge):
                try:
                    subprocess.Popen([edge, f"--app={ziel}"])
                    return True
                except OSError:
                    logger.exception("Das App-Fenster liess sich nicht oeffnen.")
                break
    try:
        return webbrowser.open(ziel, new=2)
    except Exception:  # noqa: BLE001
        logger.exception("Das Tagebuch liess sich nicht oeffnen.")
        return False


def build_tagebuch_tools(tagebuch: Tagebuch) -> list[Tool]:
    return [
        TagebuchSchreiben(tagebuch),
        TagebuchZeigen(tagebuch),
        TagebuchTitelblatt(tagebuch),
        TagebuchNachsehen(tagebuch),
        TagebuchStreichen(tagebuch),
        TagebuchAendern(tagebuch),
        TagebuchBildEinfuegen(tagebuch),
    ]
