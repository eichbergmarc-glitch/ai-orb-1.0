"""Quellenkritik (Abschnitte 10, 11).

Die W-Fragen der Quellenkritik sind seit Generationen dieselben, und genau
darin liegt ihr Wert: Sie sind ein Raster, das man abarbeiten kann, ohne
etwas zu vergessen. Ein Sprachmodell, das frei über eine Quelle spricht,
trifft die meisten davon – aber eben nicht alle, und nie zuverlässig
dieselben. Ein Raster vergisst nicht.

Der Professor arbeitet es deshalb Schritt für Schritt ab, gemeinsam mit
dem Benutzer. Er beantwortet die Fragen nicht selbst; das wäre eine
Vorführung und keine Übung.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Die Leitfragen, in der Reihenfolge, in der sie sinnvoll sind.
#:
#: Erst das Äußere (wer, wann, wo), dann das Absichtsvolle (für wen,
#: warum), dann das Deutende. Wer mit der Deutung beginnt, deutet in die
#: Quelle hinein, was er erwartet.
CRITICISM_STEPS: tuple[tuple[str, str, str], ...] = (
    ("wer", "Wer hat die Quelle verfasst?",
     "Stellung, Herkunft und Bildung des Verfassers bestimmen mit, was er "
     "überhaupt sehen und sagen konnte."),
    ("wann", "Wann ist sie entstanden?",
     "Vor, während oder nach dem Ereignis – das entscheidet über den Abstand "
     "und über die Möglichkeit nachträglicher Deutung."),
    ("wo", "Wo ist sie entstanden?",
     "Der Ort bestimmt den Kenntnisstand und oft auch die Zensurlage."),
    ("fuer_wen", "An wen richtet sie sich?",
     "Ein Brief an einen Vertrauten sagt anderes als eine Denkschrift an "
     "einen Fürsten. Die Adressatenfrage wird am häufigsten übergangen."),
    ("warum", "Zu welchem Zweck wurde sie verfasst?",
     "Rechenschaft, Rechtfertigung, Werbung, Anklage, Verwaltung – die "
     "Absicht formt den Inhalt."),
    ("kontext", "In welchem Zusammenhang steht sie?",
     "Was geschah gleichzeitig? Worauf antwortet die Quelle?"),
    ("interessen", "Welche Interessen verfolgt der Verfasser?",
     "Interessen müssen nicht unehrlich machen. Sie müssen bekannt sein."),
    ("perspektive", "Aus welcher Perspektive ist geschrieben?",
     "Wer spricht, und wessen Sicht kommt nicht vor?"),
    ("begriffe", "Welche Begriffe verwendet sie?",
     "Zeitgenössische Begriffe bedeuten oft etwas anderes als heute."),
    ("auslassungen", "Was fehlt?",
     "Was man erwarten würde und nicht findet, ist ein Befund."),
    ("aussagekraft", "Was kann sie belegen?",
     "Eine Quelle belegt zuverlässig, was sie unabsichtlich mitteilt."),
    ("grenzen", "Wo endet ihre Aussagekraft?",
     "Die Grenze zu benennen ist Teil der Analyse, nicht ihr Scheitern."),
)

#: Die vier Ebenen, die auseinanderzuhalten sind (Abschnitt 10).
LEVELS: dict[str, str] = {
    "inhalt": "Was steht da? Zunächst nur wiedergeben, noch nicht deuten.",
    "intention": "Was will der Verfasser damit erreichen?",
    "kontext": "In welche Lage gehört die Quelle?",
    "interpretation": "Was folgt daraus für deine Fragestellung?",
}

#: Quellengattungen und was bei ihnen besonders zu beachten ist.
SOURCE_TYPES: dict[str, str] = {
    "primaerquelle": "Aus der untersuchten Zeit selbst. Nähe ist ein Vorzug "
                     "und eine Gefahr zugleich – Beteiligte sind selten unbeteiligt.",
    "sekundaerquelle": "Spätere Darstellung. Sie ist Forschung, nicht Beleg, und "
                       "hat selbst eine Fragestellung.",
    "edition": "Bearbeitete Quelle. Die Bearbeitung ist eine Entscheidung, "
               "die man kennen sollte.",
    "uebersetzung": "Jede Übersetzung ist bereits eine Deutung.",
}


@dataclass(slots=True)
class SourceAnalysis:
    """Eine laufende Quellenanalyse."""

    description: str
    answers: dict[str, str] = field(default_factory=dict)

    @property
    def next_step(self) -> tuple[str, str, str] | None:
        """Der nächste offene Schritt."""

        for key, question, why in CRITICISM_STEPS:
            if not self.answers.get(key, "").strip():
                return key, question, why
        return None

    @property
    def progress(self) -> float:
        answered = sum(1 for key, _, _ in CRITICISM_STEPS if self.answers.get(key, "").strip())
        return round(answered / len(CRITICISM_STEPS), 2)

    @property
    def skipped(self) -> list[str]:
        """Schritte, die übersprungen wurden, obwohl spätere beantwortet sind."""

        keys = [key for key, _, _ in CRITICISM_STEPS]
        answered = [key for key in keys if self.answers.get(key, "").strip()]
        if not answered:
            return []
        last = keys.index(answered[-1])
        return [key for key in keys[:last] if not self.answers.get(key, "").strip()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "quelle": self.description,
            "fortschritt": self.progress,
            "beantwortet": {k: v for k, v in self.answers.items() if v.strip()},
            "uebersprungen": self.skipped,
        }


def prompt_for(analysis: SourceAnalysis) -> str:
    """Die Anweisung für den nächsten Schritt der Analyse."""

    step = analysis.next_step

    if step is None:
        return (
            "Alle Leitfragen sind beantwortet. Fasse jetzt zusammen, was die "
            "Quelle für die Fragestellung leisten kann UND wo ihre Grenze "
            "liegt. Die Grenze zu benennen gehört dazu."
        )

    key, question, why = step
    hinweis = ""
    if analysis.skipped:
        hinweis = (
            f"\nÜbergangen wurden bisher: {', '.join(analysis.skipped)}. "
            "Komm darauf zurück, wenn es passt."
        )

    return (
        f"QUELLENKRITIK – nächster Schritt: {question}\n"
        f"Warum das zählt: {why}\n"
        "Stelle diese Frage dem Benutzer. Beantworte sie NICHT selbst. "
        "Wenn er schon etwas dazu gesagt hat, greif es auf und hak nach."
        + hinweis
    )
