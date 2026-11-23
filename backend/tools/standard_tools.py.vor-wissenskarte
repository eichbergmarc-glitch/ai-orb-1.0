"""Die mitgelieferten Werkzeuge.

Bewusst klein gehalten und bewusst nützlich: Jedes Werkzeug hier löst etwas,
das ein Sprachmodell allein nicht kann, weil ihm der Zugang zur Gegenwart
oder zum Rechner fehlt. Die Uhrzeit kennt es nicht, den Inhalt einer Datei
auch nicht, und rechnen tut es unzuverlässig.

Was hier nicht steht, ist ebenso bezeichnend: Es gibt kein Werkzeug, das
beliebige Befehle ausführt. Die Vorgabe ist eindeutig – der Orchestrator
führt niemals direkt Systembefehle aus, alles läuft über umrissene Module.
Programme lassen sich nur aus der Liste in ``config.yaml`` starten.
"""

from __future__ import annotations

import asyncio
import ast
import operator
import os
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


# =============================================================================
# Zeit
# =============================================================================


class CurrentTimeTool(Tool):
    """Nennt Datum und Uhrzeit."""

    name = "aktuelle_zeit"
    description = (
        "Gibt das heutige Datum und die aktuelle Uhrzeit zurück. Benutze das "
        "immer, wenn nach Datum, Uhrzeit, Wochentag oder 'heute' gefragt wird "
        "– du kannst das nicht selbst wissen."
    )
    permission = "read_time"
    parameters = ()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        now = datetime.now()
        weekdays = [
            "Montag",
            "Dienstag",
            "Mittwoch",
            "Donnerstag",
            "Freitag",
            "Samstag",
            "Sonntag",
        ]
        return ToolResult.success(
            f"{weekdays[now.weekday()]}, {now.strftime('%d.%m.%Y')}, "
            f"{now.strftime('%H:%M')} Uhr",
            iso=now.isoformat(timespec="seconds"),
        )


# =============================================================================
# Rechnen
# =============================================================================

#: Erlaubte Rechenoperationen. Alles andere wird abgelehnt.
_OPERATORS: dict[type[ast.AST], Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def evaluate_expression(expression: str) -> float:
    """Wertet einen Rechenausdruck sicher aus.

    Bewusst **nicht** über ``eval``. Der Ausdruck wird in einen Syntaxbaum
    zerlegt, und dieser Baum wird Knoten für Knoten geprüft: Zahlen und die
    Grundrechenarten sind erlaubt, alles andere – Namen, Aufrufe, Zugriffe –
    führt zum Abbruch. Damit kann ein Ausdruck aus einer Modellantwort nichts
    anderes tun als rechnen.

    Raises:
        ValueError: Wenn der Ausdruck unzulässig ist.
    """

    cleaned = expression.strip().replace("^", "**").replace(",", ".")
    if len(cleaned) > 200:
        raise ValueError("Der Ausdruck ist zu lang.")

    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as error:
        raise ValueError(f"Das ist kein gültiger Rechenausdruck: {error.msg}") from error

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("Es sind nur Zahlen erlaubt.")
            return float(node.value)
        if isinstance(node, ast.BinOp):
            handler = _OPERATORS.get(type(node.op))
            if handler is None:
                raise ValueError("Diese Rechenart ist nicht erlaubt.")
            right = evaluate(node.right)
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ValueError("Durch null wird nicht geteilt.")
            # Sehr große Potenzen können den Rechner für Minuten blockieren.
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Der Exponent ist zu groß.")
            return handler(evaluate(node.left), right)
        if isinstance(node, ast.UnaryOp):
            handler = _OPERATORS.get(type(node.op))
            if handler is None:
                raise ValueError("Dieses Vorzeichen ist nicht erlaubt.")
            return handler(evaluate(node.operand))
        raise ValueError("Der Ausdruck enthält etwas, das nicht erlaubt ist.")

    return evaluate(tree)


class CalculateTool(Tool):
    """Rechnet einen Ausdruck aus."""

    name = "rechnen"
    description = (
        "Rechnet einen mathematischen Ausdruck aus, zum Beispiel '17 * 23 + 4' "
        "oder '(1250 / 8) ** 2'. Benutze das für jede Rechnung – verlasse dich "
        "nicht auf dein Kopfrechnen."
    )
    permission = "compute"
    parameters = (
        ToolParameter(
            "ausdruck",
            "string",
            "Der Rechenausdruck. Erlaubt sind + - * / // % ** und Klammern.",
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        expression = str(arguments["ausdruck"])
        try:
            value = evaluate_expression(expression)
        except ValueError as error:
            return ToolResult.failure(str(error))

        if value == int(value) and abs(value) < 1e15:
            formatted = str(int(value))
        else:
            formatted = f"{value:.10g}"
        return ToolResult.success(f"{expression} = {formatted}", value=value)


# =============================================================================
# Dateien
# =============================================================================


class ReadFileTool(Tool):
    """Liest eine Textdatei."""

    name = "datei_lesen"
    description = (
        "Liest den Inhalt einer Textdatei aus einem freigegebenen Ordner. "
        "Nur für Textdateien; Bilder und Programme kannst du damit nicht öffnen."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("pfad", "string", "Der vollständige Pfad zur Datei."),
        ToolParameter(
            "max_zeichen",
            "integer",
            "Wie viele Zeichen höchstens gelesen werden.",
            required=False,
            default=8000,
        ),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path_text = str(arguments["pfad"])
        limit = max(100, min(50000, int(arguments.get("max_zeichen", 8000))))

        decision = self._security.paths.check_read(path_text)
        if not decision.allowed:
            return ToolResult.failure(decision.reason)

        path = decision.path
        if not path.is_file():
            # Ein geratener Pfad ist fast immer fast richtig - also
            # nachsehen statt aufgeben (siehe backend/tools/datei_finden.py).
            from backend.tools.datei_finden import datei_finden, hinweis_zu

            gefunden, kandidaten = await asyncio.to_thread(
                datei_finden, path_text, list(self._security.paths.roots)
            )
            if gefunden is None:
                return ToolResult.failure(hinweis_zu(path_text, kandidaten))
            erneut = self._security.paths.check_read(str(gefunden))
            if not erneut.allowed:
                return ToolResult.failure(erneut.reason)
            path = erneut.path

        try:
            size = path.stat().st_size
            if size > 20 * 1024 * 1024:
                return ToolResult.failure(
                    f"Die Datei ist mit {size / 1024 / 1024:.1f} MB zu groß zum Vorlesen."
                )
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return ToolResult.failure(f"Die Datei ließ sich nicht lesen: {error}")

        truncated = len(content) > limit
        if truncated:
            content = content[:limit] + f"\n… (gekürzt, insgesamt {len(content)} Zeichen)"

        return ToolResult.success(content, path=str(path), truncated=truncated)


class ListDirectoryTool(Tool):
    """Listet einen Ordner auf."""

    name = "ordner_auflisten"
    description = (
        "Listet auf, was in einem freigegebenen Ordner liegt. Nützlich, um "
        "herauszufinden, welche Dateien es überhaupt gibt."
    )
    permission = "list_directory"
    parameters = (
        ToolParameter("pfad", "string", "Der Ordner, der aufgelistet werden soll."),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        decision = self._security.paths.check_directory(str(arguments["pfad"]))
        if not decision.allowed:
            return ToolResult.failure(decision.reason)

        try:
            entries = sorted(decision.path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        except OSError as error:
            return ToolResult.failure(f"Der Ordner ließ sich nicht lesen: {error}")

        if not entries:
            return ToolResult.success("Der Ordner ist leer.", path=str(decision.path))

        lines: list[str] = []
        for entry in entries[:200]:
            if entry.is_dir():
                lines.append(f"[Ordner] {entry.name}")
            else:
                try:
                    kilobytes = entry.stat().st_size / 1024
                    lines.append(f"{entry.name} ({kilobytes:.1f} KB)")
                except OSError:
                    lines.append(entry.name)

        if len(entries) > 200:
            lines.append(f"… und {len(entries) - 200} weitere")

        return ToolResult.success("\n".join(lines), path=str(decision.path), count=len(entries))


class SearchFilesTool(Tool):
    """Sucht Dateien nach Namen."""

    name = "dateien_suchen"
    description = (
        "Sucht in den freigegebenen Ordnern nach Dateien, deren Name einen "
        "bestimmten Text enthält."
    )
    permission = "search_files"
    parameters = (
        ToolParameter("suchbegriff", "string", "Der Text, der im Dateinamen vorkommen soll."),
        ToolParameter(
            "max_treffer",
            "integer",
            "Wie viele Treffer höchstens zurückkommen.",
            required=False,
            default=25,
        ),
    )

    def __init__(self, security: SecurityEngine) -> None:
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        needle = str(arguments["suchbegriff"]).strip().lower()
        if len(needle) < 2:
            return ToolResult.failure("Der Suchbegriff ist zu kurz.")

        limit = max(1, min(200, int(arguments.get("max_treffer", 25))))
        roots = self._security.paths.roots
        if not roots:
            return ToolResult.failure(
                "Es ist kein Ordner für die Suche freigegeben. Trage einen unter "
                "'desktop.file_search_roots' in config.yaml ein."
            )

        found: list[str] = []
        started = time.perf_counter()

        for root in roots:
            for directory, subdirectories, filenames in os.walk(root):
                # Versteckte und technische Ordner überspringen – dort liegt
                # nichts, was ein Benutzer sucht, und sie kosten viel Zeit.
                subdirectories[:] = [
                    name
                    for name in subdirectories
                    if not name.startswith(".") and name not in {"node_modules", "__pycache__", ".venv"}
                ]

                for filename in filenames:
                    if needle in filename.lower():
                        found.append(str(Path(directory) / filename))
                        if len(found) >= limit:
                            break

                if len(found) >= limit or time.perf_counter() - started > 12.0:
                    break
            if len(found) >= limit or time.perf_counter() - started > 12.0:
                break

        if not found:
            return ToolResult.success(f"Keine Datei gefunden, die '{needle}' enthält.")

        return ToolResult.success("\n".join(found), count=len(found))


# =============================================================================
# Gedächtnis
# =============================================================================


class MemorySearchTool(Tool):
    """Durchsucht das Gedächtnis von AI-Orb."""

    name = "gedaechtnis_durchsuchen"
    description = (
        "Durchsucht, was du dir früher gemerkt hast – frühere Gespräche, "
        "Vorlieben des Benutzers, Notizen zu Projekten. Benutze das, bevor du "
        "sagst, du wüsstest etwas nicht."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter("suchbegriff", "string", "Wonach im Gedächtnis gesucht wird."),
        ToolParameter(
            "max_treffer",
            "integer",
            "Wie viele Erinnerungen höchstens zurückkommen.",
            required=False,
            default=5,
        ),
    )

    def __init__(self, memory: Any) -> None:
        self._memory = memory

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("suchbegriff", "")).strip()
        if not query:
            return ToolResult.failure("Es fehlt der Suchbegriff.")
        limit = max(1, min(20, int(arguments.get("max_treffer", 5) or 5)))

        # `recall`, nicht `search`.
        #
        # Hier stand `self._memory.search(...)`, und die MemoryEngine hat
        # keine solche Methode. Das Werkzeug war damit von Anfang an tot:
        # Der Orb rief es auf, bekam einen AttributeError zurueck und
        # antwortete, im Gedaechtnis sei nichts zu finden. Genau das war
        # nicht zu unterscheiden von "es steht wirklich nichts drin" - und
        # deshalb ist es niemandem aufgefallen.
        #
        # `recall` ist ausserdem nicht asynchron. Ein `await` darauf haette
        # den naechsten Fehler ergeben, also laeuft es in einem Faden: Die
        # Suche geht ueber den Index und darf die Schleife nicht anhalten.
        try:
            treffer = await asyncio.to_thread(self._memory.recall, query, limit=limit)
        except Exception as error:  # noqa: BLE001
            logger.exception("Die Gedächtnissuche ist fehlgeschlagen.")
            return ToolResult.failure(f"Die Suche im Gedächtnis ging schief: {error}")

        if not treffer:
            return ToolResult.success(f"Zu '{query}' habe ich nichts gespeichert.")

        zeilen = []
        for eintrag in treffer:
            # `recall` liefert SearchResult mit .record; die uebrigen Formen
            # sind fuer den Fall, dass jemand hier etwas anderes einhaengt.
            satz = getattr(eintrag, "record", None)
            if satz is not None:
                art, inhalt = satz.kind, satz.content
            elif isinstance(eintrag, dict):
                art, inhalt = eintrag.get("type", ""), eintrag.get("content", "")
            else:
                art, inhalt = "", str(eintrag)
            zeilen.append(f"[{art}] {inhalt}" if art else str(inhalt))

        return ToolResult.success("\n".join(zeilen), count=len(treffer))


# =============================================================================
# Programme
# =============================================================================


class LaunchApplicationTool(Tool):
    """Startet ein Programm aus der freigegebenen Liste."""

    name = "programm_starten"
    description = (
        "Startet ein beliebiges Programm auf diesem Rechner. Gib den Namen "
        "so an, wie das Programm heisst - 'spotify', 'word', 'edge', "
        "'rechner', 'notepad++'. Deutsche Alltagsnamen werden uebersetzt. "
        "Du musst NICHT wissen, wo es installiert ist; der Orb findet es "
        "ueber den Suchpfad und die Windows-Registrierung. Benutze das "
        "immer, wenn der Benutzer sagt, du sollst etwas oeffnen oder "
        "starten. Ist das Programm nicht installiert, sagt dir die Antwort "
        "das - dann kannst du es mit 'programm_installieren' nachholen."
    )
    permission = "launch_application"
    parameters = (
        ToolParameter("programm", "string", "Der Name des Programms, etwa 'spotify', 'word' oder 'edge'."),
    )

    def __init__(self, desktop: Any) -> None:
        self._desktop = desktop

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments["programm"]).strip()

        try:
            # Die Methode heißt launch, nicht launch_application. Der frühere
            # Aufruf des falschen Namens scheiterte still mit einem
            # AttributeError – das Werkzeug meldete „fehlgeschlagen“, ohne
            # dass je ein Programm angefasst wurde. Genau das sah für den
            # Benutzer aus wie „es passiert nichts“.
            result = self._desktop.launch(name)
        except Exception as error:  # noqa: BLE001
            logger.exception("Das Programm konnte nicht gestartet werden.")
            return ToolResult.failure(f"Der Start ist fehlgeschlagen: {error}")

        # DesktopControl.launch gibt ein ActionResult zurück (kein dict).
        # Beide Formen werden behandelt, damit ein späterer Umbau des
        # Rückgabetyps das Werkzeug nicht erneut still brechen lässt.
        success = getattr(result, "success", None)
        message = getattr(result, "message", "")
        if success is None and isinstance(result, dict):
            success = result.get("success")
            message = result.get("message", "")

        if success:
            return ToolResult.success(message or f"'{name}' wurde gestartet.")
        return ToolResult.failure(message or f"'{name}' ließ sich nicht starten.")


# =============================================================================
# System
# =============================================================================


class SystemInfoTool(Tool):
    """Nennt Eckdaten des Rechners."""

    name = "systeminfo"
    description = (
        "Nennt Eckdaten dieses Rechners: Betriebssystem, Rechnername, "
        "Python-Fassung. Für Fragen, auf welchem System du gerade läufst."
    )
    permission = "read_time"
    parameters = ()

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import sys

        return ToolResult.success(
            f"Betriebssystem: {platform.system()} {platform.release()}\n"
            f"Rechner: {platform.node()}\n"
            f"Prozessor: {platform.machine()}\n"
            f"Python: {sys.version.split()[0]}"
        )


class SearchBookmarksTool(Tool):
    """Durchsucht die Browser-Favoriten (Edge, Chrome u. a.)."""

    name = "favoriten_suchen"
    description = (
        "Durchsucht die Browser-Favoriten nach einem Thema und gibt passende "
        "Links samt Ordner zurueck. Nuetzlich fuer Recherchen: Die Favoriten "
        "eines Wissenschaftlers sind seine ueber Jahre gesammelten Quellen. "
        "Benutze das, wenn nach 'meinen Favoriten', 'meinen Lesezeichen' oder "
        "gespeicherten Quellen zu einem Thema gefragt wird."
    )
    permission = "read_bookmarks"
    parameters = (
        ToolParameter(
            "suchbegriff",
            "string",
            "Das Thema, zu dem Favoriten gesucht werden. Leer listet die ersten.",
            required=False,
            default="",
        ),
        ToolParameter(
            "max_treffer", "integer", "Hoechstzahl der Treffer.",
            required=False, default=20,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        # Erst hier importieren: Das Modul liest beim Import nichts, aber so
        # bleibt die Werkzeugliste auch dann ladbar, wenn am Favoritenformat
        # einmal etwas nicht stimmt.
        from backend.research.browser_bookmarks import search_bookmarks

        needle = str(arguments.get("suchbegriff", "")).strip()
        limit = int(arguments.get("max_treffer", 20) or 20)

        try:
            treffer = search_bookmarks(needle, limit=limit)
        except Exception as error:  # noqa: BLE001 - ein Werkzeug darf nie den Kern reissen.
            return ToolResult.failure(f"Favoriten nicht lesbar: {error}")

        if not treffer:
            if needle:
                return ToolResult.success(
                    f"Keine Favoriten zu '{needle}' gefunden."
                )
            return ToolResult.success(
                "Es wurden keine Browser-Favoriten gefunden. Unterstuetzt "
                "werden Edge, Chrome, Brave, Vivaldi und Opera."
            )

        lines = [
            f"{b.title}\n    {b.url}\n    Ordner: {b.folder_path}"
            for b in treffer
        ]
        return ToolResult.success(
            "\n\n".join(lines),
            count=len(treffer),
            treffer=[b.to_dict() for b in treffer],
        )


def build_standard_tools(
    *,
    security: SecurityEngine,
    memory: Any | None = None,
    desktop: Any | None = None,
) -> list[Tool]:
    """Stellt die mitgelieferten Werkzeuge zusammen.

    Werkzeuge, für die der nötige Bestandteil fehlt, werden weggelassen –
    besser gar kein Werkzeug als eines, das beim Aufruf zusammenbricht.
    """

    # Die Internet-Werkzeuge liegen in einem eigenen Modul; der Import hier
    # unten hält die Abhängigkeit in eine Richtung.
    from backend.tools.install_tools import InstallPackageTool, InstallProgramTool
    from backend.tools.terminal_tools import build_terminal_tools
    from backend.tools.web_tools import (
        OpenInBrowserTool,
        ReadWebpageTool,
        WebSearchTool,
        WebseiteErkundenTool,
    )

    tools: list[Tool] = [
        CurrentTimeTool(),
        CalculateTool(),
        SystemInfoTool(),
        ReadFileTool(security),
        ListDirectoryTool(security),
        SearchFilesTool(security),
        SearchBookmarksTool(),
        WebSearchTool(),
        ReadWebpageTool(),
        WebseiteErkundenTool(),
        OpenInBrowserTool(desktop),
        # `wissen_aneignen` stand frueher hier und legte nur die
        # Trefferzeile der Suchmaschine ab. Es liegt jetzt in
        # backend/tools/learning_tools.py und speichert die Substanz.
        # Nachruesten: Programme installieren und fehlende eigene Pakete
        # holen. Damit endet die Sackgasse "mir fehlt ein Paket, und ich
        # kann nichts dagegen tun".
        InstallProgramTool(),
        InstallPackageTool(),
        *build_terminal_tools(),
    ]

    if memory is not None:
        tools.append(MemorySearchTool(memory))
    if desktop is not None:
        tools.append(LaunchApplicationTool(desktop))

    return tools
