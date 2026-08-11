"""Werkzeuge zum Anlegen und Ändern von Dateien.

Bisher konnte AI-Orb Dateien lesen, auflisten und suchen – aber keine
einzige schreiben. „Schreib mir das in eine Textdatei" endete deshalb
damit, dass der Orb den Text vorlas und die Datei nirgends entstand.

Diese Werkzeuge schliessen die Lücke. Sie folgen dabei denselben Regeln
wie alle anderen: Sie entscheiden nie selbst, ob sie etwas dürfen, sondern
nennen ihre Berechtigung und lassen die Sicherheitsschicht befinden. Der
Pfad läuft zusätzlich durch die Pfadprüfung.

Zwei Entscheidungen sind bewusst so getroffen:

Anhängen statt Überschreiben ist die *ausdrückliche* Wahl, nicht die
Vorgabe. Wer „schreib das in meine Notizen" sagt, meint fast immer
„ergänze" – aber ein Werkzeug, das rät, löscht irgendwann etwas, das
jemand behalten wollte. Deshalb gibt es dafür einen eigenen Schalter.

Und eine bestehende Datei wird nur überschrieben, wenn das ausdrücklich
verlangt wird. Ein vertippter Dateiname darf keine Arbeit vernichten.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

#: Obergrenze für einen einzelnen Schreibvorgang.
#:
#: Kein Sicherheitsnetz gegen Angriffe, sondern gegen Versehen: Ein Modell,
#: das sich in einer Schleife verliert, soll nicht die Platte füllen.
_MAX_CHARACTERS = 2_000_000


class WriteFileTool(Tool):
    """Legt eine Textdatei an oder ändert sie."""

    name = "datei_schreiben"
    description = (
        "Legt eine Textdatei an und schreibt Inhalt hinein – zum Beispiel "
        "eine Notiz, eine Liste, ein Protokoll oder ein Skript. Fehlende "
        "Ordner werden angelegt. Eine bestehende Datei wird nur "
        "überschrieben, wenn 'ueberschreiben' auf true steht; mit "
        "'anhaengen' wird stattdessen unten angefügt. Benutze dieses "
        "Werkzeug immer, wenn etwas als Datei gespeichert werden soll."
    )
    permission = "write_files"
    parameters = (
        ToolParameter(
            "pfad",
            "string",
            "Der vollständige Pfad der Datei, zum Beispiel "
            "C:\\Users\\info\\Desktop\\notiz.txt",
        ),
        ToolParameter("inhalt", "string", "Der Text, der hineingeschrieben wird."),
        ToolParameter(
            "ueberschreiben",
            "boolean",
            "Ob eine bereits vorhandene Datei ersetzt werden darf.",
            required=False,
            default=False,
        ),
        ToolParameter(
            "anhaengen",
            "boolean",
            "Ob der Text unten angefügt statt ersetzt werden soll.",
            required=False,
            default=False,
        ),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        inhalt = str(arguments.get("inhalt", ""))
        if len(inhalt) > _MAX_CHARACTERS:
            return ToolResult.failure(
                f"Der Text ist mit {len(inhalt)} Zeichen zu lang für einen "
                f"Schreibvorgang (Grenze: {_MAX_CHARACTERS})."
            )

        entscheidung = self._security.paths.check_write(str(arguments["pfad"]))
        if not entscheidung.allowed:
            return ToolResult.failure(entscheidung.reason)

        pfad: Path = entscheidung.path
        anhaengen = bool(arguments.get("anhaengen", False))
        ueberschreiben = bool(arguments.get("ueberschreiben", False))

        if pfad.is_dir():
            return ToolResult.failure(
                f"'{pfad}' ist ein Ordner, keine Datei. Gib einen Dateinamen an."
            )

        vorhanden = pfad.exists()
        if vorhanden and not (ueberschreiben or anhaengen):
            return ToolResult.failure(
                f"Die Datei '{pfad}' gibt es bereits. Setze 'ueberschreiben' auf "
                "true, um sie zu ersetzen, oder 'anhaengen' auf true, um unten "
                "etwas anzufügen."
            )

        try:
            pfad.parent.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            return ToolResult.failure(f"Der Ordner ließ sich nicht anlegen: {fehler}")

        try:
            if anhaengen and vorhanden:
                # Der Text soll unten stehen und nicht an das letzte Wort
                # kleben – ein Zeilenumbruch dazwischen, wenn keiner da ist.
                bisher = pfad.read_text(encoding="utf-8", errors="replace")
                trenner = "" if not bisher or bisher.endswith("\n") else "\n"
                pfad.write_text(bisher + trenner + inhalt, encoding="utf-8")
                tat = "ergänzt"
            else:
                pfad.write_text(inhalt, encoding="utf-8")
                tat = "ersetzt" if vorhanden else "angelegt"
        except OSError as fehler:
            return ToolResult.failure(f"Die Datei ließ sich nicht schreiben: {fehler}")

        try:
            groesse = pfad.stat().st_size
        except OSError:
            groesse = len(inhalt.encode("utf-8"))

        logger.info("Datei %s: %s (%d Bytes).", tat, pfad, groesse)
        return ToolResult.success(
            f"Die Datei wurde {tat}: {pfad} ({groesse} Bytes, "
            f"{inhalt.count(chr(10)) + 1} Zeilen).",
            path=str(pfad),
            bytes=groesse,
            action=tat,
        )


class CreateDirectoryTool(Tool):
    """Legt einen Ordner an."""

    name = "ordner_anlegen"
    description = (
        "Legt einen Ordner an, samt aller darüberliegenden Ordner. Gibt es "
        "ihn schon, ist das kein Fehler."
    )
    permission = "write_files"
    parameters = (
        ToolParameter("pfad", "string", "Der vollständige Pfad des neuen Ordners."),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        entscheidung = self._security.paths.check_write(str(arguments["pfad"]))
        if not entscheidung.allowed:
            return ToolResult.failure(entscheidung.reason)

        pfad: Path = entscheidung.path
        if pfad.is_file():
            return ToolResult.failure(f"'{pfad}' ist bereits eine Datei.")

        schon_da = pfad.is_dir()
        try:
            pfad.mkdir(parents=True, exist_ok=True)
        except OSError as fehler:
            return ToolResult.failure(f"Der Ordner ließ sich nicht anlegen: {fehler}")

        return ToolResult.success(
            f"Der Ordner gab es bereits: {pfad}"
            if schon_da
            else f"Der Ordner wurde angelegt: {pfad}",
            path=str(pfad),
            created=not schon_da,
        )


def build_file_tools(security: SecurityEngine) -> list[Tool]:
    """Stellt die Schreibwerkzeuge zusammen."""

    return [WriteFileTool(security), CreateDirectoryTool(security)]
