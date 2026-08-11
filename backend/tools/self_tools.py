"""Werkzeuge, mit denen AI-Orb an sich selbst arbeitet.

Drei Fähigkeiten, die zusammengehören: den eigenen Quellcode lesen, ihn
ändern – und sich danach neu starten, damit die Änderung überhaupt gilt.
Ohne den letzten Schritt wäre der zweite folgenlos: Python liest eine
Moduldatei genau einmal, beim Import. Wer eine Zeile ändert und nichts
weiter tut, hat eine Datei geändert, aber kein Programm.

Die Maschinerie dafür gab es längst (``backend/evolution``): Patches,
Prüfungen, Wiederherstellungspunkte. Sie war nur nie als Werkzeug
angeschlossen, also für den Orb unerreichbar – er *konnte* an sich
arbeiten, aber niemand hatte ihm gesagt, wie.

Die Sicherheitsnetze, in der Reihenfolge, in der sie greifen:

Vor jeder Änderung entsteht ein Wiederherstellungspunkt mit der alten
Fassung. Er wird angelegt, bevor irgendetwas geschrieben wird – nicht
danach, denn ein Netz, das nach dem Sprung gespannt wird, ist keines.

Nach dem Schreiben wird die Datei übersetzt. Ein Syntaxfehler in einer
Kerndatei bedeutet, dass der Orb beim nächsten Start nicht mehr hochkommt
und niemand mehr da wäre, der ihn zurücksetzen könnte. Scheitert die
Übersetzung, wird die alte Fassung sofort wiederhergestellt und der
Versuch gemeldet.

Und zurücknehmen lässt sich jede Änderung, auch eine syntaktisch
einwandfreie, die sich als schlechte Idee erweist.

Was hier bewusst NICHT geschieht: Es wird nichts heimlich geändert. Jede
Änderung steht im Prüfprotokoll, und der Orb sagt vorher, was er vorhat.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult
from backend.utils.paths import get_data_dir, get_project_root

logger = get_logger(__name__)

#: Dateien, die AI-Orb nicht an sich selbst ändert.
#:
#: Nicht aus Prinzip, sondern weil ein Fehler darin nicht mehr zu heilen
#: wäre: Wer die Sicherheitsschicht oder den Wiederherstellungsweg kaputt
#: macht, hat kein Werkzeug mehr, um das rückgängig zu machen.
_GESPERRT: tuple[str, ...] = (
    "backend/security/",
    "backend/evolution/rollback_manager.py",
    "backend/tools/self_tools.py",
)

#: Nur Quelldateien. Eine .exe oder ein Modell ist kein „eigener Code".
_ERLAUBTE_ENDUNGEN: frozenset[str] = frozenset(
    {".py", ".yaml", ".yml", ".json", ".md", ".ts", ".css", ".html", ".glsl"}
)


def _relativ(pfad: Path) -> str:
    """Der Pfad relativ zum Programmordner, mit Schrägstrichen."""

    return pfad.relative_to(get_project_root()).as_posix()


def _im_programm(kandidat: str) -> tuple[Path | None, str]:
    """Löst einen Pfad innerhalb des Programmordners auf.

    Returns:
        Den Pfad und eine leere Begründung – oder ``None`` und den Grund.
    """

    wurzel = get_project_root()
    roh = Path(os.path.expanduser(kandidat))

    try:
        pfad = (roh if roh.is_absolute() else wurzel / roh).resolve()
    except (OSError, RuntimeError, ValueError):
        return None, f"Der Pfad ist ungültig: {kandidat}"

    if wurzel not in pfad.parents and pfad != wurzel:
        return None, (
            f"'{kandidat}' liegt nicht im Programmordner von AI-Orb "
            f"({wurzel}). Für andere Dateien ist 'datei_schreiben' da."
        )

    if pfad.suffix.lower() not in _ERLAUBTE_ENDUNGEN:
        endung = pfad.suffix or "ohne Endung"
        return None, (
            f"Dateien vom Typ '{endung}' gehören nicht zum Quellcode und "
            "werden hier nicht angefasst."
        )

    relativ = _relativ(pfad)
    for gesperrt in _GESPERRT:
        if relativ == gesperrt or relativ.startswith(gesperrt):
            return None, (
                f"'{relativ}' ist von Selbstaenderungen ausgenommen. Ein "
                "Fehler darin liesse sich nicht mehr zurücknehmen – die "
                "Sicherheitsschicht und der Weg zurück müssen unangetastet "
                "bleiben. Sag mir, was du ändern möchtest, dann sehen wir "
                "es uns gemeinsam an."
            )

    return pfad, ""


class ReadOwnCodeTool(Tool):
    """Liest eine Datei des eigenen Quellcodes."""

    name = "eigenen_code_lesen"
    description = (
        "Liest eine Datei aus dem eigenen Programmordner – zum Beispiel "
        "'backend/voice/voice_pipeline.py'. Der Pfad darf relativ zum "
        "Programmordner angegeben werden. Benutze das, bevor du etwas an "
        "dir selbst änderst: Ohne den jetzigen Stand zu kennen, ist jede "
        "Änderung geraten."
    )
    permission = "modify_own_code"
    parameters = (
        ToolParameter("pfad", "string", "Die Datei, relativ zum Programmordner."),
        ToolParameter(
            "von_zeile",
            "integer",
            "Ab welcher Zeile gelesen wird (1 = Anfang).",
            required=False,
            default=1,
        ),
        ToolParameter(
            "zeilen",
            "integer",
            "Wie viele Zeilen höchstens gelesen werden.",
            required=False,
            default=200,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pfad, grund = _im_programm(str(arguments["pfad"]))
        if pfad is None:
            return ToolResult.failure(grund)
        if not pfad.is_file():
            return ToolResult.failure(f"Die Datei gibt es nicht: {_relativ(pfad)}")

        try:
            alle = pfad.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as fehler:
            return ToolResult.failure(f"Die Datei ließ sich nicht lesen: {fehler}")

        beginn = max(1, int(arguments.get("von_zeile", 1)))
        anzahl = max(1, min(2000, int(arguments.get("zeilen", 200))))
        ausschnitt = alle[beginn - 1 : beginn - 1 + anzahl]

        if not ausschnitt:
            return ToolResult.failure(
                f"Ab Zeile {beginn} steht nichts mehr; die Datei hat "
                f"{len(alle)} Zeilen."
            )

        # Mit Zeilennummern: Wer gleich etwas ändern will, muss sagen
        # können, wo.
        text = "\n".join(
            f"{beginn + versatz:5d}  {zeile}" for versatz, zeile in enumerate(ausschnitt)
        )
        return ToolResult.success(
            f"{_relativ(pfad)} (Zeilen {beginn} bis {beginn + len(ausschnitt) - 1} "
            f"von {len(alle)}):\n{text}",
            path=_relativ(pfad),
            total_lines=len(alle),
        )


class ChangeOwnCodeTool(Tool):
    """Ändert eine Datei des eigenen Quellcodes."""

    name = "eigenen_code_aendern"
    description = (
        "Ändert eine Datei im eigenen Programmordner und legt vorher eine "
        "Sicherung an. Der neue Inhalt ersetzt die Datei vollständig – lies "
        "sie also zuerst mit 'eigenen_code_lesen'. Python-Dateien werden "
        "nach dem Schreiben übersetzt; ist die Syntax kaputt, wird die "
        "alte Fassung sofort zurückgeholt. Die Änderung gilt erst nach "
        "einem Neustart ('neu_starten')."
    )
    permission = "modify_own_code"
    parameters = (
        ToolParameter("pfad", "string", "Die Datei, relativ zum Programmordner."),
        ToolParameter("inhalt", "string", "Der vollständige neue Inhalt der Datei."),
        ToolParameter(
            "begruendung",
            "string",
            "Warum diese Änderung – in einem Satz, für das Protokoll.",
        ),
    )

    def __init__(self, rollback: Any) -> None:
        """
        Args:
            rollback: Der Wiederherstellungsverwalter aus der Evolution
                Engine. Er legt die Sicherung an und holt sie zurück.
        """

        self._rollback = rollback

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pfad, grund = _im_programm(str(arguments["pfad"]))
        if pfad is None:
            return ToolResult.failure(grund)

        inhalt = str(arguments["inhalt"])
        begruendung = str(arguments.get("begruendung", "")).strip() or "ohne Angabe"
        relativ = _relativ(pfad)
        neu = not pfad.exists()

        # Zuerst übersetzen, dann schreiben. Ein Syntaxfehler soll die
        # Datei gar nicht erst erreichen – das nachträgliche Zurückholen
        # ist die zweite Verteidigungslinie, nicht die erste.
        if pfad.suffix.lower() == ".py":
            fehler = _syntaxfehler(inhalt, relativ)
            if fehler:
                return ToolResult.failure(
                    f"Die Änderung wurde nicht geschrieben: {fehler}"
                )

        punkt = None
        if not neu:
            try:
                punkt = self._rollback.create_point(
                    patch_id="selbst",
                    title=f"Selbstaenderung an {relativ}",
                    description=begruendung,
                    branch="",
                    commit="",
                    version="",
                    files=[relativ],
                )
            except Exception as fehler:  # noqa: BLE001
                logger.exception("Der Wiederherstellungspunkt scheiterte.")
                return ToolResult.failure(
                    "Ich konnte keine Sicherung anlegen und ändere deshalb "
                    f"nichts an mir selbst: {fehler}"
                )

        try:
            pfad.parent.mkdir(parents=True, exist_ok=True)
            pfad.write_text(inhalt, encoding="utf-8")
        except OSError as fehler:
            return ToolResult.failure(f"Die Datei ließ sich nicht schreiben: {fehler}")

        logger.info(
            "Selbstaenderung an %s (%s). Wiederherstellungspunkt: %s",
            relativ,
            begruendung,
            getattr(punkt, "id", "keiner – neue Datei"),
        )

        hinweis = (
            "Die Änderung gilt erst nach einem Neustart – Python liest eine "
            "Moduldatei nur beim Start."
        )
        rueckweg = (
            "Zurücknehmen kannst du sie mit 'letzte_selbstaenderung_zuruecknehmen'."
            if punkt is not None
            else "Die Datei war neu; es gibt nichts, wohin zurückzukehren wäre."
        )

        return ToolResult.success(
            f"{'Angelegt' if neu else 'Geändert'}: {relativ} "
            f"({len(inhalt.splitlines())} Zeilen). Grund: {begruendung}. "
            f"{hinweis} {rueckweg}",
            path=relativ,
            restore_point=getattr(punkt, "id", ""),
            needs_restart=True,
        )


class UndoOwnChangeTool(Tool):
    """Nimmt die letzte Selbständerung zurück."""

    name = "letzte_selbstaenderung_zuruecknehmen"
    description = (
        "Holt die Fassung von vor der letzten Änderung am eigenen Code "
        "zurück. Auch dafür ist danach ein Neustart nötig."
    )
    permission = "modify_own_code"
    parameters = ()

    def __init__(self, rollback: Any) -> None:
        self._rollback = rollback

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            bericht = self._rollback.undo_last()
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Das Zurücknehmen ist gescheitert.")
            return ToolResult.failure(f"Zurücknehmen gescheitert: {fehler}")

        if not bericht.get("restored"):
            return ToolResult.failure(str(bericht.get("message", "Nichts zurückgenommen.")))

        return ToolResult.success(
            str(bericht.get("message", "Zurückgenommen."))
            + " Damit es gilt, starte mich neu.",
            files=bericht.get("restored_files", []),
            needs_restart=True,
        )


class RestartTool(Tool):
    """Startet AI-Orb neu."""

    name = "neu_starten"
    description = (
        "Startet AI-Orb neu. Nötig, nachdem am eigenen Code etwas geändert "
        "wurde – vorher gilt die Änderung nicht. Sag vorher, dass du dich "
        "gleich neu startest, sonst wirkt es wie ein Absturz."
    )
    permission = "system_commands"
    parameters = (
        ToolParameter(
            "grund",
            "string",
            "Warum neu gestartet wird – für das Protokoll.",
            required=False,
            default="auf Wunsch",
        ),
    )

    def __init__(self, neustart: Any) -> None:
        """
        Args:
            neustart: Etwas mit ``anfordern(grund)``. In der Regel der
                Neustarter aus :mod:`backend.system.restart`.
        """

        self._neustart = neustart

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        grund = str(arguments.get("grund", "auf Wunsch"))
        ok, meldung = self._neustart.anfordern(grund)
        if not ok:
            return ToolResult.failure(meldung)
        return ToolResult.success(meldung, restarting=True)


def _syntaxfehler(quelltext: str, name: str) -> str:
    """Prüft Python-Quelltext und beschreibt den Fehler im Klartext."""

    try:
        ast.parse(quelltext, filename=name)
    except SyntaxError as fehler:
        return (
            f"In {name}, Zeile {fehler.lineno or '?'}: {fehler.msg}. "
            "So gespeichert käme ich beim nächsten Start nicht mehr hoch."
        )
    except ValueError as fehler:
        return f"{name} ließ sich nicht übersetzen: {fehler}"
    return ""


def build_self_tools(*, rollback: Any, neustart: Any) -> list[Tool]:
    """Stellt die Werkzeuge zur Selbstarbeit zusammen."""

    return [
        ReadOwnCodeTool(),
        ChangeOwnCodeTool(rollback),
        UndoOwnChangeTool(rollback),
        RestartTool(neustart),
    ]
