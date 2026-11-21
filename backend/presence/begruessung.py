"""Begruessung nach dem Start - jedes Mal anders.

Marc, 17.11.2026: Der Orb soll ihn nach dem Neustart begruessen, jedes Mal
anders, und sich ab und zu der Tageszeit anpassen.

Bewusst ohne Sprachmodell: Die Begruessung kommt, sobald die Stimme
bereit ist, und darf nicht auf einen Modellabruf warten (Grundanforderung:
der Orb antwortet fluessig).

Wie die Abwechslung entsteht
----------------------------
* Ein Gruss besteht aus Anrede und einem kurzen Nachsatz. Beides wird
  gezogen - das ergibt weit ueber hundert Kombinationen.
* Etwa jede dritte Begruessung bezieht sich auf die Tageszeit ("Guten
  Morgen", "Noch wach?"), die anderen sind tageszeitneutral. Immer
  "Guten Morgen" waere wieder ein Ritual.
* Die letzten Begruessungen werden gemerkt (``data/begruessungen.json``)
  und nicht wiederholt.
* Ab und zu faellt der Name.
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Sequence

#: Wie viele der letzten Begruessungen nicht wiederkommen duerfen.
GEDAECHTNIS = 12
#: Anteil der Begruessungen mit Tageszeitbezug.
ANTEIL_TAGESZEIT = 0.35
#: Anteil mit Namen.
ANTEIL_NAME = 0.3

NEUTRAL_ANREDE: tuple[str, ...] = (
    "Hallo", "Hey", "Da bin ich wieder", "Hallo zusammen", "Schön, dich zu hören",
    "So", "Hallo nochmal", "Grüezi", "Salü", "Ich bin zurück",
)
NEUTRAL_NACHSATZ: tuple[str, ...] = (
    "Ich bin bereit.",
    "Was steht an?",
    "Womit fangen wir an?",
    "Ich höre dir zu.",
    "Alles läuft, du kannst loslegen.",
    "Was darf ich für dich tun?",
    "Ich bin wieder ganz da.",
    "Frisch gestartet und startklar.",
    "Wo waren wir stehen geblieben?",
    "Sag einfach, worum es geht.",
)

#: Tageszeit -> (Anreden, Nachsaetze). Stunde von-bis (bis ausschliesslich).
TAGESZEITEN: tuple[tuple[int, int, tuple[str, ...], tuple[str, ...]], ...] = (
    (5, 11,
     ("Guten Morgen", "Morgen", "Einen schönen guten Morgen"),
     ("Kaffee schon da?", "Gut geschlafen?", "Bereit für den Tag?", "Ich bin wach, du auch?")),
    (11, 14,
     ("Hallo", "Grüezi", "Schönen Mittag"),
     ("Mitten im Tag, ich bin bereit.", "Schon was gegessen?", "Was steht heute Mittag an?")),
    (14, 18,
     ("Guten Tag", "Hallo", "Schönen Nachmittag"),
     ("Wie läuft dein Nachmittag?", "Ich bin bereit für die zweite Tageshälfte.", "Was steht noch an heute?")),
    (18, 22,
     ("Guten Abend", "Schönen Abend", "Hallo"),
     ("Wie war dein Tag?", "Feierabend oder noch was vor?", "Ich bin da, ganz entspannt.")),
    (22, 29,  # 22 bis 5 Uhr (29 = 24 + 5)
     ("Noch wach", "Hallo, Nachteule", "Guten Abend, oder eher gute Nacht"),
     ("Ich leiste dir Gesellschaft.", "Was beschäftigt dich so spät?", "Ich bin leise, aber da.")),
)


def _tageszeit(stunde: int) -> tuple[Sequence[str], Sequence[str]]:
    for von, bis, anreden, nachsaetze in TAGESZEITEN:
        s = stunde if stunde >= 5 else stunde + 24
        if von <= s < bis:
            return anreden, nachsaetze
    return NEUTRAL_ANREDE, NEUTRAL_NACHSATZ


def _speicher() -> Path | None:
    try:
        from backend.utils.paths import get_data_dir

        return get_data_dir() / "begruessungen.json"
    except Exception:  # noqa: BLE001 - ohne Datenordner eben ohne Gedaechtnis.
        return None


def _bisherige(pfad: Path | None) -> list[str]:
    if pfad is None or not pfad.exists():
        return []
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        return [str(x) for x in daten][-GEDAECHTNIS:]
    except Exception:  # noqa: BLE001
        return []


def _merken(pfad: Path | None, bisher: list[str], neu: str) -> None:
    if pfad is None:
        return
    try:
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(
            json.dumps((bisher + [neu])[-GEDAECHTNIS:], ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - eine Begruessung darf nie scheitern.
        pass


def erzeugen(
    *,
    name: str = "",
    einschraenkungen: bool = False,
    jetzt: datetime | None = None,
    zufall: random.Random | None = None,
    speicher: Path | None | bool = True,
) -> str:
    """Eine neue Begruessung.

    Args:
        name: Der Name des Benutzers; faellt ab und zu.
        einschraenkungen: Ob der Start mit Einschraenkungen lief.
        jetzt: Uhrzeit (fuer Tests).
        zufall: Zufallsquelle (fuer Tests).
        speicher: ``True`` = Standardablage, ``None``/``False`` = nichts merken,
            sonst ein eigener Pfad.
    """

    z = zufall or random.Random()
    jetzt = jetzt or datetime.now()
    pfad: Path | None
    if speicher is True:
        pfad = _speicher()
    elif speicher in (None, False):
        pfad = None
    else:
        pfad = speicher  # type: ignore[assignment]
    bisher = _bisherige(pfad)

    gruss = ""
    for _ in range(25):
        if z.random() < ANTEIL_TAGESZEIT:
            anreden, nachsaetze = _tageszeit(jetzt.hour)
        else:
            anreden, nachsaetze = NEUTRAL_ANREDE, NEUTRAL_NACHSATZ
        anrede = z.choice(list(anreden))
        nachsatz = z.choice(list(nachsaetze))
        if name and z.random() < ANTEIL_NAME:
            anrede = f"{anrede}, {name}"
        trenner = "?" if anrede.startswith("Noch wach") else "."
        gruss = f"{anrede}{trenner} {nachsatz}"
        if gruss not in bisher:
            break

    if einschraenkungen:
        gruss += " Ein paar Dinge laufen eingeschränkt, Details stehen im Startbericht."
    _merken(pfad, bisher, gruss.split(" Ein paar Dinge")[0])
    return gruss
