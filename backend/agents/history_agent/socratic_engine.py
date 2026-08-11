"""Der sokratische Lehrmodus (Abschnitte 3, 4, 5).

Die wichtigste Regel der ganzen Engine steht in Abschnitt 3:

    Der Professor soll nicht automatisch die Lösung liefern, wenn der
    Benutzer durch eigenes Denken zu einer Lösung gelangen kann.

Das ist leicht gesagt und schwer gebaut, weil ein Sprachmodell von sich aus
das Gegenteil tut. Es ist darauf trainiert, hilfreich zu sein, und
hilfreich heißt für es: antworten. Ein bloßer Hinweis im Systemprompt
(„stelle Gegenfragen") hält dem nicht stand, sobald die Frage konkret wird.

Dieses Modul setzt deshalb zwei Dinge um, die nicht vom Modell abhängen:

1. **Eine Entscheidung, ob überhaupt gefragt oder geantwortet wird.** Sie
   fällt hier, nach nachvollziehbaren Regeln, und nicht im Modell.
2. **Einen Vorrat konkreter Fragen**, gestaffelt nach Denkdimension und
   Niveau. Das Modell formuliert sie aus, es erfindet sie nicht.

## Wann doch geantwortet wird

Sokratisch heißt nicht stur. Es gibt Fälle, in denen eine Gegenfrage keine
Lehre ist, sondern eine Zumutung:

* Eine reine Faktenfrage („Wann starb Karl der Große?") – wer ein Datum
  nicht weiß, findet es nicht durch Nachdenken.
* Der Benutzer hat es schon zweimal versucht und kommt nicht weiter.
* Er bittet ausdrücklich um die Antwort.
* Es geht um eine Begriffsklärung, die er nicht herleiten kann.

In diesen Fällen wird geantwortet. Wer daraus ein Dogma macht, erzieht
niemanden, sondern nervt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.agents.history_agent.learning_profile import LEVELS, LearningProfile
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class SocraticDecision:
    """Ob gefragt oder geantwortet wird – und warum."""

    ask: bool
    reason: str
    questions: list[str]
    #: Die Denkdimension, um die es geht.
    dimension: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "nachfragen": self.ask,
            "begruendung": self.reason,
            "fragen": self.questions,
            "dimension": self.dimension,
        }


#: Der Fragenvorrat, nach Denkdimension und Anspruch.
#:
#: Die Staffelung ist keine Zierde. Eine Frage nach der impliziten Annahme
#: hinter einem Argument ist für jemanden, der gerade erst Ereignisse
#: einordnet, keine Anregung, sondern eine Mauer. Umgekehrt ist „Was
#: geschah zuerst?" für einen Fortgeschrittenen eine Beleidigung.
QUESTION_BANK: dict[str, dict[str, tuple[str, ...]]] = {
    "kausalitaet": {
        "einfach": (
            "Was war die Ursache, und was war der Anlass? Die beiden werden oft verwechselt.",
            "Wäre es auch ohne dieses Ereignis dazu gekommen?",
            "Was musste vorher gegeben sein, damit das überhaupt möglich wurde?",
        ),
        "mittel": (
            "Ist das eine Ursache oder nur etwas, das zeitlich davor lag?",
            "Wie würdest du zwischen langfristigen strukturellen Ursachen und "
            "unmittelbaren Auslösern unterscheiden?",
            "Welche dieser Ursachen war notwendig, welche nur begünstigend?",
        ),
        "anspruchsvoll": (
            "Du beschreibst einen Zusammenhang – was macht ihn zu einem "
            "kausalen und nicht bloß zu einer Gleichzeitigkeit?",
            "Welche Gegenprobe würde deine Kausalbehauptung entkräften?",
            "Wie verhalten sich Struktur und Ereignis in deiner Erklärung zueinander?",
        ),
    },
    "quellenkritik": {
        "einfach": (
            "Wer hat das geschrieben, und für wen?",
            "Wann ist die Quelle entstanden – vor, während oder nach dem Ereignis?",
            "Was will der Verfasser erreichen?",
        ),
        "mittel": (
            "Welche Interessen hatte der Verfasser, und wie zeigen sie sich im Text?",
            "Was steht nicht in der Quelle, obwohl man es erwarten würde?",
            "Was kann diese Quelle belegen – und was kann sie nicht belegen?",
        ),
        "anspruchsvoll": (
            "Welche Aussagekraft hat die Quelle für deine Fragestellung, "
            "und wo endet sie?",
            "Wie verhält sich die Entstehungssituation zur Adressatenfrage?",
            "Welche Quellengattung liegt vor, und was folgt daraus methodisch?",
        ),
    },
    "argumentation": {
        "einfach": (
            "Woran machst du das fest?",
            "Welche Quelle stützt diese Aussage?",
            "Warum?",
        ),
        "mittel": (
            "Welche Annahme steckt hinter deinem Argument?",
            "Was würde gegen deine These sprechen?",
            "Welche Gegenposition wäre möglich?",
        ),
        "anspruchsvoll": (
            "Deine These und dein Beleg sind beide plausibel – aber trägt der "
            "Beleg wirklich diese These?",
            "An welcher Stelle springst du von der Beschreibung zur Deutung?",
            "Welcher Befund müsste vorliegen, damit du deine These aufgibst?",
        ),
    },
    "kontextualisierung": {
        "einfach": (
            "Was geschah zur selben Zeit noch?",
            "Wie sah die Gesellschaft damals aus?",
        ),
        "mittel": (
            "Welche politischen, sozialen und wirtschaftlichen Bedingungen "
            "musst du berücksichtigen?",
            "Was verändert sich, wenn wir den Zeitraum erweitern?",
        ),
        "anspruchsvoll": (
            "Verwendest du hier einen Begriff, den die Zeitgenossen so nicht "
            "gekannt hätten?",
            "Was verändert sich, wenn du den Betrachtungsmaßstab wechselst – "
            "vom Reich zur Region, von der Region zum Dorf?",
        ),
    },
    "multiperspektivitaet": {
        "einfach": (
            "Wer erzählt hier – und wer kommt nicht vor?",
            "Wie hätte das jemand anderes erlebt?",
        ),
        "mittel": (
            "Was verändert sich, wenn wir die Perspektive des Akteurs wechseln?",
            "Wessen Sicht fehlt in deiner Darstellung?",
        ),
        "anspruchsvoll": (
            "Wessen Perspektive ist überliefert, und wessen ist es aus welchen "
            "Gründen nicht?",
            "Ist die Lücke in der Überlieferung zufällig oder aussagekräftig?",
        ),
    },
    "kontingenz": {
        "einfach": ("Hätte es auch anders kommen können?",),
        "mittel": (
            "Welche Alternativen standen den Beteiligten offen?",
            "Wussten die Handelnden, worauf es hinauslaufen würde?",
        ),
        "anspruchsvoll": (
            "Beschreibst du hier einen Verlauf oder eine Zwangsläufigkeit? "
            "Und woher weißt du das?",
            "Welche Handlungsspielräume hatten die Akteure tatsächlich?",
        ),
    },
    "vergleich": {
        "einfach": ("Wo siehst du Gemeinsamkeiten, wo Unterschiede?",),
        "mittel": (
            "Was ist die gemeinsame Bezugsgröße deines Vergleichs?",
            "Vergleichst du hier Vergleichbares?",
        ),
        "anspruchsvoll": (
            "Was soll der Vergleich zeigen, das die Einzelbetrachtung nicht zeigt?",
        ),
    },
    "historiographie": {
        "mittel": (
            "Wie hat die Forschung das bisher gesehen?",
            "Gibt es dazu unterschiedliche Positionen?",
        ),
        "anspruchsvoll": (
            "Worin genau besteht der Streit – in den Quellen, den Methoden "
            "oder den Fragestellungen?",
            "Aus welcher Forschungstradition kommt diese Deutung?",
        ),
    },
}


#: Signalwörter, an denen sich eine Denkdimension erkennen lässt.
#:
#: Bewusst grob. Es geht nicht um Klassifikation, sondern darum, eine
#: passendere Frage zu wählen als eine zufällige.
_DIMENSION_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kausalitaet", ("warum", "ursache", "ursachen", "führte zu", "auslöser",
                     "weshalb", "grund", "gründe", "bewirkt", "folge")),
    ("quellenkritik", ("quelle", "quellen", "dokument", "urkunde", "brief",
                       "chronik", "zeuge", "überliefert", "verfasser")),
    ("argumentation", ("these", "argument", "beweis", "belegen", "beleg",
                       "behaupte", "meine", "denke, dass")),
    ("multiperspektivitaet", ("perspektive", "sicht", "standpunkt", "betroffen")),
    ("kontingenz", ("hätte", "wäre", "alternative", "zwangsläufig", "unvermeidlich")),
    ("vergleich", ("vergleich", "verglichen", "unterschied", "gemeinsam", "ähnlich")),
    ("historiographie", ("forschung", "forschungsstand", "historiker",
                         "umstritten", "debatte", "kontrovers")),
    ("kontextualisierung", ("kontext", "hintergrund", "zusammenhang", "epoche",
                            "gesellschaft", "damals")),
)


#: Fragen, die reine Faktenabfragen sind. Hier hilft Nachdenken nicht.
_FACTUAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*wann\b", re.IGNORECASE),
    re.compile(r"^\s*wer war\b", re.IGNORECASE),
    re.compile(r"^\s*wie hieß\b", re.IGNORECASE),
    re.compile(r"^\s*wo (lag|liegt|befand)\b", re.IGNORECASE),
    re.compile(r"\bin welchem jahr\b", re.IGNORECASE),
    re.compile(r"\bwie viele\b", re.IGNORECASE),
)

#: Wendungen, mit denen jemand ausdrücklich um die Antwort bittet.
_EXPLICIT_ANSWER_REQUESTS: tuple[str, ...] = (
    "sag mir einfach",
    "sag es mir",
    "gib mir die antwort",
    "erklär mir",
    "erkläre mir",
    "ich will keine gegenfrage",
    "keine gegenfragen",
    "nenn mir",
    "nenne mir",
    "einfach die antwort",
    "ich komme nicht weiter",
    "ich weiß es nicht",
    "keine ahnung",
)

#: Wendungen, die Erschöpfung anzeigen. Wer aufgibt, braucht Hilfe, keine Frage.
_FRUSTRATION_MARKERS: tuple[str, ...] = (
    "ich verstehe es nicht",
    "verstehe ich nicht",
    "das ist zu schwer",
    "ich schaffe das nicht",
    "das bringt nichts",
    "hilf mir",
)


def detect_dimension(text: str) -> str:
    """Rät die Denkdimension einer Äußerung.

    Returns:
        Der Schlüssel aus :data:`QUESTION_BANK`, sonst ``"argumentation"``
        als brauchbarer Vorgabewert – nach der Begründung zu fragen passt
        fast immer.
    """

    lowered = text.lower()
    best = ""
    best_hits = 0

    for dimension, markers in _DIMENSION_MARKERS:
        hits = sum(1 for marker in markers if marker in lowered)
        if hits > best_hits:
            best = dimension
            best_hits = hits

    return best or "argumentation"


def tier_for_level(level: str) -> str:
    """Übersetzt das Niveau in eine Anspruchsstufe des Fragenvorrats."""

    try:
        index = LEVELS.index(level)
    except ValueError:
        index = 0

    if index <= 1:
        return "einfach"
    if index <= 4:
        return "mittel"
    return "anspruchsvoll"


def pick_questions(dimension: str, level: str, *, count: int = 2) -> list[str]:
    """Wählt passende Fragen aus dem Vorrat.

    Fällt eine Dimension auf der gewünschten Stufe aus, wird die nächst
    niedrigere genommen – lieber eine zu einfache Frage als gar keine.
    """

    bank = QUESTION_BANK.get(dimension) or QUESTION_BANK["argumentation"]
    order = {
        "anspruchsvoll": ("anspruchsvoll", "mittel", "einfach"),
        "mittel": ("mittel", "einfach", "anspruchsvoll"),
        "einfach": ("einfach", "mittel"),
    }[tier_for_level(level)]

    collected: list[str] = []
    for tier in order:
        for question in bank.get(tier, ()):
            if question not in collected:
                collected.append(question)
            if len(collected) >= count:
                return collected

    return collected


def looks_factual(text: str) -> bool:
    """Ob es sich um eine reine Faktenfrage handelt.

    Wer ein Datum nicht weiß, findet es nicht durch Nachdenken. Eine
    Gegenfrage wäre hier keine Lehre, sondern eine Schikane.
    """

    stripped = text.strip()
    if any(pattern.search(stripped) for pattern in _FACTUAL_PATTERNS):
        # „Warum" oder „inwiefern" im selben Satz hebt das wieder auf –
        # dann ist es doch eine Denkfrage.
        return not re.search(r"\b(warum|weshalb|inwiefern|wieso)\b", stripped, re.IGNORECASE)
    return False


def decide(
    text: str,
    profile: LearningProfile,
    *,
    attempts: int = 0,
    mode: str = "socratic",
) -> SocraticDecision:
    """Entscheidet, ob gefragt oder geantwortet wird.

    Args:
        text: Was der Benutzer gesagt hat.
        profile: Sein Lernprofil – bestimmt das Anspruchsniveau.
        attempts: Wie oft er es an dieser Stelle schon versucht hat.
        mode: Der aktive Professor-Modus. ``erklaeren`` schaltet das
            Nachfragen ab, ``socratic`` verstärkt es.

    Returns:
        Die Entscheidung samt Begründung. Die Begründung ist nicht Zierde:
        Sie geht ins Protokoll und lässt sich später nachlesen, wenn das
        Verhalten unpassend war.
    """

    lowered = text.lower()

    if mode == "erklaeren":
        return SocraticDecision(
            False, "Der Modus ERKLÄREN wurde ausdrücklich gewählt.", []
        )

    if any(marker in lowered for marker in _EXPLICIT_ANSWER_REQUESTS):
        return SocraticDecision(
            False, "Der Benutzer bittet ausdrücklich um die Antwort.", []
        )

    if any(marker in lowered for marker in _FRUSTRATION_MARKERS):
        return SocraticDecision(
            False,
            "Der Benutzer kommt nicht weiter. Eine weitere Frage wäre jetzt "
            "keine Anregung, sondern eine Zumutung.",
            [],
        )

    if attempts >= 2:
        return SocraticDecision(
            False,
            f"Nach {attempts} eigenen Versuchen ist Hilfe angebracht.",
            [],
        )

    if looks_factual(text):
        return SocraticDecision(
            False,
            "Reine Faktenfrage – wer ein Datum nicht weiß, findet es nicht "
            "durch Nachdenken.",
            [],
        )

    if len(text.strip()) < 12:
        return SocraticDecision(
            False, "Die Äußerung ist zu knapp, um daran anzuknüpfen.", []
        )

    dimension = detect_dimension(text)
    questions = pick_questions(dimension, profile.level)

    return SocraticDecision(
        True,
        "Hier kann der Benutzer selbst zu einer Antwort kommen.",
        questions,
        dimension,
    )


def guidance_for_prompt(decision: SocraticDecision) -> str:
    """Formuliert die Anweisung an das Sprachmodell.

    Sie steht bewusst am *Ende* des Systemprompts. Ein Modell hält sich an
    das, was zuletzt kam, deutlich zuverlässiger als an das, was zwischen
    zwanzig anderen Regeln stand.
    """

    if not decision.ask:
        return (
            "In diesem Fall antwortest du direkt und sachlich. "
            f"Grund: {decision.reason}"
        )

    fragen = "\n".join(f"  - {frage}" for frage in decision.questions)
    return (
        "WICHTIG – in dieser Antwort gibst du die Lösung NICHT preis.\n"
        "Der Benutzer kann selbst darauf kommen. Stelle stattdessen eine "
        "Gegenfrage und gib höchstens einen Hinweis, der den nächsten "
        "Denkschritt ermöglicht, ohne ihn abzunehmen.\n"
        "Nimm eine dieser Fragen als Ausgangspunkt und formuliere sie "
        "natürlich aus – nicht wörtlich abschreiben:\n"
        f"{fragen}\n"
        "Stelle genau EINE Frage. Zwei Fragen auf einmal beantwortet niemand."
    )
