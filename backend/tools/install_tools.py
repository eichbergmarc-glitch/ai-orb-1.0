"""Werkzeuge zum Nachrüsten: Programme und fehlende Pakete installieren.

Zwei Dinge, die zusammengehören.

**Programme installieren.** Ein Assistent, der nur benutzen kann, was schon
da ist, hört genau dort auf, wo es interessant wird. Unter Windows gibt es
mit ``winget`` einen Paketverwalter, der ab Werk dabei ist und aus
geprüften Quellen installiert – kein Herunterladen zweifelhafter
Installationsdateien, kein Klickweg durch Werbeseiten.

**Sich selbst nachrüsten.** AI-Orb bringt seinen eigenen Python mit, und
darin fehlen mitunter Pakete – die für Bildschirmfotos etwa werden beim
Bauen nicht mitinstalliert. Bisher endete das in einer Sackgasse: Der Orb
meldete, ein Paket fehle, und konnte nichts dagegen tun. Jetzt kann er es
nachinstallieren, in seine eigene Laufzeit, ohne das System-Python
anzufassen.

Beides ist ausdrücklich heikel und läuft deshalb über die
Sicherheitsschicht mit der Berechtigung ``install_dependencies``
(Stufe KRITISCH). Im geschützten Modus wird gefragt; im offenen Modus,
den der Benutzer gewählt hat, geschieht es ohne Rückfrage – aber immer im
Prüfprotokoll nachlesbar.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

#: Wie lange eine Installation höchstens dauern darf.
_TIMEOUT = 600.0


def _runtime_python() -> str:
    """Der Python-Interpreter, mit dem AI-Orb selbst läuft.

    Bewusst ``sys.executable`` und nicht ein gefundenes ``python`` aus dem
    Suchpfad: Nachgerüstet wird in die mitgelieferte Laufzeit, in der die
    Pakete auch gebraucht werden. Ein Paket im System-Python zu
    installieren sähe nach Erfolg aus und änderte nichts.
    """

    return sys.executable or "python"


def _run(arguments: list[str]) -> tuple[int, str]:
    """Führt einen Befehl aus und gibt Rückgabewert und Ausgabe zurück."""

    flags = 0
    if os.name == "nt":
        # Kein aufblitzendes Konsolenfenster.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = subprocess.run(  # noqa: S603 - die Argumente stehen unten fest.
            arguments,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            creationflags=flags,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return 1, f"Zeitlimit von {_TIMEOUT / 60:.0f} Minuten überschritten."
    except OSError as error:
        return 1, f"Aufruf fehlgeschlagen: {error}"

    ausgabe = ((process.stdout or "") + "\n" + (process.stderr or "")).strip()
    return process.returncode, ausgabe


class InstallProgramTool(Tool):
    """Installiert ein Programm über den Windows-Paketverwalter."""

    name = "programm_installieren"
    description = (
        "Installiert ein Programm auf diesem Rechner ueber winget, den "
        "Windows-Paketverwalter. Benutze das, wenn der Benutzer sagt, du "
        "sollst etwas installieren oder einrichten - etwa einen Editor, ein "
        "Werkzeug oder eine Anwendung. Suchst du erst, welches Paket gemeint "
        "ist, setze nur_suchen auf true; dann wird nichts installiert, "
        "sondern eine Trefferliste zurueckgegeben."
    )
    permission = "install_dependencies"
    parameters = (
        ToolParameter("name", "string", "Name oder Paket-Kennung des Programms."),
        ToolParameter(
            "nur_suchen", "boolean",
            "Nur nachsehen, welche Pakete es gibt, statt zu installieren.",
            required=False, default=False,
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("name", "")).strip()
        if not name:
            return ToolResult.failure("Es fehlt der Programmname.")

        nur_suchen = bool(arguments.get("nur_suchen", False))

        winget = shutil.which("winget")
        if winget is None:
            return ToolResult.failure(
                "winget wurde nicht gefunden. Es gehoert ab Windows 10 zum "
                "System (als 'App-Installer' im Microsoft Store). Ohne winget "
                "kann ich keine Programme installieren."
            )

        if nur_suchen:
            code, ausgabe = await asyncio.to_thread(
                _run, [winget, "search", name, "--accept-source-agreements"]
            )
            if code != 0:
                return ToolResult.failure(f"Die Suche ist fehlgeschlagen: {ausgabe[:400]}")
            return ToolResult.success(ausgabe[:3000] or f"Keine Treffer zu '{name}'.")

        logger.info("Installation angefordert: %s", name)
        code, ausgabe = await asyncio.to_thread(
            _run,
            [
                winget, "install", "--id", name, "-e",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity",
            ],
        )

        # Die Kennung war vielleicht ein gewöhnlicher Name. Dann ohne "--id"
        # noch einmal versuchen, bevor aufgegeben wird.
        if code != 0 and "No package found" in ausgabe:
            code, ausgabe = await asyncio.to_thread(
                _run,
                [
                    winget, "install", name,
                    "--accept-package-agreements", "--accept-source-agreements",
                    "--disable-interactivity",
                ],
            )

        if code != 0:
            return ToolResult.failure(
                f"Die Installation von '{name}' ist fehlgeschlagen.\n{ausgabe[-800:]}"
            )

        logger.info("Installiert: %s", name)
        return ToolResult.success(
            f"'{name}' wurde installiert.\n{ausgabe[-600:]}", programm=name
        )


class InstallPackageTool(Tool):
    """Rüstet fehlende Python-Pakete in AI-Orbs eigener Laufzeit nach."""

    name = "pakete_nachruesten"
    description = (
        "Installiert fehlende Python-Pakete in AI-Orbs eigene Laufzeit - "
        "damit kann sich der Orb selbst Faehigkeiten nachruesten. Benutze "
        "das, wenn ein Werkzeug meldet, dass ihm ein Paket fehlt. Fuer die "
        "Bildschirmaufnahme sind es 'mss' und 'Pillow', fuer die "
        "Texterkennung zusaetzlich 'pytesseract'. Installiere nur, was "
        "wirklich gebraucht wird."
    )
    permission = "install_dependencies"
    parameters = (
        ToolParameter(
            "pakete", "string",
            "Die Paketnamen, durch Leerzeichen getrennt (z. B. 'mss Pillow').",
        ),
    )

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        roh = str(arguments.get("pakete", "")).strip()
        if not roh:
            return ToolResult.failure("Es fehlen die Paketnamen.")

        # Nur einfache Paketnamen zulassen. Alles mit Sonderzeichen könnte
        # pip zu etwas anderem überreden, als hier gemeint ist.
        pakete = [
            teil for teil in roh.replace(",", " ").split()
            if teil.replace("-", "").replace("_", "").replace(".", "").isalnum()
        ]
        if not pakete:
            return ToolResult.failure(
                "Keine gültigen Paketnamen erkannt. Erlaubt sind nur "
                "gewöhnliche Namen wie 'mss' oder 'Pillow'."
            )

        python = _runtime_python()
        logger.info("Pakete werden nachgerüstet: %s (nach %s)", ", ".join(pakete), python)

        code, ausgabe = await asyncio.to_thread(
            _run,
            [python, "-m", "pip", "install", "--no-warn-script-location",
             "--disable-pip-version-check", *pakete],
        )

        if code != 0:
            return ToolResult.failure(
                "Das Nachrüsten ist fehlgeschlagen:\n" + ausgabe[-800:]
            )

        # Gegenprobe: Lässt sich wirklich importieren, was installiert wurde?
        # Eine erfolgreiche Installation ist nicht dasselbe wie ein
        # benutzbares Paket – etwa wenn eine Fassung nicht zur Laufzeit passt.
        pruefnamen = {"pillow": "PIL", "opencv-python": "cv2"}
        fehlend: list[str] = []
        for paket in pakete:
            modul = pruefnamen.get(paket.lower(), paket)
            pcode, _ = await asyncio.to_thread(_run, [python, "-c", f"import {modul}"])
            if pcode != 0:
                fehlend.append(paket)

        if fehlend:
            return ToolResult.failure(
                "Installiert, aber nicht ladbar: " + ", ".join(fehlend)
                + ". Moeglicherweise passt die Fassung nicht zur Laufzeit."
            )

        return ToolResult.success(
            f"Nachgerüstet und geprüft: {', '.join(pakete)}. "
            "Die zugehörigen Fähigkeiten stehen nach einem Neustart von "
            "AI-Orb bereit.",
            pakete=pakete,
        )
