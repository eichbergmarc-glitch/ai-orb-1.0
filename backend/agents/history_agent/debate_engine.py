"""Die Debatte (Abschnitt 25).

Der Professor nimmt bewusst die Gegenposition ein. Das ist die härteste
Übung überhaupt, weil sie den Benutzer zwingt, seine eigene Position zu
verteidigen statt sie nur zu behaupten – und weil dabei sichtbar wird,
was an ihr trägt und was nur gut klingt.

Zwei Dinge müssen dabei gesichert sein, sonst schadet die Übung mehr als
sie nützt.

Erstens: Der Professor muss ankündigen, dass er die Gegenposition
einnimmt. Ein Betreuer, der plötzlich das Gegenteil vertritt, ohne es zu
sagen, verwirrt und untergräbt sein eigenes Wort.

Zweitens: Er muss am Ende aus der Rolle treten und bewerten. Eine Debatte
ohne Auswertung ist ein Streitgespräch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

#: Woran ein Argument gemessen wird.
CRITERIA: dict[str, str] = {
    "argumentqualitaet": "Trägt die Begründung die Behauptung?",
    "quellenbasis": "Stützt sich das Argument auf Quellen?",
    "konsistenz": "Widerspricht sich die Position an keiner Stelle?",
    "gegenargumente": "Werden Einwände ernsthaft behandelt?",
    "plausibilitaet": "Ist die Deutung historisch plausibel?",
}


@dataclass(slots=True)
class DebateRound:
    """Ein Schlagabtausch."""

    user_argument: str
    counter: str = ""
    scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "argument": self.user_argument,
            "gegenrede": self.counter,
            "bewertung": {k: round(v, 2) for k, v in self.scores.items()},
        }


@dataclass(slots=True)
class DebateSession:
    """Eine laufende Debatte."""

    topic: str
    user_position: str
    rounds: list[DebateRound] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def averages(self) -> dict[str, float]:
        """Der Durchschnitt je Kriterium über alle Runden."""

        result: dict[str, float] = {}
        for key in CRITERIA:
            values = [r.scores[key] for r in self.rounds if key in r.scores]
            if values:
                result[key] = sum(values) / len(values)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "thema": self.topic,
            "position": self.user_position,
            "runden": [r.to_dict() for r in self.rounds],
            "durchschnitt": {k: round(v, 2) for k, v in self.averages.items()},
        }


def opening_prompt(topic: str, user_position: str) -> str:
    """Die Anweisung für den Einstieg in die Debatte."""

    return (
        f"DEBATTE – Thema: {topic}\n"
        f"Die Position des Benutzers: „{user_position}“\n\n"
        "Kündige zuerst in einem Satz an, dass du bewusst die Gegenposition "
        "einnimmst – er soll wissen, dass das eine Übung ist und nicht deine "
        "Überzeugung.\n\n"
        "Bringe dann das STÄRKSTE Argument gegen seine Position, nicht das "
        "bequemste. Eine Debatte gegen ein schwaches Gegenargument lehrt "
        "nichts.\n\n"
        "Schließe mit einer Aufforderung, die ihn zum Argumentieren bringt. "
        "Halte dich kurz: Ein Absatz, nicht drei."
    )


def rebuttal_prompt(session: DebateSession) -> str:
    """Die Anweisung für die nächste Gegenrede."""

    letzte = session.rounds[-1].user_argument if session.rounds else ""
    return (
        f"DEBATTE, Runde {len(session.rounds) + 1} – Thema: {session.topic}.\n"
        f"Der Benutzer hat gerade vorgebracht: „{letzte[:400]}“\n\n"
        "Du vertrittst weiterhin die Gegenposition. Greif den schwächsten "
        "Punkt seines Arguments an – aber fair: Wenn er etwas gut belegt hat, "
        "räum das ein, bevor du weitermachst. Ein Gegner, der nichts gelten "
        "lässt, wird nicht ernst genommen.\n\n"
        "Ein Absatz. Eine Frage am Ende."
    )


def evaluation_prompt(session: DebateSession) -> str:
    """Die Anweisung, aus der Rolle zu treten und zu bewerten."""

    kriterien = "\n".join(f"  - {name}: {frage}" for name, frage in CRITERIA.items())
    return (
        "DEBATTE BEENDET. Tritt jetzt ausdrücklich aus der Gegenposition "
        "heraus – sage, dass du sie nur eingenommen hast, um die Argumentation "
        "zu prüfen.\n\n"
        f"Bewerte danach die Argumentation des Benutzers an diesen Punkten:\n"
        f"{kriterien}\n\n"
        "Nenne zuerst, was wirklich getragen hat. Dann höchstens zwei "
        "Schwachstellen, jeweils mit dem Hinweis, was sie stärker machen "
        "würde. Sage am Ende ehrlich, ob seine Position nach diesem "
        "Schlagabtausch stärker oder schwächer dasteht."
    )
