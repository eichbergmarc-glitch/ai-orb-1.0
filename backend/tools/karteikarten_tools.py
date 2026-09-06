"""Karteikarten als Werkzeuge - damit der Orb sie auch benutzen kann.

Die Karteikarten gibt es seit Phase 18: abgestufte Wiederholungen, Stapel,
Leichtigkeit, Termine. Der Orb legte den Stapel beim Start auch brav an -
und konnte ihn dann nicht anfassen. Es war schlicht kein Werkzeug dafür
angemeldet, und was nicht in der Werkzeugliste steht, existiert für das
Sprachmodell nicht.

Genau das war die Lücke zwischen „Lernstand und Karteikarten existieren" und
der Vorgabe „Mentor und Professor": Der Orb konnte den Lernstand führen und
Karten verwalten, aber niemand hatte die beiden Enden verbunden. Vier
Werkzeuge reichen dafür - anlegen, abfragen, bewerten, nachsehen.
"""

from __future__ import annotations

from typing import Any

from backend.learning.flashcards import FlashcardDeck
from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)


class KarteikarteAnlegenTool(Tool):
    """Legt eine einzelne Karte an."""

    name = "karteikarte_anlegen"
    description = (
        "Legt eine Karteikarte mit Frage und Antwort an. Benutze das, wenn "
        "der Benutzer etwas lernen oder behalten will, wenn er sagt 'merk "
        "dir das zum Abfragen', oder wenn du im Unterricht einen Punkt "
        "siehst, den er wiederholen sollte. Eine Karte je Gedanke - zwei "
        "Fragen in einer Karte lassen sich nicht sinnvoll bewerten."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter("frage", "string", "Die Vorderseite - was gefragt wird."),
        ToolParameter("antwort", "string", "Die Rückseite - was gewusst werden soll."),
        ToolParameter(
            "stapel",
            "string",
            "Der Stapel, etwa ein Fach oder Thema.",
            required=False,
            default="allgemein",
        ),
    )

    def __init__(self, karten: FlashcardDeck) -> None:
        super().__init__()
        self._karten = karten

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        frage = str(arguments.get("frage", "")).strip()
        antwort = str(arguments.get("antwort", "")).strip()
        stapel = str(arguments.get("stapel", "allgemein")).strip() or "allgemein"

        karte, meldung = self._karten.add(frage, antwort, deck=stapel)
        if karte is None:
            return ToolResult.failure(meldung)
        return ToolResult.success(
            f"{meldung} Frage: {karte.front}",
            karten_id=karte.card_id,
            stapel=karte.deck,
        )


class KarteikartenAbfragenTool(Tool):
    """Holt die fälligen Karten."""

    name = "karteikarten_abfragen"
    description = (
        "Gibt die Karteikarten zurück, die jetzt zur Wiederholung anstehen - "
        "mit Frage, Antwort und Kennung. Benutze das, wenn der Benutzer "
        "abgefragt werden möchte, wenn er nach seinem Lernstand fragt oder "
        "wenn du von dir aus eine Lerneinheit vorschlägst. Frage die Karten "
        "einzeln ab und bewerte jede mit 'karteikarte_bewerten'."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter(
            "stapel", "string", "Nur dieser Stapel.", required=False, default=""
        ),
        ToolParameter(
            "anzahl", "integer", "Wie viele höchstens (1-20).", required=False, default=5
        ),
    )

    def __init__(self, karten: FlashcardDeck) -> None:
        super().__init__()
        self._karten = karten

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        stapel = str(arguments.get("stapel", "")).strip()
        anzahl = min(20, max(1, int(arguments.get("anzahl", 5) or 5)))

        faellig = self._karten.due_cards(deck=stapel, limit=anzahl)
        if not faellig:
            return ToolResult.success(
                "Im Moment steht keine Karte zur Wiederholung an."
                + (f" (Stapel '{stapel}')" if stapel else ""),
                faellig=0,
            )

        zeilen = [
            f"{nummer}. [{karte.card_id}] {karte.front}\n   Antwort: {karte.back}"
            for nummer, karte in enumerate(faellig, start=1)
        ]
        return ToolResult.success(
            f"{len(faellig)} Karte(n) fällig:\n" + "\n".join(zeilen),
            faellig=len(faellig),
            karten=[karte.card_id for karte in faellig],
        )


class KarteikarteBewertenTool(Tool):
    """Trägt ein, wie gut eine Karte saß."""

    name = "karteikarte_bewerten"
    description = (
        "Trägt ein, wie gut der Benutzer eine Karte konnte, und legt damit "
        "den nächsten Abfragetermin fest. Ohne diesen Schritt lernt der "
        "Stapel nichts dazu. Noten: 'nochmal' (nicht gewusst), 'muehsam' "
        "(mit Mühe), 'gut' (gewusst), 'leicht' (sofort gewusst)."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter("karten_id", "string", "Die Kennung aus der Abfrage."),
        ToolParameter(
            "note", "string", "nochmal, muehsam, gut oder leicht."
        ),
    )

    def __init__(self, karten: FlashcardDeck) -> None:
        super().__init__()
        self._karten = karten

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        kennung = str(arguments.get("karten_id", "")).strip()
        note = str(arguments.get("note", "")).strip()

        karte, meldung = self._karten.review(kennung, note)
        if karte is None:
            return ToolResult.failure(meldung)
        return ToolResult.success(meldung, karten_id=karte.card_id)


class KarteikartenStandTool(Tool):
    """Wie es um die Stapel steht."""

    name = "karteikarten_stand"
    description = (
        "Zeigt die Stapel mit Anzahl, fälligen Karten und den Punkten, die "
        "am schlechtesten sitzen. Benutze das, wenn der Benutzer wissen "
        "will, wie er steht, oder wenn du entscheiden musst, was als "
        "Nächstes geübt werden sollte."
    )
    permission = "read_memory"
    parameters = ()

    def __init__(self, karten: FlashcardDeck) -> None:
        super().__init__()
        self._karten = karten

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        stapel = self._karten.decks()
        if not stapel:
            return ToolResult.success(
                "Es gibt noch keine Karteikarten. Lege welche mit "
                "'karteikarte_anlegen' an."
            )

        zeilen = [
            f"- {eintrag.get('deck', '?')}: {eintrag.get('total', 0)} Karten, "
            f"{eintrag.get('due', 0)} fällig"
            for eintrag in stapel
        ]
        schwach = self._karten.weak_cards(limit=3)
        if schwach:
            zeilen.append("Am wackligsten:")
            zeilen.extend(
                f"  - {eintrag.get('front', '')}" for eintrag in schwach
            )
        return ToolResult.success("\n".join(zeilen), stapel=len(stapel))


def build_karteikarten_tools(karten: FlashcardDeck) -> list[Tool]:
    """Die vier Werkzeuge rund um die Karteikarten."""

    return [
        KarteikarteAnlegenTool(karten),
        KarteikartenAbfragenTool(karten),
        KarteikarteBewertenTool(karten),
        KarteikartenStandTool(karten),
    ]


__all__ = [
    "KarteikarteAnlegenTool",
    "KarteikartenAbfragenTool",
    "KarteikarteBewertenTool",
    "KarteikartenStandTool",
    "build_karteikarten_tools",
]
