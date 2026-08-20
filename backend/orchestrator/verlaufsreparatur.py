"""Das Verhörte wieder herausnehmen.

## Wozu

Am 18.08.2026 um 11:21 lief eine fremde Stimme mit. Zwei ihrer Sätze
kamen durch die Erkennung und wurden beantwortet::

    11:21:48  "Nachwägung, Konkunft, Sekundism. ... die Unwahrung gegen
               das Patienten ist eine solche Form der Konflikation."
    11:22:08  "Das ist unverteidigbar, wenn ein Schwierigem was ähnlich
               ist ... wie ich als Südpaulinsist, Hallo Orb!"

Beide stehen seitdem im Gesprächsverlauf - als hätte der Benutzer sie
gesagt. Und weil jede weitere Antwort den ganzen Verlauf mitliest, färbt
dieser Unsinn ab: Der Orb bezieht sich darauf, sucht einen Sinn darin,
erfindet Zusammenhänge. Im Protokoll wächst der Modellkontext von 17 auf
23 Nachrichten, und die falschen zwei bleiben in jeder einzelnen davon.

Genau das meint "er hat angefangen zu halluzinieren und nicht mehr
aufgehört". Es ist keine Laune des Sprachmodells, sondern ein
verunreinigter Verlauf - eine Ursache, die von selbst nicht vergeht.

## Die Abhilfe

Der Benutzer hat es um 11:22:45 selbst gesagt::

    "Du hast eine falsche Stimme gehört, Orb, du sollst nur auf mich
     hören."

Dieser Satz muss wirken. Er nimmt die letzten Wechsel wieder heraus -
ohne Sprachmodell, ohne Werkzeug, ohne Umweg: Ein fester Satz, eine feste
Wirkung. Was einmal falsch im Verlauf steht, bekommt man sonst nur durch
einen Neustart wieder heraus, und das weiss niemand.

Die Anzahl der herausgenommenen Wechsel ist bewusst klein (zwei), denn
ein Wechsel zu wenig lässt sich mit demselben Satz noch einmal entfernen,
ein Wechsel zu viel dagegen ist verloren.
"""

from __future__ import annotations

import re

#: Wendungen, mit denen man einen falsch verstandenen Wechsel zurücknimmt.
#: Sie sind so gewählt, dass sie im gewöhnlichen Gespräch nicht vorkommen
#: - "vergiss das" allein wäre zu nah an einer beiläufigen Bemerkung.
_MUSTER = (
    r"das war nicht ich",
    r"das war ich nicht",
    r"das habe ich (?:gar )?nicht gesagt",
    r"das hab ich (?:gar )?nicht gesagt",
    r"du hast (?:eine|die) (?:falsche|fremde|andere) stimme",
    r"das war (?:eine|die) (?:falsche|fremde|andere) stimme",
    r"das war (?:jemand|wer) anderes",
    r"das war (?:der )?fernseher",
    r"das war nicht an dich",
    r"(?:das )?war nicht f(?:ü|ue)r dich",
    r"vergiss (?:das|die) letzte[nrs]?",
    r"nimm (?:das|die) letzte[nrs]? zur(?:ü|ue)ck",
    r"streich (?:das|die) letzte[nrs]?",
    r"h(?:ö|oe)r nur auf mich",
    r"du sollst nur auf mich h(?:ö|oe)ren",
)

_ERKENNER = re.compile("|".join(_MUSTER), re.IGNORECASE)

#: So viele Wechsel (Frage + Antwort) werden herausgenommen.
STANDARD_WECHSEL = 2


def ist_reparaturbefehl(text: str) -> bool:
    """Ob der Satz einen falsch verstandenen Wechsel zurücknehmen will."""

    knapp = " ".join(str(text or "").split())
    if not knapp:
        return False
    # Umlaute und Satzzeichen stoeren die Mustersuche nicht, weil die
    # Muster beide Schreibweisen kennen; nur die Kleinschreibung wird
    # vereinheitlicht.
    return bool(_ERKENNER.search(knapp.lower()))


def antwort(entfernt: int) -> str:
    """Die Bestätigung im Klartext - kurz, damit sie nicht stört."""

    if entfernt <= 0:
        return "Da war nichts mehr, was ich herausnehmen könnte. Ich höre."
    if entfernt == 1:
        return "Ich habe den letzten Wortwechsel vergessen. Ich höre nur auf dich."
    return (
        f"Ich habe die letzten {entfernt} Wortwechsel vergessen. "
        "Ich höre nur auf dich."
    )
