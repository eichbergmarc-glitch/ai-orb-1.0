"""Lernpläne und Lernfortschritt (Phase 18).

Ordnet Themen einem Termin zu und verteilt sie über die verbleibende Zeit.
Der Nutzen liegt weniger im Plan selbst als in dem, was er sichtbar macht:
ob die Zeit reicht, und was zuerst drankommen muss.

Zwei Regeln prägen die Verteilung:

**Schwieriges früh.** Was am wenigsten sitzt, kommt zuerst – dann bleibt Zeit
für Wiederholung. Die umgekehrte Reihenfolge fühlt sich besser an und geht
regelmäßig schief.

**Der letzte Tag bleibt frei.** Er ist für Wiederholung reserviert, nicht für
neuen Stoff. Wer am Vorabend noch ein Kapitel anfängt, kann es zur Prüfung
nicht.

Der Fortschritt wird nicht geschätzt, sondern gezählt: Ein Thema gilt als
beherrscht, wenn die zugehörigen Karteikarten sitzen. Damit steht hinter der
Prozentzahl etwas Nachprüfbares.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

DAY = 86400.0


@dataclass
class Topic:
    """Ein Thema innerhalb eines Lernplans."""

    topic_id: str
    title: str
    #: Wie schwer, von 1 (leicht) bis 5 (schwer). Steuert die Reihenfolge.
    difficulty: int = 3
    #: Geschätzter Aufwand in Stunden.
    hours: float = 2.0
    #: Zugehöriger Karteikartenstapel.
    deck: str = ""
    notes: str = ""
    done: bool = False
    #: Selbsteinschätzung von 0.0 bis 1.0.
    confidence: float = 0.0
    scheduled_for: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "title": self.title,
            "difficulty": self.difficulty,
            "hours": self.hours,
            "deck": self.deck,
            "notes": self.notes,
            "done": self.done,
            "confidence": round(self.confidence, 2),
            "scheduled_for": self.scheduled_for,
            "scheduled_date": (
                datetime.fromtimestamp(self.scheduled_for).strftime("%d.%m.%Y")
                if self.scheduled_for
                else ""
            ),
        }


@dataclass
class StudyPlan:
    """Ein Lernplan bis zu einem Termin."""

    plan_id: str
    title: str
    #: Wann die Prüfung ist.
    exam_at: float
    #: Wie viele Stunden am Tag zur Verfügung stehen.
    hours_per_day: float = 3.0
    topics: list[Topic] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "exam_at": self.exam_at,
            "exam_date": datetime.fromtimestamp(self.exam_at).strftime("%d.%m.%Y"),
            "days_left": self.days_left(),
            "hours_per_day": self.hours_per_day,
            "topics": [topic.to_dict() for topic in self.topics],
            "created_at": self.created_at,
            "progress": self.progress(),
        }

    def days_left(self) -> int:
        """Wie viele Tage noch bleiben."""

        return max(0, int((self.exam_at - time.time()) / DAY))

    def total_hours(self) -> float:
        """Der geschätzte Gesamtaufwand."""

        return sum(topic.hours for topic in self.topics)

    def remaining_hours(self) -> float:
        """Der Aufwand für das, was noch offen ist."""

        return sum(topic.hours for topic in self.topics if not topic.done)

    def available_hours(self) -> float:
        """Wie viele Stunden bis zum Termin zur Verfügung stehen."""

        return self.days_left() * self.hours_per_day

    def progress(self) -> dict[str, Any]:
        """Der Stand des Plans."""

        if not self.topics:
            return {"done": 0, "total": 0, "percent": 0.0, "feasible": True, "note": ""}

        done = sum(1 for topic in self.topics if topic.done)
        remaining = self.remaining_hours()
        available = self.available_hours()
        feasible = remaining <= available

        note = ""
        if not feasible and self.days_left() > 0:
            shortfall = remaining - available
            note = (
                f"Es fehlen etwa {shortfall:.0f} Stunden. Entweder mehr Zeit am Tag "
                f"({remaining / max(1, self.days_left()):.1f} statt "
                f"{self.hours_per_day:.1f} Stunden), oder Themen streichen."
            )
        elif self.days_left() == 0:
            note = "Der Termin ist heute oder vorbei."
        elif feasible:
            spare = available - remaining
            note = f"Der Plan geht auf, mit etwa {spare:.0f} Stunden Puffer."

        return {
            "done": done,
            "total": len(self.topics),
            "percent": round(done / len(self.topics) * 100, 1),
            "remaining_hours": round(remaining, 1),
            "available_hours": round(available, 1),
            "feasible": feasible,
            "note": note,
        }


class StudyPlanner:
    """Legt Lernpläne an und verteilt die Themen."""

    def __init__(self, *, store_filename: str = "learning/study_plans.json") -> None:
        self._store = JsonStore(store_filename, default={"plans": {}})
        self._plans: dict[str, StudyPlan] = {}
        self._load()

    def _load(self) -> None:
        for raw in (self._store.get("plans", {}) or {}).values():
            plan_id = str(raw.get("plan_id", ""))
            if not plan_id:
                continue

            topics = [
                Topic(
                    topic_id=str(item.get("topic_id", uuid.uuid4().hex[:8])),
                    title=str(item.get("title", "")),
                    difficulty=int(item.get("difficulty", 3)),
                    hours=float(item.get("hours", 2.0)),
                    deck=str(item.get("deck", "")),
                    notes=str(item.get("notes", "")),
                    done=bool(item.get("done", False)),
                    confidence=float(item.get("confidence", 0.0)),
                    scheduled_for=float(item.get("scheduled_for", 0.0)),
                )
                for item in (raw.get("topics", []) or [])
            ]

            self._plans[plan_id] = StudyPlan(
                plan_id=plan_id,
                title=str(raw.get("title", "")),
                exam_at=float(raw.get("exam_at", time.time())),
                hours_per_day=float(raw.get("hours_per_day", 3.0)),
                topics=topics,
                created_at=float(raw.get("created_at", time.time())),
            )

    def _save(self) -> None:
        self._store.set(
            "plans", {plan_id: plan.to_dict() for plan_id, plan in self._plans.items()}
        )

    # --- Anlegen ------------------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        exam_date: str,
        hours_per_day: float = 3.0,
        topics: list[dict[str, Any]] | None = None,
    ) -> tuple[StudyPlan | None, str]:
        """Legt einen Lernplan an.

        Args:
            title: Wie der Plan heißt.
            exam_date: Der Termin als ``TT.MM.JJJJ`` oder ``JJJJ-MM-TT``.
            hours_per_day: Wie viel Zeit am Tag zur Verfügung steht.
            topics: Die Themen, je mit ``title``, ``difficulty``, ``hours``.

        Returns:
            Der Plan und eine Meldung im Klartext.
        """

        exam_at = self._parse_date(exam_date)
        if exam_at is None:
            return None, (
                f"'{exam_date}' ist kein erkennbares Datum. Erwartet wird "
                "TT.MM.JJJJ oder JJJJ-MM-TT."
            )

        if exam_at < time.time():
            return None, "Der Termin liegt in der Vergangenheit."

        plan = StudyPlan(
            plan_id=uuid.uuid4().hex[:12],
            title=title.strip() or "Lernplan",
            exam_at=exam_at,
            hours_per_day=max(0.5, min(14.0, hours_per_day)),
        )

        for entry in topics or []:
            plan.topics.append(
                Topic(
                    topic_id=uuid.uuid4().hex[:8],
                    title=str(entry.get("title", "")).strip(),
                    difficulty=max(1, min(5, int(entry.get("difficulty", 3)))),
                    hours=max(0.25, float(entry.get("hours", 2.0))),
                    deck=str(entry.get("deck", "")),
                    notes=str(entry.get("notes", "")),
                )
            )

        self._plans[plan.plan_id] = plan
        self.schedule(plan.plan_id)

        progress = plan.progress()
        return plan, (
            f"Lernplan '{plan.title}' angelegt: {len(plan.topics)} Themen, "
            f"{plan.days_left()} Tage. {progress['note']}"
        )

    @staticmethod
    def _parse_date(text: str) -> float | None:
        """Liest ein Datum in den gebräuchlichen Schreibweisen."""

        cleaned = text.strip()
        for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(cleaned, pattern)
                # Auf das Ende des Tages setzen: Eine Prüfung am 15. heißt
                # nicht, dass der 15. nicht mehr zum Lernen zählt.
                return parsed.replace(hour=23, minute=59).timestamp()
            except ValueError:
                continue
        return None

    def add_topic(
        self,
        plan_id: str,
        title: str,
        *,
        difficulty: int = 3,
        hours: float = 2.0,
        deck: str = "",
    ) -> tuple[bool, str]:
        """Ergänzt ein Thema."""

        plan = self._plans.get(plan_id)
        if plan is None:
            return False, "Diesen Lernplan gibt es nicht."

        plan.topics.append(
            Topic(
                topic_id=uuid.uuid4().hex[:8],
                title=title.strip(),
                difficulty=max(1, min(5, difficulty)),
                hours=max(0.25, hours),
                deck=deck,
            )
        )
        self.schedule(plan_id)
        return True, f"'{title}' aufgenommen."

    # --- Verteilen -------------------------------------------------------------------

    def schedule(self, plan_id: str) -> tuple[bool, str]:
        """Verteilt die offenen Themen über die verbleibenden Tage.

        Schwieriges zuerst, und der letzte Tag bleibt für Wiederholung frei.
        """

        plan = self._plans.get(plan_id)
        if plan is None:
            return False, "Diesen Lernplan gibt es nicht."

        open_topics = [topic for topic in plan.topics if not topic.done]
        if not open_topics:
            self._save()
            return True, "Es ist nichts mehr offen."

        # Schwerstes zuerst; bei gleichem Schwierigkeitsgrad das Aufwendigere.
        open_topics.sort(key=lambda topic: (-topic.difficulty, -topic.hours))

        days = max(1, plan.days_left())
        # Der letzte Tag ist für Wiederholung reserviert.
        planning_days = max(1, days - 1) if days > 1 else 1

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        day_index = 0
        used_today = 0.0

        for topic in open_topics:
            # Erst umbrechen, wenn der Tag schon etwas trägt. Ohne diese
            # Bedingung landete ein Thema, das allein länger dauert als ein
            # Lerntag, immer erst am Folgetag – und heute stünde nichts an.
            if (
                used_today > 0.0
                and used_today + topic.hours > plan.hours_per_day
                and day_index < planning_days - 1
            ):
                day_index += 1
                used_today = 0.0

            topic.scheduled_for = (today + timedelta(days=day_index)).timestamp()
            used_today += topic.hours

        self._save()

        progress = plan.progress()
        return True, (
            f"{len(open_topics)} Themen auf {min(day_index + 1, planning_days)} Tage "
            f"verteilt. {progress['note']}"
        )

    def today(self, plan_id: str = "") -> list[dict[str, Any]]:
        """Was heute dran ist."""

        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        end = start + DAY

        found: list[dict[str, Any]] = []
        for plan in self._plans.values():
            if plan_id and plan.plan_id != plan_id:
                continue
            for topic in plan.topics:
                # Überfälliges gehört ebenfalls auf heute – sonst verschwindet
                # es lautlos aus dem Plan.
                if not topic.done and topic.scheduled_for and topic.scheduled_for < end:
                    found.append({**topic.to_dict(), "plan": plan.title, "plan_id": plan.plan_id})

        found.sort(key=lambda item: (-int(item["difficulty"]), item["title"]))
        return found

    # --- Fortschritt ---------------------------------------------------------------------

    def mark_done(self, plan_id: str, topic_id: str, *, confidence: float = 0.7) -> tuple[bool, str]:
        """Hakt ein Thema ab."""

        plan = self._plans.get(plan_id)
        if plan is None:
            return False, "Diesen Lernplan gibt es nicht."

        for topic in plan.topics:
            if topic.topic_id == topic_id:
                topic.done = True
                topic.confidence = max(0.0, min(1.0, confidence))
                self.schedule(plan_id)
                progress = plan.progress()
                return True, (
                    f"'{topic.title}' abgehakt. {progress['done']} von "
                    f"{progress['total']} geschafft ({progress['percent']:.0f} Prozent)."
                )

        return False, "Dieses Thema gibt es im Plan nicht."

    def reopen(self, plan_id: str, topic_id: str) -> tuple[bool, str]:
        """Nimmt ein Thema wieder auf – etwa nach einer misslungenen Abfrage."""

        plan = self._plans.get(plan_id)
        if plan is None:
            return False, "Diesen Lernplan gibt es nicht."

        for topic in plan.topics:
            if topic.topic_id == topic_id:
                topic.done = False
                topic.confidence = 0.0
                self.schedule(plan_id)
                return True, f"'{topic.title}' steht wieder an."

        return False, "Dieses Thema gibt es im Plan nicht."

    def sync_with_flashcards(self, plan_id: str, deck_status: list[dict[str, Any]]) -> dict[str, Any]:
        """Gleicht den Fortschritt mit den Karteikarten ab.

        Damit steht hinter einem abgehakten Thema etwas Nachprüfbares:
        Wackeln die zugehörigen Karten, wird das Thema wieder geöffnet.
        """

        plan = self._plans.get(plan_id)
        if plan is None:
            return {"updated": 0, "reopened": []}

        by_deck = {str(entry.get("deck", "")): entry for entry in deck_status}
        reopened: list[str] = []
        updated = 0

        for topic in plan.topics:
            if not topic.deck or topic.deck not in by_deck:
                continue

            entry = by_deck[topic.deck]
            total = int(entry.get("total", 0)) or 1
            mastered = int(entry.get("mastered", 0))
            shaky = int(entry.get("shaky", 0))

            topic.confidence = round(mastered / total, 2)
            updated += 1

            # Sitzt weniger als ein Drittel und wackelt etwas, war das Thema
            # nicht wirklich fertig.
            if topic.done and shaky > 0 and topic.confidence < 0.34:
                topic.done = False
                reopened.append(topic.title)

        if reopened:
            self.schedule(plan_id)
        else:
            self._save()

        return {"updated": updated, "reopened": reopened}

    # --- Auskunft -------------------------------------------------------------------------

    def plans(self) -> list[dict[str, Any]]:
        """Alle Lernpläne."""

        return [
            plan.to_dict()
            for plan in sorted(self._plans.values(), key=lambda item: item.exam_at)
        ]

    def get(self, plan_id: str) -> dict[str, Any] | None:
        """Einen Lernplan holen."""

        plan = self._plans.get(plan_id)
        return plan.to_dict() if plan else None

    def remove(self, plan_id: str) -> tuple[bool, str]:
        """Löscht einen Lernplan."""

        plan = self._plans.pop(plan_id, None)
        if plan is None:
            return False, "Diesen Lernplan gibt es nicht."
        self._save()
        return True, f"Lernplan '{plan.title}' gelöscht."

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        upcoming = [plan for plan in self._plans.values() if plan.days_left() > 0]
        return {
            "plans": len(self._plans),
            "upcoming": len(upcoming),
            "next_exam": (
                min(upcoming, key=lambda plan: plan.exam_at).to_dict()
                if upcoming
                else None
            ),
            "today": len(self.today()),
            "store": str(self._store.path),
        }
