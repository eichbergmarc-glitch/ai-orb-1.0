"""Fehleranalyse, Anachronismusprüfung und akademisches Feedback.

Deckt die Abschnitte 7, 8, 9 und 17 der Vorgabe ab.

Der Kern ist eine Unterscheidung, die in der Vorgabe zu Recht sehr genau
gezogen wird: Ein Faktenfehler ist etwas anderes als ein Kausalfehler, und
beide sind etwas anderes als ein Anachronismus. Wer das zusammenwirft und
„das stimmt so nicht“ sagt, hat nichts erklärt. Wer sagt „du verwechselst
hier den Anlass mit der Ursache“, hat gelehrt.

## Was hier entschieden wird und was nicht

Ob eine historische Tatsache stimmt, kann dieses Modul nicht wissen – das
muss das Sprachmodell beurteilen, und es muss dabei ehrlich bleiben
(Abschnitt 27). Was dieses Modul kann, ist das Formale: die Struktur einer
Argumentation prüfen, Signalwörter für Kausalbehauptungen ohne Beleg
finden, moderne Begriffe in historischen Zusammenhängen erkennen.

Das ist weniger, als es klingt, und mehr, als man denkt. Gerade der
Anachronismus ist ein Fehler, den ein Sprachmodell selbst gerne begeht –
es hat schließlich moderne Texte gelesen. Eine Liste, die ihn unabhängig
vom Modell erkennt, ist deshalb kein Beiwerk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


#: Die Fehlerarten aus Abschnitt 8, mit ihrer Erklärung.
ERROR_KINDS: dict[str, str] = {
    "faktenfehler": "Eine historische Tatsache ist falsch wiedergegeben.",
    "chronologiefehler": "Ereignisse sind zeitlich falsch eingeordnet.",
    "kausalfehler": "Ursache und Folge sind vertauscht, oder eine Abfolge "
                    "wird für eine Verursachung gehalten.",
    "kontextfehler": "Der historische Zusammenhang fehlt oder ist falsch.",
    "interpretationsfehler": "Eine Quelle oder ein Ereignis ist falsch gedeutet.",
    "argumentationsfehler": "Die These ist nicht ausreichend begründet.",
    "quellenfehler": "Die Quelle ist nicht richtig eingeordnet.",
    "begrifflicher_fehler": "Ein historischer Begriff wird anachronistisch verwendet.",
    "methodischer_fehler": "Die Methode passt nicht zur Fragestellung.",
}


@dataclass(slots=True)
class Finding:
    """Ein Befund in einem Text des Benutzers."""

    kind: str
    excerpt: str
    explanation: str
    question: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "art": self.kind,
            "stelle": self.excerpt,
            "erklaerung": self.explanation,
            "rueckfrage": self.question,
        }


@dataclass(slots=True)
class ArgumentStructure:
    """Die Bestandteile einer Argumentation (Abschnitt 7)."""

    has_claim: bool = False
    has_reason: bool = False
    has_evidence: bool = False
    has_conclusion: bool = False
    has_counterargument: bool = False
    findings: list[Finding] = field(default_factory=list)

    @property
    def missing(self) -> list[str]:
        """Was fehlt – in der Reihenfolge, in der es zählt."""

        gaps: list[str] = []
        if not self.has_claim:
            gaps.append("eine erkennbare These")
        if not self.has_reason:
            gaps.append("eine Begründung")
        if not self.has_evidence:
            gaps.append("ein Beleg aus einer Quelle")
        if not self.has_counterargument:
            gaps.append("die Auseinandersetzung mit einer Gegenposition")
        return gaps

    def to_dict(self) -> dict[str, Any]:
        return {
            "these": self.has_claim,
            "begruendung": self.has_reason,
            "beleg": self.has_evidence,
            "schluss": self.has_conclusion,
            "gegenargument": self.has_counterargument,
            "fehlt": self.missing,
            "befunde": [finding.to_dict() for finding in self.findings],
        }


#: Moderne Begriffe, die auf ältere Gesellschaften oft unbedacht übertragen
#: werden (Abschnitt 9).
#:
#: Die Liste ist nicht als Verbot gemeint. Manche dieser Begriffe lassen
#: sich mit Bedacht verwenden – aber eben mit Bedacht, und darum geht es:
#: Der Professor fragt nach, er verbietet nicht.
ANACHRONISTIC_TERMS: dict[str, str] = {
    "nationalstaat": "Der Nationalstaat ist eine Bildung des 19. Jahrhunderts.",
    "nationalbewusstsein": "Nationales Bewusstsein in heutigem Sinn setzt das "
                           "19. Jahrhundert voraus.",
    "demokratie": "Der Begriff meint heute etwas anderes als in der Antike "
                  "oder der Frühen Neuzeit.",
    "öffentliche meinung": "Eine Öffentlichkeit in diesem Sinn entsteht erst "
                           "im 18. Jahrhundert.",
    "menschenrechte": "Als politisch wirksame Kategorie erst seit dem "
                      "18. Jahrhundert.",
    "kapitalismus": "Ein Begriff des 19. Jahrhunderts, rückwirkend nur mit "
                    "Vorbehalt anwendbar.",
    "rassismus": "Der Begriff und die zugehörige Ideologie sind neuzeitlich.",
    "wirtschaftswachstum": "Setzt eine statistische Erfassung voraus, die es "
                           "vorher nicht gab.",
    "arbeitslosigkeit": "Als soziale Kategorie ein Phänomen der Industriegesellschaft.",
    "mittelschicht": "Ein Schichtmodell moderner Gesellschaften.",
    "propaganda": "In heutiger Bedeutung ein Begriff des 20. Jahrhunderts.",
    "totalitär": "Eine Kategorie der Zwischenkriegszeit und danach.",
    "ideologie": "Der Begriff entsteht um 1800.",
    "privatsphäre": "Setzt eine Trennung von privat und öffentlich voraus, die "
                    "historisch geworden ist.",
    "kindheit": "Als eigener Lebensabschnitt ein Konzept der Neuzeit.",
}

#: Epochenwörter, in deren Nähe ein moderner Begriff besonders auffällt.
_EARLY_PERIOD_MARKERS: tuple[str, ...] = (
    "mittelalter", "antike", "römisch", "roemisch", "karolinger", "ottonen",
    "staufer", "frühe neuzeit", "fruehe neuzeit", "reformation", "16. jahrhundert",
    "17. jahrhundert", "15. jahrhundert", "14. jahrhundert", "13. jahrhundert",
    "kreuzzug", "feudal", "ständisch", "staendisch",
)

#: Wörter, die eine Kausalbehauptung anzeigen.
_CAUSAL_MARKERS: tuple[str, ...] = (
    "weil", "daher", "deshalb", "deswegen", "führte zu", "fuehrte zu",
    "verursachte", "bewirkte", "hatte zur folge", "resultierte", "aufgrund",
    "infolge", "somit", "folglich",
)

#: Wörter, die auf einen Beleg deuten.
_EVIDENCE_MARKERS: tuple[str, ...] = (
    "quelle", "laut", "zufolge", "schreibt", "berichtet", "zitiert",
    "belegt", "urkunde", "brief", "chronik", "protokoll", "akte",
    "überliefert", "ueberliefert", "vgl.", "ebd.", "s.",
)

#: Wörter, die eine These anzeigen.
_CLAIM_MARKERS: tuple[str, ...] = (
    "these", "ich behaupte", "meiner ansicht", "ich argumentiere",
    "es lässt sich zeigen", "es laesst sich zeigen", "war entscheidend",
    "war die ursache", "ist zu erklären", "ist zu erklaeren",
)

#: Wörter, die eine Gegenposition anzeigen.
_COUNTER_MARKERS: tuple[str, ...] = (
    "dagegen", "einwenden", "gegenposition", "kritiker", "allerdings",
    "andererseits", "hingegen", "demgegenüber", "demgegenueber",
    "widerspricht", "gegenargument", "zwar",
)

#: Wörter, die einen Schluss anzeigen.
_CONCLUSION_MARKERS: tuple[str, ...] = (
    "insgesamt", "zusammenfassend", "es zeigt sich", "daraus folgt",
    "im ergebnis", "abschließend", "abschliessend", "somit lässt sich",
)

#: Eine bloße Zeitfolge, die gern für eine Ursache gehalten wird.
_SEQUENCE_PATTERN = re.compile(
    r"\b(danach|anschließend|anschliessend|kurz darauf|daraufhin|"
    r"in der folgezeit|später|spaeter)\b.{0,80}?\b(führte|fuehrte|verursachte|"
    r"bewirkte|löste aus|loeste aus)\b",
    re.IGNORECASE | re.DOTALL,
)


def _contains(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _excerpt(text: str, needle: str, width: int = 70) -> str:
    """Schneidet die Fundstelle mit etwas Umgebung heraus."""

    lowered = text.lower()
    position = lowered.find(needle.lower())
    if position < 0:
        return needle

    start = max(0, position - width // 2)
    end = min(len(text), position + len(needle) + width // 2)
    fragment = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + fragment + ("…" if end < len(text) else "")


def check_anachronisms(text: str) -> list[Finding]:
    """Sucht moderne Begriffe in Aussagen über ältere Epochen (Abschnitt 9).

    Gemeldet wird nur, wenn zugleich eine frühere Epoche im Spiel ist. Wer
    über das 20. Jahrhundert schreibt, darf „Propaganda“ sagen, ohne dass
    ihm jemand dazwischenredet.
    """

    lowered = text.lower()
    if not any(marker in lowered for marker in _EARLY_PERIOD_MARKERS):
        return []

    findings: list[Finding] = []
    for term, note in ANACHRONISTIC_TERMS.items():
        if term not in lowered:
            continue
        findings.append(
            Finding(
                kind="begrifflicher_fehler",
                excerpt=_excerpt(text, term),
                explanation=(
                    f"„{term}“ ist ein moderner Begriff. {note} Ihn auf diese "
                    "Epoche anzuwenden, kann sinnvoll sein – aber es muss "
                    "begründet werden."
                ),
                question=(
                    f"Hätten die Zeitgenossen verstanden, was du mit "
                    f"„{term}“ meinst? Und wenn nicht: Was setzt du damit "
                    "stillschweigend voraus?"
                ),
            )
        )

    return findings


def analyse_argument(text: str) -> ArgumentStructure:
    """Zerlegt einen Text in die Bestandteile einer Argumentation.

    Die Erkennung geht über Signalwörter und ist damit grob. Sie ersetzt
    kein Urteil – sie liefert dem Professor Anhaltspunkte, wo er
    nachhaken kann, und sie tut das gleichbleibend.
    """

    structure = ArgumentStructure(
        has_claim=_contains(text, _CLAIM_MARKERS),
        has_reason=_contains(text, _CAUSAL_MARKERS),
        has_evidence=_contains(text, _EVIDENCE_MARKERS),
        has_conclusion=_contains(text, _CONCLUSION_MARKERS),
        has_counterargument=_contains(text, _COUNTER_MARKERS),
    )

    # Eine Kausalbehauptung ohne jeden Beleg ist der häufigste Mangel
    # überhaupt – und der, den man am leichtesten übersieht, weil der Satz
    # gut klingt.
    if structure.has_reason and not structure.has_evidence:
        marker = next(
            (word for word in _CAUSAL_MARKERS if word in text.lower()), "weil"
        )
        structure.findings.append(
            Finding(
                kind="argumentationsfehler",
                excerpt=_excerpt(text, marker),
                explanation=(
                    "Hier steht eine Kausalbehauptung, aber keine Quelle, die "
                    "sie stützt. Der Satz ist damit plausibel, nicht belegt."
                ),
                question="Welche Quelle stützt diese Aussage?",
            )
        )

    # Zeitfolge als Ursache.
    match = _SEQUENCE_PATTERN.search(text)
    if match:
        structure.findings.append(
            Finding(
                kind="kausalfehler",
                excerpt=match.group(0)[:110].replace("\n", " "),
                explanation=(
                    "Hier wird aus einer zeitlichen Abfolge eine Verursachung. "
                    "Dass etwas danach geschah, heißt nicht, dass es deswegen "
                    "geschah."
                ),
                question="Ist das eine Ursache oder nur etwas, das zeitlich "
                         "darauf folgte?",
            )
        )

    structure.findings.extend(check_anachronisms(text))
    return structure


def feedback_prompt(structure: ArgumentStructure, *, is_written_work: bool = False) -> str:
    """Erzeugt die Anweisung für das akademische Feedback (Abschnitt 17).

    Die Vorgabe verlangt dreierlei: Was ist das Problem, warum ist es
    problematisch, wie lässt es sich verbessern. Genau das steht hier – und
    zwar begrenzt auf einen Punkt. Fünf Kritikpunkte auf einmal führen
    dazu, dass keiner bearbeitet wird.
    """

    lines: list[str] = []

    if structure.findings:
        lines.append("Die formale Prüfung hat ergeben:")
        for finding in structure.findings[:4]:
            lines.append(
                f"  - {ERROR_KINDS.get(finding.kind, finding.kind)} "
                f"bei: „{finding.excerpt}“ – {finding.explanation}"
            )

    if structure.missing:
        lines.append("Es fehlt: " + ", ".join(structure.missing) + ".")

    if not lines:
        return (
            "Die Argumentation ist formal vollständig. Prüfe jetzt inhaltlich: "
            "Trägt der Beleg wirklich die These? Ist die Gegenposition ernsthaft "
            "behandelt oder nur erwähnt?"
        )

    umfang = (
        "Du betreust hier eine schriftliche Arbeit. Sei genau und benenne die "
        "Stelle."
        if is_written_work
        else "Es geht um eine mündliche Äußerung. Bleib knapp."
    )

    return (
        "\n".join(lines)
        + "\n\n"
        + umfang
        + " Sprich GENAU EINEN Punkt an – den wichtigsten. Sage in dieser "
        "Reihenfolge: was das Problem ist, warum es zählt, und was zu tun "
        "wäre. Schließe mit einer Frage, die den Benutzer die Verbesserung "
        "selbst finden lässt. Sei klar, aber nie herablassend."
    )
