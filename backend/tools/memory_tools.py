"""Werkzeuge, mit denen sich der Orb etwas über den Benutzer merkt.

Der Orb beobachtete schon immer, wie er benutzt wird, und das
Langzeitgedächtnis kennt die Kategorien „Vorliebe" und „Gewohnheit" seit
Anfang an. Was fehlte, war beides: Er konnte nichts ausdrücklich
hinterlegen, wenn jemand es ihm sagte – und das Gemerkte kam beim Denken
nie an. Gelernt zu haben und nichts damit zu tun ist schlimmer, als nicht
gelernt zu haben: Von aussen sieht es wie Gleichgültigkeit aus.

Diese Werkzeuge schliessen die eine Hälfte. Die andere – dass das Gemerkte
in jeden Gedanken eingeht – steckt im Cognitive Core.

Bewusst getrennt gehalten sind zwei Dinge, die leicht zusammenfallen
würden:

Eine **Vorliebe** ist, was jemand möchte („kurze Antworten", „lieber
Schweizer Quellen"). Eine **Gewohnheit** ist, was jemand tut („arbeitet
meist am frühen Morgen"). Die erste ist eine Anweisung, die zweite eine
Beobachtung – und der Unterschied ändert, wie der Orb damit umgeht.
"""

from __future__ import annotations

from typing import Any

from backend.system.logging_setup import get_logger
from backend.tools.base_tool import Tool, ToolParameter, ToolResult

logger = get_logger(__name__)

#: Was sich merken lässt und wie es genannt wird.
_ARTEN: dict[str, str] = {
    "vorliebe": "Vorliebe",
    "gewohnheit": "Gewohnheit",
}


class RememberPreferenceTool(Tool):
    """Merkt sich eine Vorliebe oder Gewohnheit des Benutzers."""

    name = "vorliebe_merken"
    description = (
        "Merkt sich dauerhaft etwas über den Benutzer: eine Vorliebe (was "
        "er möchte, z. B. 'mag kurze Antworten', 'arbeitet auf Deutsch') "
        "oder eine Gewohnheit (was er tut, z. B. 'recherchiert meist "
        "abends'). Benutze das, sobald der Benutzer so etwas ausspricht – "
        "auch beiläufig – oder wenn du es über mehrere Gespräche hinweg "
        "bemerkst. Formuliere kurz und in der dritten Person. Merke nichts, "
        "was nur für diesen einen Augenblick gilt."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter(
            "art",
            "string",
            "Ob es eine Vorliebe oder eine Gewohnheit ist.",
            choices=("vorliebe", "gewohnheit"),
        ),
        ToolParameter(
            "inhalt",
            "string",
            "Was gemerkt wird – ein kurzer Satz, z. B. 'Mag knappe Antworten'.",
        ),
    )

    def __init__(self, long_term: Any, user_memory: Any = None) -> None:
        self._long_term = long_term
        #: Das Benutzergedächtnis. Es speist zwei weitere Abschnitte des
        #: Denkkontexts, die sonst leer blieben – dieselbe Angabe wirkt
        #: dadurch an zwei Stellen, ohne dass sie zweimal gesagt werden muss.
        self._user = user_memory

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        art = str(arguments["art"]).strip().lower()
        if art not in _ARTEN:
            return ToolResult.failure(
                f"'{art}' kenne ich nicht. Möglich sind: vorliebe, gewohnheit."
            )

        inhalt = str(arguments["inhalt"]).strip()
        if len(inhalt) < 4:
            return ToolResult.failure("Dafür ist mir zu wenig gesagt worden.")
        if len(inhalt) > 300:
            inhalt = inhalt[:300].rstrip() + " …"

        try:
            self._long_term.store(art, inhalt, source="gespräch")
        except Exception as fehler:  # noqa: BLE001
            logger.exception("Das Merken ist gescheitert.")
            return ToolResult.failure(f"Ich konnte es mir nicht merken: {fehler}")

        if self._user is not None:
            try:
                self._user.add_fact(inhalt, source="gespräch")
            except Exception:  # noqa: BLE001
                logger.debug("Die Angabe kam nicht ins Benutzergedächtnis.", exc_info=True)

        logger.info("Gemerkt (%s): %s", art, inhalt)
        return ToolResult.success(
            f"Gemerkt als {_ARTEN[art]}: {inhalt}", art=art, inhalt=inhalt
        )


class ShowPreferencesTool(Tool):
    """Sagt, was der Orb über den Benutzer gemerkt hat."""

    name = "vorlieben_zeigen"
    description = (
        "Zählt auf, was der Orb sich über den Benutzer gemerkt hat – "
        "Vorlieben und Gewohnheiten. Benutze das bei Fragen wie 'was weisst "
        "du über mich' oder 'was hast du dir gemerkt'."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter(
            "art",
            "string",
            "Nur eine Art zeigen. Weglassen zeigt beides.",
            required=False,
            choices=("vorliebe", "gewohnheit"),
        ),
    )

    def __init__(self, long_term: Any, preferences: Any = None) -> None:
        self._long_term = long_term
        self._preferences = preferences

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        gewuenscht = str(arguments.get("art", "") or "").strip().lower()
        arten = [gewuenscht] if gewuenscht in _ARTEN else list(_ARTEN)

        zeilen: list[str] = []
        gesamt = 0
        for art in arten:
            try:
                eintraege = self._long_term.by_category(art)
            except Exception:  # noqa: BLE001
                continue
            texte = [str(e.content).strip() for e in eintraege if str(e.content).strip()]
            if not texte:
                continue
            gesamt += len(texte)
            zeilen.append(f"{_ARTEN[art]}n:" if art == "vorliebe" else f"{_ARTEN[art]}en:")
            zeilen.extend(f"- {text}" for text in texte[-12:])

        # Das nebenher Gelernte gehört dazu – es wirkt sich genauso aus,
        # auch wenn es niemand ausgesprochen hat.
        beobachtet = ""
        if self._preferences is not None:
            try:
                beobachtet = str(self._preferences.guidance() or "")
            except Exception:  # noqa: BLE001
                beobachtet = ""
        if beobachtet:
            zeilen.append(beobachtet)

        if not zeilen:
            return ToolResult.success(
                "Ich habe mir bisher nichts über dich gemerkt. Sag mir "
                "einfach, was du möchtest – dann behalte ich es.",
                anzahl=0,
            )

        return ToolResult.success("\n".join(zeilen), anzahl=gesamt)


class ForgetPreferenceTool(Tool):
    """Vergisst eine gemerkte Vorliebe oder Gewohnheit."""

    name = "vorliebe_vergessen"
    description = (
        "Löscht eine gemerkte Vorliebe oder Gewohnheit. Gesucht wird nach "
        "einem Stichwort; passt genau ein Eintrag, wird er gelöscht. "
        "Benutze das, wenn der Benutzer sagt, etwas stimme nicht mehr."
    )
    permission = "read_memory"
    parameters = (
        ToolParameter("stichwort", "string", "Wonach gesucht wird."),
    )

    def __init__(self, long_term: Any) -> None:
        self._long_term = long_term

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        stichwort = str(arguments["stichwort"]).strip().lower()
        if len(stichwort) < 3:
            return ToolResult.failure(
                "Das Stichwort ist zu kurz – so träfe es womöglich das Falsche."
            )

        treffer = []
        for art in _ARTEN:
            try:
                for eintrag in self._long_term.by_category(art):
                    if stichwort in str(eintrag.content).lower():
                        treffer.append(eintrag)
            except Exception:  # noqa: BLE001
                continue

        if not treffer:
            return ToolResult.failure(
                f"Zu '{stichwort}' habe ich nichts gemerkt."
            )

        if len(treffer) > 1:
            # Lieber nachfragen als das Falsche löschen: Gemerktes ist mit
            # der Zeit entstanden und lässt sich nicht zurückholen.
            liste = "\n".join(f"- {e.content}" for e in treffer[:6])
            return ToolResult.failure(
                f"Dazu passen mehrere Einträge:\n{liste}\n"
                "Sag genauer, welcher gemeint ist."
            )

        eintrag = treffer[0]
        try:
            geloescht = bool(self._long_term.delete(eintrag.id))
        except Exception as fehler:  # noqa: BLE001
            return ToolResult.failure(f"Das Löschen ist gescheitert: {fehler}")

        if not geloescht:
            return ToolResult.failure("Der Eintrag ließ sich nicht löschen.")

        return ToolResult.success(f"Vergessen: {eintrag.content}")


def build_memory_tools(
    *, long_term: Any, preferences: Any = None, user_memory: Any = None
) -> list[Tool]:
    """Stellt die Gedächtniswerkzeuge zusammen."""

    return [
        RememberPreferenceTool(long_term, user_memory),
        ShowPreferencesTool(long_term, preferences),
        ForgetPreferenceTool(long_term),
    ]
