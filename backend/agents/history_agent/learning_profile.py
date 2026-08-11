"""Das langfristige Lernprofil (Abschnitte 22, 23, 30).

Dies ist das Fundament der Professor-Engine. Ohne es wäre der Professor ein
Chatbot mit akademischem Tonfall: Er könnte gut klingen, aber er wüsste
beim zweiten Gespräch nicht mehr, dass beim ersten die Unterscheidung von
Ursache und Auslöser Mühe gemacht hat.

Genau darin liegt der Unterschied zwischen einer Antwortmaschine und einem
Mentor. Ein Mentor erinnert sich – und zwar nicht an das Gespräch, sondern
an den Menschen: woran er arbeitet, was ihm liegt, welcher Fehler
wiederkehrt, was zuletzt gut lief.

## Was hier gespeichert wird und was nicht

Gespeichert wird, was für die Betreuung gebraucht wird: Kompetenzstände je
Bereich, wiederkehrende Fehler, bearbeitete Themen,
Forschungsinteressen. Nicht gespeichert werden Gesprächsverläufe – dafür
gibt es das allgemeine Gedächtnis.

Das Profil gehört dem Benutzer. Es liegt im Klartext als JSON in seinen
Daten, er kann es lesen, ändern und löschen. Ein Lernprofil, das man nicht
einsehen kann, ist eine Akte.

## Zur Bewertung

Die Kompetenzstände sind gleitende Mittelwerte mit Gewicht auf dem Neuen.
Wer eine Sache dreimal falsch und dann zweimal richtig gemacht hat, hat sie
gerade gelernt – ein einfacher Durchschnitt würde das verschleiern und ihn
noch monatelang für schwach in diesem Bereich halten.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)


#: Die Bereiche historischen Denkens, in denen bewertet wird (Abschnitt 6).
#:
#: Bewusst nicht „Geschichte" als eine Zahl. Wer Chronologie sicher
#: beherrscht und bei Kausalität strauchelt, braucht ein anderes Training
#: als umgekehrt – eine Gesamtnote verwischt genau diesen Unterschied.
COMPETENCES: tuple[tuple[str, str], ...] = (
    ("faktenwissen", "Historisches Faktenwissen"),
    ("chronologie", "Chronologie"),
    ("kausalitaet", "Kausalität"),
    ("kontingenz", "Kontingenz und Alternativen"),
    ("wandel", "Wandel und Kontinuität"),
    ("akteure", "Akteursanalyse"),
    ("struktur", "Struktur und Handlung"),
    ("kontextualisierung", "Kontextualisierung"),
    ("multiperspektivitaet", "Multiperspektivität"),
    ("vergleich", "Vergleich"),
    ("quellenkritik", "Quellenkritik"),
    ("argumentation", "Historische Argumentation"),
    ("historiographie", "Historiographie und Forschungsstand"),
    ("methodik", "Methodisches Denken"),
)

#: Nachschlagewerk für die Klarnamen.
COMPETENCE_LABELS: dict[str, str] = dict(COMPETENCES)

#: Die Niveaustufen (Abschnitt 5).
LEVELS: tuple[str, ...] = (
    "einsteiger",
    "grundwissen",
    "zusammenhaenge",
    "analyse",
    "quellenkritik",
    "argumentation",
    "forschungsstand",
    "wissenschaftliche_diskussion",
)

#: Wie stark ein neues Ergebnis den bisherigen Stand verschiebt.
#:
#: 0.34 heißt: Nach drei gleichgerichteten Ergebnissen ist der alte Stand
#: zu etwa neun Zehnteln überschrieben. Schnell genug, um Fortschritt
#: abzubilden, langsam genug, dass ein einzelner schlechter Tag nicht das
#: ganze Bild kippt.
LEARNING_RATE = 0.34

#: Abstände der Wiederholung in Tagen, nach Beherrschungsgrad (Abschnitt 23).
#:
#: Angelehnt an SM-2, aber gröber: Ein Mentor plant nicht auf die Stunde.
REVIEW_INTERVALS: tuple[float, ...] = (1.0, 3.0, 7.0, 16.0, 35.0, 90.0)


@dataclass(slots=True)
class ErrorRecord:
    """Ein wiederkehrender Fehler."""

    kind: str
    topic: str
    description: str
    count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    @property
    def is_recurring(self) -> bool:
        """Ab dem dritten Mal ist es kein Ausrutscher mehr."""

        return self.count >= 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "art": self.kind,
            "thema": self.topic,
            "beschreibung": self.description,
            "anzahl": self.count,
            "zuerst": self.first_seen,
            "zuletzt": self.last_seen,
            "wiederkehrend": self.is_recurring,
        }


@dataclass(slots=True)
class TopicRecord:
    """Ein bearbeitetes Thema."""

    name: str
    encounters: int = 0
    #: Beherrschung von 0.0 bis 1.0.
    mastery: float = 0.0
    last_seen: float = field(default_factory=time.time)
    #: Wann es sinnvollerweise wieder drankommt.
    due_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thema": self.name,
            "begegnungen": self.encounters,
            "beherrschung": round(self.mastery, 3),
            "zuletzt": self.last_seen,
            "faellig": self.due_at,
        }


class LearningProfile:
    """Das Lernprofil eines Benutzers.

    Wird beim Start geladen und nach jeder Änderung geschrieben. Das
    kostet wenig und erspart die Frage, was bei einem Absturz verloren
    geht.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_data_dir() / "professor" / "lernprofil.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.competences: dict[str, float] = {key: 0.0 for key, _ in COMPETENCES}
        self.topics: dict[str, TopicRecord] = {}
        self.errors: dict[str, ErrorRecord] = {}
        self.interests: list[str] = []
        self.preferred_methods: list[str] = []
        self.created_at: float = time.time()

        self._load()

    # --- Laden und Sichern ----------------------------------------------------

    def _load(self) -> None:
        if not self.path.is_file():
            return

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Lernprofil nicht lesbar (%s) – es wird neu angelegt.", error)
            return

        self.competences.update(
            {
                key: float(value)
                for key, value in (raw.get("kompetenzen") or {}).items()
                if key in self.competences
            }
        )
        self.created_at = float(raw.get("angelegt", self.created_at))
        self.interests = [str(item) for item in (raw.get("interessen") or [])]
        self.preferred_methods = [str(item) for item in (raw.get("methoden") or [])]

        for entry in raw.get("themen") or []:
            name = str(entry.get("thema", "")).strip()
            if name:
                self.topics[name.lower()] = TopicRecord(
                    name=name,
                    encounters=int(entry.get("begegnungen", 0)),
                    mastery=float(entry.get("beherrschung", 0.0)),
                    last_seen=float(entry.get("zuletzt", time.time())),
                    due_at=float(entry.get("faellig", time.time())),
                )

        for entry in raw.get("fehler") or []:
            key = f"{entry.get('art','')}|{entry.get('thema','')}".lower()
            self.errors[key] = ErrorRecord(
                kind=str(entry.get("art", "")),
                topic=str(entry.get("thema", "")),
                description=str(entry.get("beschreibung", "")),
                count=int(entry.get("anzahl", 1)),
                first_seen=float(entry.get("zuerst", time.time())),
                last_seen=float(entry.get("zuletzt", time.time())),
            )

        logger.info(
            "Lernprofil geladen: %d Themen, %d Fehlerarten.",
            len(self.topics),
            len(self.errors),
        )

    def save(self) -> bool:
        """Schreibt das Profil. Gibt zurück, ob es geklappt hat."""

        payload = {
            "angelegt": self.created_at,
            "geaendert": time.time(),
            "kompetenzen": {key: round(value, 4) for key, value in self.competences.items()},
            "themen": [record.to_dict() for record in self.topics.values()],
            "fehler": [record.to_dict() for record in self.errors.values()],
            "interessen": self.interests,
            "methoden": self.preferred_methods,
        }

        try:
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except OSError as error:
            logger.error("Lernprofil nicht speicherbar: %s", error)
            return False

    # --- Fortschreiben --------------------------------------------------------

    def record_competence(self, key: str, score: float) -> float:
        """Trägt ein Ergebnis in einem Kompetenzbereich ein.

        Args:
            key: Bereich aus :data:`COMPETENCES`.
            score: 0.0 bis 1.0.

        Returns:
            Der neue Stand.
        """

        if key not in self.competences:
            logger.debug("Unbekannter Kompetenzbereich: %s", key)
            return 0.0

        score = max(0.0, min(1.0, score))
        current = self.competences[key]
        self.competences[key] = current + (score - current) * LEARNING_RATE
        return self.competences[key]

    def record_topic(self, name: str, mastery: float) -> TopicRecord:
        """Trägt die Beschäftigung mit einem Thema ein und plant die Wiederholung."""

        clean = name.strip()
        key = clean.lower()
        record = self.topics.get(key) or TopicRecord(name=clean)

        record.encounters += 1
        record.mastery = record.mastery + (max(0.0, min(1.0, mastery)) - record.mastery) * LEARNING_RATE
        record.last_seen = time.time()

        # Der Abstand wächst mit der Beherrschung. Wer etwas sicher kann,
        # soll nicht jede Woche daran erinnert werden – das ermüdet und
        # erzeugt den Eindruck, der Professor höre nicht zu.
        step = min(len(REVIEW_INTERVALS) - 1, int(record.mastery * len(REVIEW_INTERVALS)))
        record.due_at = time.time() + REVIEW_INTERVALS[step] * 86400.0

        self.topics[key] = record
        return record

    def record_error(self, kind: str, topic: str, description: str) -> ErrorRecord:
        """Trägt einen Fehler ein.

        Gezählt wird nach Art *und* Thema. Derselbe Denkfehler in zwei
        Epochen ist zweimal derselbe Fehler – und genau das ist die
        Beobachtung, die einen Mentor interessiert.
        """

        key = f"{kind}|{topic}".lower()
        record = self.errors.get(key)

        if record is None:
            record = ErrorRecord(kind=kind, topic=topic, description=description)
        else:
            record.count += 1
            record.last_seen = time.time()
            record.description = description or record.description

        self.errors[key] = record
        return record

    @property
    def level(self) -> str:
        """Das aktuelle Gesamtniveau (Abschnitt 5).

        Abgeleitet aus dem Mittel der Kompetenzen, aber gedämpft durch das
        schwächste Drittel: Wer in vier Bereichen glänzt und in vier
        versagt, ist kein fortgeschrittener Historiker, sondern jemand mit
        Lücken – und diese Lücken bestimmen, was er als Nächstes braucht.
        """

        values = sorted(self.competences.values())
        if not values:
            return LEVELS[0]

        weakest_third = values[: max(1, len(values) // 3)]
        blended = (sum(values) / len(values)) * 0.6 + (
            sum(weakest_third) / len(weakest_third)
        ) * 0.4

        index = min(len(LEVELS) - 1, int(blended * len(LEVELS)))
        return LEVELS[index]

    def strengths(self, limit: int = 3) -> list[tuple[str, float]]:
        """Die stärksten Bereiche – nur solche, die wirklich sitzen."""

        ranked = sorted(self.competences.items(), key=lambda item: item[1], reverse=True)
        return [(key, value) for key, value in ranked if value >= 0.6][:limit]

    def weaknesses(self, limit: int = 3) -> list[tuple[str, float]]:
        """Die schwächsten Bereiche, in denen schon gearbeitet wurde.

        Bereiche mit Stand 0.0 werden übergangen: Sie sind nicht schwach,
        sie kamen nur noch nicht vor. Sie als Schwäche zu melden, wäre ein
        Vorwurf für etwas, das nie verlangt wurde.
        """

        touched = [
            (key, value)
            for key, value in self.competences.items()
            if value > 0.0 and value < 0.55
        ]
        return sorted(touched, key=lambda item: item[1])[:limit]

    def recurring_errors(self) -> list[ErrorRecord]:
        """Fehler, die mindestens dreimal vorkamen."""

        return sorted(
            (record for record in self.errors.values() if record.is_recurring),
            key=lambda record: record.count,
            reverse=True,
        )

    def due_topics(self, *, now: float | None = None, limit: int = 5) -> list[TopicRecord]:
        """Themen, die zur Wiederholung anstehen (Abschnitt 23)."""

        moment = now if now is not None else time.time()
        due = [record for record in self.topics.values() if record.due_at <= moment]
        return sorted(due, key=lambda record: record.mastery)[:limit]

    def is_new(self) -> bool:
        """Ob noch praktisch nichts bekannt ist.

        Wichtig für den ersten Eindruck: Ein Professor, der beim ersten
        Gespräch auf ein Lernprofil verweist, wirkt nicht aufmerksam,
        sondern unheimlich.
        """

        return not self.topics and all(
            math.isclose(value, 0.0) for value in self.competences.values()
        )

    # --- Darstellung ----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Das Profil in Kürze – für die Anzeige und für den Systemprompt."""

        return {
            "niveau": self.level,
            "themen": len(self.topics),
            "staerken": [
                {"bereich": COMPETENCE_LABELS.get(key, key), "stand": round(value, 2)}
                for key, value in self.strengths()
            ],
            "schwaechen": [
                {"bereich": COMPETENCE_LABELS.get(key, key), "stand": round(value, 2)}
                for key, value in self.weaknesses()
            ],
            "wiederkehrende_fehler": [
                record.to_dict() for record in self.recurring_errors()[:5]
            ],
            "faellige_themen": [record.name for record in self.due_topics()],
            "interessen": self.interests,
        }

    def as_context(self) -> str:
        """Das Profil als Text für den Systemprompt des Professors.

        Bewusst knapp. Ein Modell, das drei Absätze Vorgeschichte liest,
        bevor es die Frage sieht, antwortet auf die Vorgeschichte.
        """

        if self.is_new():
            return (
                "Zu diesem Benutzer liegt noch kein Lernprofil vor. Das ist das "
                "erste Gespräch – frage nicht nach Vorwissen, sondern finde es "
                "im Gespräch heraus."
            )

        parts = [f"Niveau: {self.level}."]

        strong = self.strengths()
        if strong:
            parts.append(
                "Sicher in: "
                + ", ".join(COMPETENCE_LABELS.get(key, key) for key, _ in strong)
                + "."
            )

        weak = self.weaknesses()
        if weak:
            parts.append(
                "Schwierigkeiten mit: "
                + ", ".join(COMPETENCE_LABELS.get(key, key) for key, _ in weak)
                + "."
            )

        recurring = self.recurring_errors()[:2]
        if recurring:
            parts.append(
                "Wiederkehrende Fehler: "
                + "; ".join(f"{record.kind} ({record.topic})" for record in recurring)
                + "."
            )

        due = self.due_topics(limit=3)
        if due:
            parts.append(
                "Zur Wiederholung fällig: " + ", ".join(record.name for record in due) + "."
            )

        return " ".join(parts)
