"""Werkzeuge, mit denen sich der Orb in ein Thema einarbeitet.

Es gab schon eines, ``wissen_aneignen``, und es war angeschlossen. Es
speicherte aber nur die Trefferzeile der Suchmaschine – Titel, ein Satz,
ein Link. Diese Werkzeuge treten an seine Stelle und legen die Substanz ab.

Fünf Wege führen zum selben Themenwissen, und das ist Absicht: Was der Orb
aus dem Netz liest, was in einem Aufsatz auf der Festplatte steht und was
der Benutzer ihm im Gespräch erklärt, gehört zum selben Gebiet und soll
sich nicht in drei Ablagen verteilen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.learning.themenlerner import Themenlerner
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


class LearnTopicTool(Tool):
    """Arbeitet ein Thema aus dem Internet ein."""

    name = "wissen_aneignen"
    description = (
        "Arbeitet ein Thema aus dem Internet ein und behaelt es dauerhaft. "
        "Liest mehrere Quellen, destilliert daraus einzelne belegte Aussagen "
        "und haelt fest, was offen blieb. Benutze das, wenn der Benutzer "
        "sagt, du sollst dir etwas aneignen, dich einarbeiten, dazulernen "
        "oder ein Grundwissen aufbauen. Fuer eine einmalige Frage nimm "
        "stattdessen internet_suchen."
    )
    permission = "network"
    parameters = (
        ToolParameter("thema", "string", "Das Gebiet, in das eingearbeitet wird."),
        ToolParameter(
            "max_quellen",
            "integer",
            "Wie viele Quellen gelesen werden (1-5).",
            required=False,
            default=3,
        ),
    )

    def __init__(self, lerner: Themenlerner) -> None:
        super().__init__()
        self._lerner = lerner

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        thema = str(arguments.get("thema", "")).strip()
        if not thema:
            return ToolResult.failure("Es fehlt das Thema.")
        quellen = min(5, max(1, int(arguments.get("max_quellen", 3) or 3)))

        ergebnis = await self._lerner.aus_dem_netz(thema, quellen=quellen)
        return _melden(ergebnis, thema)


class DeepenTopicTool(Tool):
    """Arbeitet an einer offenen Frage eines Themas weiter."""

    name = "wissen_vertiefen"
    description = (
        "Arbeitet an einem bereits begonnenen Thema weiter und geht dabei "
        "einer offenen Frage nach - nicht derselben Suche noch einmal. "
        "Benutze das, wenn der Benutzer sagt, du sollst mehr darueber "
        "lernen, tiefer einsteigen oder eine Luecke schliessen."
    )
    permission = "network"
    parameters = (
        ToolParameter("thema", "string", "Das begonnene Gebiet."),
        ToolParameter(
            "frage",
            "string",
            "Welcher Frage nachgegangen wird. Leer heisst: die naechste offene.",
            required=False,
            default="",
        ),
    )

    def __init__(self, lerner: Themenlerner, speicher: Any) -> None:
        super().__init__()
        self._lerner = lerner
        self._speicher = speicher

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        thema_name = str(arguments.get("thema", "")).strip()
        if not thema_name:
            return ToolResult.failure("Es fehlt das Thema.")

        frage = str(arguments.get("frage", "")).strip()
        if not frage:
            thema = self._speicher.laden(thema_name)
            if not thema.aussagen:
                return ToolResult.failure(
                    f"Zu '{thema_name}' weiss ich noch nichts. Lass mich das "
                    "Thema erst aneignen, dann kann ich vertiefen."
                )
            if not thema.offene_fragen:
                return ToolResult.success(
                    f"Zu {thema_name} ist bei mir gerade nichts offen. Sag "
                    "mir, was dich genauer interessiert, dann gehe ich dem nach."
                )
            frage = thema.offene_fragen[0]

        ergebnis = await self._lerner.aus_dem_netz(thema_name, quellen=3, frage=frage)
        antwort = _melden(ergebnis, thema_name)
        if antwort.ok:
            # ``context`` und nicht ``data``: ToolResult hat kein Feld
            # ``data``, und der Zugriff darauf liess das Werkzeug jedes Mal
            # abstuerzen ("'ToolResult' object has no attribute 'data'").
            # Der Fehler traf ausgerechnet den Erfolgsfall - wenn also
            # wirklich etwas gelernt worden war.
            return ToolResult.success(
                f"Nachgegangen bin ich der Frage: {frage}\n\n{antwort.output}",
                **(antwort.context or {}),
            )
        return antwort


class LearnFromFileTool(Tool):
    """Arbeitet eine Datei in ein Thema ein."""

    name = "wissen_aus_datei"
    description = (
        "Liest eine Datei von der Festplatte - PDF, Word oder Text - und "
        "arbeitet ihren Inhalt in ein Thema ein. Benutze das, wenn der "
        "Benutzer auf ein Dokument zeigt und sagt, du sollst es dir "
        "aneignen oder einarbeiten."
    )
    permission = "read_files"
    parameters = (
        ToolParameter("pfad", "string", "Die Datei, die eingearbeitet wird."),
        ToolParameter("thema", "string", "Zu welchem Gebiet sie gehoert."),
    )

    def __init__(self, lerner: Themenlerner, security: Any) -> None:
        super().__init__()
        self._lerner = lerner
        self._security = security

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        thema = str(arguments.get("thema", "")).strip()
        pfad_text = str(arguments.get("pfad", "")).strip()
        if not thema or not pfad_text:
            return ToolResult.failure("Es fehlen Thema oder Pfad.")

        entscheidung = self._security.paths.check_read(pfad_text)
        if not entscheidung.allowed:
            return ToolResult.failure(entscheidung.reason)

        pfad = Path(entscheidung.path)
        if not pfad.is_file():
            # Nicht aufgeben, sondern NACHSEHEN.
            #
            # Der geratene Pfad ist fast immer fast richtig (falscher
            # Zwischenordner, Unterstrich statt Leerzeichen). Vorher endete
            # die Aufgabe genau hier - zweimal geraten, zweimal daneben,
            # fertig. Jetzt wird der Name in den freigegebenen Ordnern
            # gesucht; ist er eindeutig, geht es einfach weiter.
            import asyncio

            from backend.tools.datei_finden import datei_finden, hinweis_zu

            gefunden, kandidaten = await asyncio.to_thread(
                datei_finden, pfad_text, list(self._security.paths.roots)
            )
            if gefunden is None:
                return ToolResult.failure(hinweis_zu(pfad_text, kandidaten))
            geprueft = self._security.paths.check_read(str(gefunden))
            if not geprueft.allowed:
                return ToolResult.failure(geprueft.reason)
            pfad = Path(geprueft.path)
            logger.info("Die gemeinte Datei wurde gefunden: %s", pfad)

        ergebnis = await self._lerner.aus_datei(thema, pfad)
        return _melden(ergebnis, thema)


class RememberStatementTool(Tool):
    """Übernimmt, was der Benutzer im Gespräch erklärt hat."""

    name = "wissen_uebernehmen"
    description = (
        "Merkt sich dauerhaft, was der Benutzer dir selbst ueber ein Thema "
        "erklaert hat - mit ihm als Quelle. Benutze das, wenn er dir etwas "
        "Fachliches beibringt, richtigstellt oder sagt, du sollst dir das "
        "merken. Gib seine Aussage moeglichst woertlich weiter."
    )
    # Dieselbe Berechtigung wie beim Merken von Vorlieben: Es wird ins
    # eigene Gedaechtnis geschrieben, nicht nach draussen gewirkt. Eine
    # eigene Berechtigung dafuer einzufuehren hiesse, dem Benutzer eine
    # Frage mehr zu stellen, ohne dass ein Unterschied dahinterstuende.
    permission = "read_memory"
    parameters = (
        ToolParameter("thema", "string", "Zu welchem Gebiet die Aussage gehoert."),
        ToolParameter("aussage", "string", "Was er erklaert hat, fuer sich verstaendlich."),
    )

    def __init__(self, lerner: Themenlerner) -> None:
        super().__init__()
        self._lerner = lerner

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        thema = str(arguments.get("thema", "")).strip()
        aussage = str(arguments.get("aussage", "")).strip()
        if not thema or not aussage:
            return ToolResult.failure("Es fehlen Thema oder Aussage.")

        ergebnis = self._lerner.aus_gespraech(thema, aussage)
        if not ergebnis.ok:
            return ToolResult.failure(ergebnis.hinweis)
        return ToolResult.success(ergebnis.hinweis, **ergebnis.to_dict())


class ShowTopicTool(Tool):
    """Sagt, was der Orb zu einem Thema weiss."""

    name = "wissen_zeigen"
    description = (
        "Gibt wieder, was du dir zu einem Thema bereits angeeignet hast, "
        "mit Quellen und offenen Fragen. Ohne Thema nennst du alle Gebiete, "
        "in die du dich eingearbeitet hast."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter(
            "thema",
            "string",
            "Das Gebiet. Leer heisst: alle Gebiete nennen.",
            required=False,
            default="",
        ),
    )

    def __init__(self, speicher: Any) -> None:
        super().__init__()
        self._speicher = speicher

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments.get("thema", "")).strip()

        if not name:
            themen = self._speicher.alle()
            if not themen:
                return ToolResult.success(
                    "Ich habe mich bisher in kein Thema eingearbeitet."
                )
            zeilen = ["Eingearbeitet habe ich mich in:"]
            for thema in themen:
                offen = (
                    f", {len(thema.offene_fragen)} Fragen offen"
                    if thema.offene_fragen
                    else ""
                )
                zeilen.append(
                    f"- {thema.name}: {len(thema.aussagen)} Aussagen aus "
                    f"{len(thema.quellen())} Quellen{offen}"
                )
            return ToolResult.success("\n".join(zeilen), themen=len(themen))

        thema = self._speicher.laden(name)
        return ToolResult.success(
            thema.bericht(),
            aussagen=len(thema.aussagen),
            offene_fragen=len(thema.offene_fragen),
        )


def _melden(ergebnis: Any, thema: str) -> ToolResult:
    """Macht aus einem Lernergebnis eine Antwort für das Modell."""

    if not ergebnis.ok:
        return ToolResult.failure(ergebnis.hinweis or "Das Einarbeiten ist gescheitert.")

    if ergebnis.neue_aussagen == 0:
        return ToolResult.success(
            f"Zu '{thema}' habe ich {len(ergebnis.quellen)} Quellen gelesen, aber "
            "nichts gefunden, was ich nicht schon wusste. Sag dem Benutzer das "
            "so - und schlag ihm vor, es genauer einzugrenzen.",
            **ergebnis.to_dict(),
        )

    quellen = "\n".join(f"- {q}" for q in ergebnis.quellen)
    return ToolResult.success(
        f"Zu '{thema}' habe ich {ergebnis.neue_aussagen} neue Aussagen "
        f"aufgenommen und {ergebnis.neue_fragen} offene Fragen vermerkt.\n\n"
        f"Gelesene Quellen:\n{quellen}\n\n"
        "Sag dem Benutzer in eigenen Worten, was du dazugelernt hast, nenne "
        "dabei die Quellen und erwaehne, was offen blieb. Erfinde nichts dazu - "
        "wenn du den Inhalt brauchst, ruf wissen_zeigen fuer dieses Thema auf.",
        **ergebnis.to_dict(),
    )


def build_learning_tools(
    *, lerner: Themenlerner, speicher: Any, security: Any
) -> list[Tool]:
    """Stellt die Lernwerkzeuge zusammen."""

    return [
        LearnTopicTool(lerner),
        DeepenTopicTool(lerner, speicher),
        LearnFromFileTool(lerner, security),
        RememberStatementTool(lerner),
        ShowTopicTool(speicher),
    ]
