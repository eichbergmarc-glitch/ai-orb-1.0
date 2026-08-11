"""Historiographie und Forschungskontroversen (Abschnitte 12, 28).

Ein Studierender, der Geschichte für eine Sammlung feststehender Tatsachen
hält, wird bei der ersten widersprüchlichen Literaturangabe irre. Deshalb
gehört zur Ausbildung, dass Geschichte eine Wissenschaft mit Streit ist –
und dass der Streit meistens nicht an den Fakten hängt, sondern an
Fragestellung und Methode.

Dieses Modul hält die Ansätze und die Struktur einer Kontroverse bereit.
Konkrete Positionen zu einzelnen Debatten stehen bewusst NICHT hier: Sie
wären eine unvollständige Liste, die schnell veraltet, und der Professor
soll sie mit dem Benutzer erarbeiten, nicht abrufen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Forschungsrichtungen und ihre Leitfrage.
#:
#: Die Leitfrage ist wichtiger als der Name: Sie erklärt, warum zwei
#: Historiker mit denselben Quellen zu verschiedenen Ergebnissen kommen.
APPROACHES: dict[str, str] = {
    "politische Geschichte": "Wer entscheidet, und wie kommt Herrschaft zustande?",
    "Sozialgeschichte": "Wie sind Gesellschaften gegliedert, und wie verändert "
                        "sich das?",
    "Alltagsgeschichte": "Wie lebten die Menschen, über die sonst nicht "
                         "geschrieben wird?",
    "Kulturgeschichte": "Welche Bedeutungen gaben Zeitgenossen ihrer Welt?",
    "Gendergeschichte": "Wie wurden Geschlechterverhältnisse hergestellt und "
                        "begründet?",
    "Globalgeschichte": "Welche Verflechtungen reichen über die Nation hinaus?",
    "Mikrogeschichte": "Was zeigt der Einzelfall, was die Übersicht verdeckt?",
    "Wirtschaftsgeschichte": "Wie wurde produziert, getauscht und verteilt?",
    "Begriffsgeschichte": "Was bedeuteten die Wörter, mit denen die Quellen "
                          "arbeiten?",
    "Umweltgeschichte": "Wie wirkten natürliche Bedingungen und menschliches "
                        "Handeln aufeinander?",
}

#: Die Kennzeichnung der Sicherheit einer Aussage (Abschnitt 27).
#:
#: Diese vier Stufen sind der Kern wissenschaftlicher Redlichkeit im
#: Gespräch. Ein Professor, der Vermutung und Befund gleich klingen lässt,
#: erzieht zu schlechter Arbeit.
CERTAINTY: dict[str, str] = {
    "gesichert": "Durch Quellen breit belegt und in der Forschung unstrittig.",
    "wahrscheinlich": "Gut begründet, aber nicht abschließend gesichert.",
    "umstritten": "Die Forschung ist geteilt; es gibt vertretbare Gegenpositionen.",
    "unsicher": "Die Quellenlage trägt keine feste Aussage.",
}


@dataclass(slots=True)
class Position:
    """Eine Position in einer Forschungskontroverse."""

    label: str
    claim: str
    arguments: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "bezeichnung": self.label,
            "these": self.claim,
            "argumente": self.arguments,
            "quellenbasis": self.sources,
            "methode": self.method,
        }


@dataclass(slots=True)
class Controversy:
    """Eine Forschungskontroverse mit mindestens zwei Positionen."""

    topic: str
    positions: list[Position] = field(default_factory=list)
    core_of_dispute: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "thema": self.topic,
            "streitpunkt": self.core_of_dispute,
            "positionen": [position.to_dict() for position in self.positions],
        }

    def as_text(self) -> str:
        lines = [f"KONTROVERSE: {self.topic}"]
        if self.core_of_dispute:
            lines += ["", f"Worin der Streit besteht: {self.core_of_dispute}"]

        for position in self.positions:
            lines += ["", f"{position.label}", f"  These: {position.claim}"]
            for argument in position.arguments:
                lines.append(f"  - {argument}")
            if position.sources:
                lines.append(f"  Quellen: {', '.join(position.sources)}")
            if position.method:
                lines.append(f"  Methode: {position.method}")

        return "\n".join(lines)


def controversy_prompt(topic: str) -> str:
    """Die Anweisung, eine Kontroverse darzustellen."""

    return (
        f"Stelle die Forschungskontroverse zu „{topic}“ dar.\n\n"
        "Halte dich an diesen Aufbau: erst worin der Streit besteht (Quellen? "
        "Methoden? Fragestellung?), dann je Position die These, ihre "
        "Argumente und ihre Quellenbasis.\n\n"
        "Zwei Regeln, die nicht verhandelbar sind:\n"
        "  1. Erfinde keine Namen, Titel, Jahreszahlen oder Seitenzahlen. "
        "Wenn du eine Position kennst, aber nicht die genaue Fundstelle, "
        "sage das.\n"
        "  2. Kennzeichne jede Aussage als gesichert, wahrscheinlich, "
        "umstritten oder unsicher.\n\n"
        "Schließe damit, dass du den Benutzer fragst, welche Position er für "
        "stärker hält – und warum. Er soll sich positionieren, nicht du."
    )


def approach_prompt(question: str) -> str:
    """Zeigt, wie die Fragestellung das Ergebnis mitbestimmt."""

    liste = "\n".join(f"  - {name}: {frage}" for name, frage in APPROACHES.items())
    return (
        f"Der Benutzer fragt: „{question}“\n\n"
        "Zeige an zwei oder drei dieser Zugänge, wie sich die Antwort ändert, "
        "je nachdem, welche Frage man stellt:\n"
        f"{liste}\n\n"
        "Es geht nicht darum, alle aufzuzählen. Es geht darum, dass der "
        "Benutzer versteht: Die Methode entscheidet mit, was man findet."
    )
