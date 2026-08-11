"""Forschungsfragen prüfen und entwickeln (Abschnitte 13, 14).

Eine Forschungsfrage ist der Punkt, an dem eine wissenschaftliche Arbeit
gelingt oder scheitert, und sie ist zugleich das, was am seltensten
geprüft wird. „Warum war die Französische Revolution wichtig?“ klingt nach
einer Frage; sie ist keine, weil sie weder Zeitraum noch Ebene noch
Maßstab benennt und deshalb jede beliebige Antwort zulässt.

Die Prüfung hier ist bewusst regelbasiert und nicht dem Sprachmodell
überlassen. Ein Modell findet an fast jeder Frage etwas zu loben; die
Mängel, um die es geht, sind aber formaler Art und lassen sich benennen:
fehlender Zeitraum, fehlender Raum, unbestimmte Wertbegriffe, eine im
Fragewort schon enthaltene Antwort. Wer sie regelbasiert prüft, bekommt
jedes Mal dieselbe Auskunft – und darauf kommt es bei einem Prüfmaßstab an.

Was das Modell danach tut, ist der schwierigere Teil: aus einer schlechten
Frage gemeinsam mit dem Benutzer eine bessere entwickeln. Nicht *für* ihn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class QuestionFlaw:
    """Ein Mangel an einer Forschungsfrage."""

    kind: str
    explanation: str
    #: Was der Benutzer konkret tun kann.
    remedy: str
    #: Wie schwer der Mangel wiegt: 1 Hinweis, 2 Problem, 3 Ausschluss.
    severity: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "art": self.kind,
            "erklaerung": self.explanation,
            "abhilfe": self.remedy,
            "gewicht": self.severity,
        }


@dataclass(slots=True)
class QuestionAssessment:
    """Das Ergebnis der Prüfung."""

    question: str
    flaws: list[QuestionFlaw] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        """Ob die Frage als Ausgangspunkt taugt.

        Ein einzelner Hinweis macht eine Frage nicht unbrauchbar. Ein
        Ausschlussgrund oder zwei Probleme schon.
        """

        if any(flaw.severity >= 3 for flaw in self.flaws):
            return False
        return sum(1 for flaw in self.flaws if flaw.severity >= 2) < 2

    @property
    def verdict(self) -> str:
        if not self.flaws:
            return "Die Frage ist tragfähig."
        if self.is_usable:
            return "Die Frage ist brauchbar, lässt sich aber schärfen."
        return "Die Frage trägt in dieser Form noch nicht."

    def to_dict(self) -> dict[str, Any]:
        return {
            "frage": self.question,
            "urteil": self.verdict,
            "tragfaehig": self.is_usable,
            "maengel": [flaw.to_dict() for flaw in self.flaws],
        }


#: Die Schritte der Fragestellungs-Werkstatt (Abschnitt 14).
WORKSHOP_STEPS: tuple[tuple[str, str], ...] = (
    ("thema", "Womit willst du dich beschäftigen? Noch ganz grob."),
    ("interesse", "Was daran interessiert dich wirklich? Was willst du wissen, "
                  "das du noch nicht weißt?"),
    ("zeitraum", "Welchen Zeitraum nimmst du in den Blick – und warum genau diesen? "
                 "Die Grenzen müssen sich begründen lassen."),
    ("raum", "Welchen Raum? Ein Reich, eine Stadt, ein Dorf, ein Netzwerk?"),
    ("akteure", "Wer handelt in deiner Frage? Wessen Tun oder Erleben untersuchst du?"),
    ("problem", "Was ist daran das Problem? Was ist unklar, strittig oder erklärungsbedürftig?"),
    ("forschungsstand", "Was sagt die Forschung dazu bisher? Wo widerspricht sie sich?"),
    ("quellen", "Womit willst du das beantworten? Welche Quellen gibt es, "
                "und sind sie dir zugänglich?"),
    ("forschungsfrage", "Formuliere die Frage in einem Satz. Sie muss beantwortbar sein."),
    ("these", "Welche Antwort erwartest du? Das ist deine Arbeitsthese – "
              "sie darf sich unterwegs ändern."),
)

#: Wertende Wörter ohne festen Gehalt. Sie klingen nach Fragestellung und
#: lassen doch jede Antwort zu.
_VAGUE_TERMS: tuple[str, ...] = (
    "wichtig", "bedeutend", "bedeutsam", "interessant", "entscheidend",
    "großartig", "schrecklich", "gut", "schlecht", "erfolgreich",
    "revolutionär", "fortschrittlich", "rückständig", "modern",
)

#: Fragewörter, die nur zur Beschreibung führen.
_DESCRIPTIVE_OPENERS: tuple[str, ...] = (
    "was geschah", "was passierte", "wer war", "wann war", "wann fand",
    "wie hieß", "beschreibe", "nenne", "liste",
)

#: Formulierungen, die die Antwort schon voraussetzen.
_LOADED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwarum (?:war|ist|waren|sind) .{0,40}\b(so|derart|besonders)\b", re.I),
    re.compile(r"\bwieso (?:scheiterte|versagte|misslang)\b", re.I),
    re.compile(r"\bweshalb (?:musste|mussten)\b", re.I),
    re.compile(r"\binwiefern (?:beweist|zeigt|belegt)\b", re.I),
)

#: Ein Zeitraum ist genannt, wenn Jahreszahlen, Jahrhunderte oder Epochen
#: vorkommen.
_TIME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b1[0-9]{3}\b"),
    re.compile(r"\b20[0-2][0-9]\b"),
    re.compile(r"\b\d{1,2}\.\s*jahrhundert", re.I),
    re.compile(r"\bzwischen\b.{0,30}\bund\b", re.I),
    re.compile(
        r"\b(mittelalter|antike|neuzeit|reformation|aufkl(ä|ae)rung|"
        r"kaiserreich|weimarer|nachkriegs|vormärz|vormaerz|zwischenkriegs)\w*",
        re.I,
    ),
)

#: Räumliche Eingrenzungen.
_SPACE_PATTERN = re.compile(
    r"\b(in|im|bei|zu|für|fuer)\s+(?:der|dem|den|die|das)?\s*[A-ZÄÖÜ][\wäöüß-]{2,}",
)


def assess(question: str) -> QuestionAssessment:
    """Prüft eine Forschungsfrage auf die üblichen Mängel."""

    text = question.strip()
    assessment = QuestionAssessment(question=text)
    lowered = text.lower()

    if len(text) < 15:
        assessment.flaws.append(
            QuestionFlaw(
                "zu knapp",
                "Das ist noch keine Frage, sondern ein Stichwort.",
                "Formuliere einen vollständigen Fragesatz.",
                severity=3,
            )
        )
        return assessment

    # --- Zu breit -------------------------------------------------------------
    found_vague = [term for term in _VAGUE_TERMS if re.search(rf"\b{term}\b", lowered)]
    if found_vague:
        assessment.flaws.append(
            QuestionFlaw(
                "unbestimmter Wertbegriff",
                f"„{found_vague[0]}“ ist ein Urteil, kein Untersuchungsgegenstand. "
                "Solange nicht feststeht, woran es sich bemisst, lässt die Frage "
                "jede Antwort zu.",
                f"Ersetze „{found_vague[0]}“ durch das, was du tatsächlich messen "
                "oder beobachten willst.",
            )
        )

    # --- Zeitraum -------------------------------------------------------------
    if not any(pattern.search(text) for pattern in _TIME_PATTERNS):
        assessment.flaws.append(
            QuestionFlaw(
                "fehlende zeitliche Eingrenzung",
                "Ohne Zeitraum ist nicht entscheidbar, was zur Untersuchung "
                "gehört und was nicht.",
                "Nenne Anfang und Ende – und sei darauf gefasst, die Wahl "
                "begründen zu müssen.",
            )
        )

    # --- Raum -----------------------------------------------------------------
    if not _SPACE_PATTERN.search(text):
        assessment.flaws.append(
            QuestionFlaw(
                "fehlende räumliche Eingrenzung",
                "Es ist nicht erkennbar, worauf sich die Frage geografisch bezieht.",
                "Nenne den Raum: ein Reich, eine Region, eine Stadt, ein Milieu.",
                severity=1,
            )
        )

    # --- Rein deskriptiv ------------------------------------------------------
    if any(lowered.startswith(opener) for opener in _DESCRIPTIVE_OPENERS):
        assessment.flaws.append(
            QuestionFlaw(
                "rein deskriptiv",
                "Die Frage verlangt eine Beschreibung, keine Erklärung. Sie ist "
                "beantwortet, sobald jemand nachgeschlagen hat.",
                "Frage nicht, was geschah, sondern warum, unter welchen "
                "Bedingungen oder mit welcher Wirkung.",
                # Ausschlusskriterium: Eine Frage, die durch Nachschlagen
                # beantwortet ist, traegt keine Untersuchung. Das ist kein
                # Schoenheitsfehler, sondern der Unterschied zwischen einem
                # Referat und einer Arbeit.
                severity=3,
            )
        )

    # --- Antwort schon enthalten ----------------------------------------------
    if any(pattern.search(text) for pattern in _LOADED_PATTERNS):
        assessment.flaws.append(
            QuestionFlaw(
                "vorausgesetzte Antwort",
                "Die Frage setzt bereits als gegeben voraus, was erst zu zeigen "
                "wäre. Wer so fragt, findet nur noch Belege.",
                "Formuliere ergebnisoffen: „Wie veränderte sich …“ statt "
                "„Warum war … so …“.",
            )
        )

    # --- Ja/Nein --------------------------------------------------------------
    if re.match(r"^\s*(war|ist|hatte|gab es|kann man|sollte)\b", lowered):
        assessment.flaws.append(
            QuestionFlaw(
                "Entscheidungsfrage",
                "Eine Frage, die sich mit ja oder nein beantworten lässt, trägt "
                "keine Untersuchung.",
                "Mache daraus eine Wie- oder Inwiefern-Frage.",
            )
        )

    # --- Zu eng ---------------------------------------------------------------
    if re.search(r"\bam\s+\d{1,2}\.\s*\w+\s+1[0-9]{3}\b", lowered) and len(text) < 90:
        assessment.flaws.append(
            QuestionFlaw(
                "zu eng",
                "Ein einzelner Tag trägt selten eine wissenschaftliche Arbeit – "
                "es sei denn, er steht für etwas Größeres.",
                "Weite den Zeitraum, oder mache deutlich, wofür dieser Tag steht.",
                severity=1,
            )
        )

    return assessment


def improvement_prompt(assessment: QuestionAssessment) -> str:
    """Erzeugt die Anweisung, mit der das Modell weiterarbeitet.

    Es soll die bessere Frage nicht liefern, sondern erarbeiten lassen –
    das ist der Unterschied zwischen einem Betreuer und einem Automaten.
    """

    if not assessment.flaws:
        return (
            "Die Frage ist formal tragfähig. Prüfe inhaltlich weiter: Gibt es "
            "dazu genug Quellen? Ist sie in der Forschung schon beantwortet? "
            "Frage den Benutzer danach, statt es zu behaupten."
        )

    maengel = "\n".join(
        f"  - {flaw.kind}: {flaw.explanation} → {flaw.remedy}"
        for flaw in sorted(assessment.flaws, key=lambda item: -item.severity)
    )

    return (
        f"Die Forschungsfrage lautet: „{assessment.question}“\n\n"
        f"Die formale Prüfung hat ergeben:\n{maengel}\n\n"
        "Sprich den WICHTIGSTEN dieser Punkte an – nur einen, nicht alle auf "
        "einmal. Erkläre kurz, warum er zählt, und stelle dann eine Frage, die "
        "den Benutzer dazu bringt, die Eingrenzung selbst vorzunehmen. "
        "Liefere die verbesserte Frage NICHT fertig; er soll sie formulieren."
    )


def next_workshop_step(collected: dict[str, str]) -> tuple[str, str] | None:
    """Der nächste Schritt der Fragestellungs-Werkstatt.

    Args:
        collected: Was bereits beantwortet wurde, nach Schrittschlüssel.

    Returns:
        Schlüssel und Frage, oder ``None``, wenn alles beisammen ist.
    """

    for key, prompt in WORKSHOP_STEPS:
        if not collected.get(key, "").strip():
            return key, prompt
    return None


def workshop_progress(collected: dict[str, str]) -> dict[str, Any]:
    """Wie weit die Werkstatt gediehen ist."""

    done = [key for key, _ in WORKSHOP_STEPS if collected.get(key, "").strip()]
    return {
        "erledigt": done,
        "offen": [key for key, _ in WORKSHOP_STEPS if key not in done],
        "anteil": round(len(done) / len(WORKSHOP_STEPS), 2),
    }
