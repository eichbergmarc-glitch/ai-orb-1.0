"""Die adaptive Prüfungssimulation (Abschnitte 18, 19, 20, 21).

Eine mündliche Prüfung ist etwas anderes als eine Reihe von Fragen. Sie
hat einen Verlauf: Der Prüfer stellt eine Frage, hört die Antwort, hakt
nach, vertieft, bringt einen Einwand – und richtet die nächste Frage
danach aus, wie die letzte ausgefallen ist.

Genau dieser Verlauf wird hier abgebildet, und zwar als Zustandsautomat
und nicht als Anweisung an ein Sprachmodell. Der Grund ist derselbe wie
beim sokratischen Modus: Ein Modell, das gebeten wird, „eine Prüfung zu
simulieren“, verfällt nach drei Zügen darauf, die Antworten gleich
mitzuliefern. Ein Automat vergisst nicht, in welchem Schritt er ist.

## Zur Bewertung

Bewertet wird in den Kompetenzbereichen des Lernprofils, nicht als eine
Note. Eine Zahl am Ende wäre einprägsam und nutzlos: Sie sagt nicht, was
zu tun ist. Sieben Werte sagen es.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.agents.history_agent.learning_profile import (
    COMPETENCE_LABELS,
    LearningProfile,
)
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


#: Der Ablauf eines Prüfungszugs (Abschnitt 18).
PHASES: tuple[str, ...] = (
    "frage",        # Die Ausgangsfrage
    "nachfrage",    # Nachhaken an einer Stelle der Antwort
    "vertiefung",   # Tiefer in denselben Gegenstand
    "gegenargument",  # Einwand, der verteidigt werden muss
)

#: Wie viele Züge eine Prüfung mindestens und höchstens hat.
MIN_TURNS = 4
MAX_TURNS = 14

#: Bereiche, die in einer Prüfung bewertet werden.
EXAM_COMPETENCES: tuple[str, ...] = (
    "faktenwissen",
    "chronologie",
    "kausalitaet",
    "quellenkritik",
    "argumentation",
    "kontextualisierung",
    "multiperspektivitaet",
)


@dataclass(slots=True)
class ExamTurn:
    """Ein einzelner Zug der Prüfung."""

    phase: str
    question: str
    answer: str = ""
    #: Bewertung dieses Zuges von 0.0 bis 1.0.
    score: float = 0.0
    competence: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "frage": self.question,
            "antwort": self.answer,
            "bewertung": round(self.score, 2),
            "bereich": self.competence,
            "notiz": self.note,
        }


@dataclass(slots=True)
class ExamSession:
    """Eine laufende Prüfung."""

    topic: str
    turns: list[ExamTurn] = field(default_factory=list)
    #: Schwierigkeit von 0.0 bis 1.0; wandert mit den Antworten.
    difficulty: float = 0.5
    started_at: float = field(default_factory=time.time)
    finished: bool = False

    #: Wie oft hintereinander blockiert wurde. Ab zwei wird geholfen.
    stalls: int = 0

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def current_phase(self) -> str:
        """Die Phase des nächsten Zugs."""

        if not self.turns:
            return "frage"

        last = self.turns[-1]
        index = PHASES.index(last.phase) if last.phase in PHASES else 0

        # Bei einer schwachen Antwort nicht weiter vertiefen, sondern
        # zurück auf eine neue Frage. Wer schon bei der Grundfrage
        # strauchelt, wird durch ein Gegenargument nicht klüger.
        if last.score < 0.35:
            return "frage"

        return PHASES[min(index + 1, len(PHASES) - 1)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "thema": self.topic,
            "zuege": [turn.to_dict() for turn in self.turns],
            "schwierigkeit": round(self.difficulty, 2),
            "beendet": self.finished,
            "dauer_sekunden": round(time.time() - self.started_at),
        }


class ExamEngine:
    """Führt eine adaptive mündliche Prüfung."""

    def __init__(self, profile: LearningProfile) -> None:
        self.profile = profile
        self.session: ExamSession | None = None

    # --- Ablauf ---------------------------------------------------------------

    def start(self, topic: str) -> ExamSession:
        """Beginnt eine Prüfung.

        Die Anfangsschwierigkeit richtet sich nach dem Lernprofil. Wer
        einen Bereich sicher beherrscht, wird nicht mit Grundwissen
        begonnen – das wäre höflich und Zeitverschwendung.
        """

        known = self.profile.topics.get(topic.strip().lower())
        start_difficulty = 0.5 if known is None else max(0.3, min(0.85, known.mastery + 0.15))

        self.session = ExamSession(topic=topic.strip(), difficulty=start_difficulty)
        logger.info(
            "Prüfung begonnen: %s (Anfangsschwierigkeit %.2f).", topic, start_difficulty
        )
        return self.session

    def next_competence(self) -> str:
        """Welcher Bereich als Nächstes drankommt.

        Bevorzugt werden schwache Bereiche – aber nicht ausschließlich.
        Eine Prüfung, die nur die Lücken abfragt, gibt ein falsches Bild
        und ist obendrein entmutigend.
        """

        asked = {turn.competence for turn in (self.session.turns if self.session else [])}
        open_areas = [key for key in EXAM_COMPETENCES if key not in asked]

        if not open_areas:
            open_areas = list(EXAM_COMPETENCES)

        return min(open_areas, key=lambda key: self.profile.competences.get(key, 0.0))

    def record_answer(self, answer: str, score: float, note: str = "") -> ExamTurn:
        """Trägt eine Antwort ein und passt die Schwierigkeit an (Abschnitt 19)."""

        if self.session is None:
            raise RuntimeError("Es läuft keine Prüfung.")

        if not self.session.turns:
            raise RuntimeError("Es wurde noch keine Frage gestellt.")

        turn = self.session.turns[-1]
        turn.answer = answer.strip()
        turn.score = max(0.0, min(1.0, score))
        turn.note = note

        # Schwierigkeit nachführen: gute Antwort hinauf, schwache herunter.
        # Der Ausschlag nach unten ist größer als nach oben – jemanden zu
        # überfordern kostet mehr als ihn zu unterfordern.
        if turn.score >= 0.7:
            self.session.difficulty = min(1.0, self.session.difficulty + 0.12)
            self.session.stalls = 0
        elif turn.score <= 0.35:
            self.session.difficulty = max(0.1, self.session.difficulty - 0.18)
            self.session.stalls += 1
        else:
            self.session.stalls = 0

        if turn.competence:
            self.profile.record_competence(turn.competence, turn.score)

        return turn

    def add_question(self, question: str, competence: str = "") -> ExamTurn:
        """Trägt eine gestellte Frage ein."""

        if self.session is None:
            raise RuntimeError("Es läuft keine Prüfung.")

        turn = ExamTurn(
            phase=self.session.current_phase,
            question=question.strip(),
            competence=competence or self.next_competence(),
        )
        self.session.turns.append(turn)
        return turn

    @property
    def needs_help(self) -> bool:
        """Ob jetzt eine Hilfestellung angebracht ist (Abschnitt 19).

        Nach zwei blockierten Antworten weiter zu prüfen, ist keine
        Prüfung mehr, sondern Vorführung.
        """

        return self.session is not None and self.session.stalls >= 2

    @property
    def should_finish(self) -> bool:
        """Ob die Prüfung zu Ende gehen sollte."""

        if self.session is None:
            return False
        if self.session.turn_count >= MAX_TURNS:
            return True
        # Alle Bereiche behandelt und genug Züge gelaufen.
        covered = {turn.competence for turn in self.session.turns if turn.answer}
        return self.session.turn_count >= MIN_TURNS and len(covered) >= len(EXAM_COMPETENCES)

    # --- Auswertung -----------------------------------------------------------

    def evaluate(self) -> dict[str, Any]:
        """Erzeugt die Auswertung (Abschnitt 20)."""

        if self.session is None:
            return {"fehler": "Es läuft keine Prüfung."}

        self.session.finished = True

        scores: dict[str, float] = {}
        for key in EXAM_COMPETENCES:
            relevant = [
                turn.score
                for turn in self.session.turns
                if turn.competence == key and turn.answer
            ]
            if relevant:
                scores[key] = sum(relevant) / len(relevant)

        if scores:
            self.profile.record_exam(scores, self.session.topic)
            self.profile.save()

        strong = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        weak = [item for item in reversed(strong) if item[1] < 0.6]

        return {
            "thema": self.session.topic,
            "zuege": self.session.turn_count,
            "bewertung": {
                COMPETENCE_LABELS.get(key, key): f"{round(value * 10)}/10"
                for key, value in scores.items()
            },
            "staerken": [COMPETENCE_LABELS.get(key, key) for key, value in strong[:3] if value >= 0.6],
            "schwaechen": [COMPETENCE_LABELS.get(key, key) for key, _ in weak[:3]],
            "wiederkehrende_fehler": [
                record.to_dict() for record in self.profile.recurring_errors()[:3]
            ],
            "durchschnitt": round(sum(scores.values()) / max(1, len(scores)), 2),
        }

    def report_text(self, evaluation: dict[str, Any]) -> str:
        """Die Auswertung als lesbarer Bericht."""

        if "fehler" in evaluation:
            return str(evaluation["fehler"])

        lines = [f"PRÜFUNG: {evaluation['thema']}", ""]

        for label, value in evaluation.get("bewertung", {}).items():
            lines.append(f"  {label:34} {value}")

        lines.append("")

        if evaluation.get("staerken"):
            lines.append("Das sitzt: " + ", ".join(evaluation["staerken"]) + ".")
        if evaluation.get("schwaechen"):
            lines.append("Daran arbeiten: " + ", ".join(evaluation["schwaechen"]) + ".")

        for record in evaluation.get("wiederkehrende_fehler", []):
            lines.append(
                f"Wiederkehrend ({record['anzahl']}×): {record['art']} – "
                f"{record['beschreibung']}"
            )

        return "\n".join(lines)

    def prompt_for_next(self) -> str:
        """Die Anweisung an das Modell für den nächsten Zug."""

        if self.session is None:
            return ""

        if self.needs_help:
            return (
                "Der Prüfling kommt zweimal hintereinander nicht weiter. Gib "
                "jetzt eine echte Hilfestellung: erkläre den Punkt kurz, und "
                "frage danach dasselbe noch einmal in einfacherer Form. Nicht "
                "weiterbohren."
            )

        phase = self.session.current_phase
        competence = self.next_competence()
        niveau = (
            "einfach" if self.session.difficulty < 0.4
            else "mittel" if self.session.difficulty < 0.72
            else "anspruchsvoll"
        )

        anweisung = {
            "frage": "Stelle eine neue Prüfungsfrage.",
            "nachfrage": "Hake an einer konkreten Stelle der letzten Antwort nach.",
            "vertiefung": "Geh beim selben Gegenstand eine Ebene tiefer.",
            "gegenargument": (
                "Bringe einen ernsthaften Einwand gegen das, was der Prüfling "
                "gesagt hat. Er soll ihn entkräften müssen."
            ),
        }[phase]

        return (
            f"PRÜFUNGSMODUS – Thema: {self.session.topic}.\n"
            f"Nächster Schritt: {anweisung}\n"
            f"Bereich: {COMPETENCE_LABELS.get(competence, competence)}. "
            f"Anspruch: {niveau}.\n"
            "Stelle GENAU EINE Frage. Verrate die Antwort nicht, auch nicht "
            "andeutungsweise, und bewerte die vorige Antwort nicht ausführlich – "
            "die Auswertung kommt am Ende."
        )
