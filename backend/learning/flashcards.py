"""Karteikarten mit abgestuften Wiederholungen (Phase 18).

Der Kern ist das Prinzip der verteilten Wiederholung: Was man sicher weiß,
wird selten abgefragt, was wackelt, häufig. Dadurch verbringt man die Lernzeit
dort, wo sie etwas bringt, statt zum zwanzigsten Mal zu wiederholen, was
längst sitzt.

Umgesetzt ist eine Fassung des SM-2-Verfahrens, wie es Anki und Verwandte
benutzen. Jede Karte trägt drei Werte:

* **Leichtigkeit** – wie gut die Karte sitzt. Startet bei 2,5 und wandert
  mit jeder Antwort.
* **Abstand** – wie viele Tage bis zur nächsten Abfrage.
* **Serie** – wie oft sie hintereinander richtig war. Ein Fehler setzt sie
  auf null; damit kommt die Karte am nächsten Tag wieder.

Die Bewertung erfolgt in vier Stufen statt richtig/falsch. Der Unterschied
zwischen „mit Mühe erinnert" und „sofort gewusst" ist für die Terminplanung
der wichtigste, und er geht verloren, wenn man nur zwei Knöpfe anbietet.

Alles liegt lokal in ``data/learning/flashcards.json``.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Ein Tag in Sekunden.
DAY = 86400.0

#: Startwert der Leichtigkeit.
INITIAL_EASE = 2.5

#: Untergrenze. Darunter käme eine Karte praktisch täglich, was den Stapel
#: verstopft, ohne dem Lernen zu helfen.
MINIMUM_EASE = 1.3


class Grade(Enum):
    """Wie gut eine Karte gewusst wurde."""

    #: Gar nicht gewusst.
    AGAIN = 0
    #: Mit Mühe erinnert.
    HARD = 1
    #: Gewusst.
    GOOD = 2
    #: Sofort und sicher gewusst.
    EASY = 3

    @classmethod
    def parse(cls, value: Any) -> "Grade":
        if isinstance(value, Grade):
            return value
        text = str(value).strip().lower()
        mapping = {
            "0": cls.AGAIN, "again": cls.AGAIN, "nochmal": cls.AGAIN, "falsch": cls.AGAIN,
            "1": cls.HARD, "hard": cls.HARD, "schwer": cls.HARD, "mühsam": cls.HARD,
            "2": cls.GOOD, "good": cls.GOOD, "gut": cls.GOOD, "richtig": cls.GOOD,
            "3": cls.EASY, "easy": cls.EASY, "leicht": cls.EASY, "einfach": cls.EASY,
        }
        return mapping.get(text, cls.GOOD)

    def label(self) -> str:
        return {
            Grade.AGAIN: "nochmal",
            Grade.HARD: "mühsam",
            Grade.GOOD: "gewusst",
            Grade.EASY: "sofort gewusst",
        }[self]


@dataclass
class Card:
    """Eine Karteikarte."""

    card_id: str
    front: str
    back: str
    deck: str = "allgemein"
    tags: list[str] = field(default_factory=list)

    #: Wie gut die Karte sitzt.
    ease: float = INITIAL_EASE
    #: Abstand bis zur nächsten Abfrage, in Tagen.
    interval_days: float = 0.0
    #: Wie oft hintereinander richtig.
    streak: int = 0
    #: Wann sie das nächste Mal fällig ist.
    due_at: float = field(default_factory=time.time)

    reviews: int = 0
    lapses: int = 0
    created_at: float = field(default_factory=time.time)
    last_reviewed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "front": self.front,
            "back": self.back,
            "deck": self.deck,
            "tags": list(self.tags),
            "ease": round(self.ease, 3),
            "interval_days": round(self.interval_days, 2),
            "streak": self.streak,
            "due_at": self.due_at,
            "due_in_days": round((self.due_at - time.time()) / DAY, 2),
            "reviews": self.reviews,
            "lapses": self.lapses,
            "created_at": self.created_at,
            "last_reviewed": self.last_reviewed,
            "mastery": self.mastery(),
        }

    def is_due(self, at: float | None = None) -> bool:
        """Ob die Karte fällig ist."""

        return self.due_at <= (at if at is not None else time.time())

    def is_new(self) -> bool:
        """Ob sie noch nie abgefragt wurde."""

        return self.reviews == 0

    def mastery(self) -> str:
        """Wie sicher die Karte sitzt – für die Fortschrittsanzeige."""

        if self.reviews == 0:
            return "neu"
        if self.streak == 0:
            return "wackelig"
        if self.interval_days >= 60:
            return "sitzt"
        if self.interval_days >= 14:
            return "gut"
        return "im Aufbau"


class FlashcardDeck:
    """Verwaltet Karteikarten und ihre Abfragetermine."""

    def __init__(self, *, store_filename: str = "learning/flashcards.json") -> None:
        self._store = JsonStore(store_filename, default={"cards": {}, "sessions": []})
        self._cards: dict[str, Card] = {}
        self._load()

    def _load(self) -> None:
        for raw in (self._store.get("cards", {}) or {}).values():
            card_id = str(raw.get("card_id", ""))
            if not card_id:
                continue
            self._cards[card_id] = Card(
                card_id=card_id,
                front=str(raw.get("front", "")),
                back=str(raw.get("back", "")),
                deck=str(raw.get("deck", "allgemein")),
                tags=[str(tag) for tag in (raw.get("tags", []) or [])],
                ease=float(raw.get("ease", INITIAL_EASE)),
                interval_days=float(raw.get("interval_days", 0.0)),
                streak=int(raw.get("streak", 0)),
                due_at=float(raw.get("due_at", time.time())),
                reviews=int(raw.get("reviews", 0)),
                lapses=int(raw.get("lapses", 0)),
                created_at=float(raw.get("created_at", time.time())),
                last_reviewed=float(raw.get("last_reviewed", 0.0)),
            )

        if self._cards:
            logger.info("Karteikarten geladen: %d.", len(self._cards))

    def _save(self) -> None:
        self._store.set("cards", {card_id: card.to_dict() for card_id, card in self._cards.items()})

    # --- Karten anlegen ---------------------------------------------------------------

    def add(
        self,
        front: str,
        back: str,
        *,
        deck: str = "allgemein",
        tags: list[str] | None = None,
    ) -> tuple[Card | None, str]:
        """Legt eine Karte an.

        Doppelte Vorderseiten im selben Stapel werden abgewiesen: Zwei Karten
        mit derselben Frage und verschiedenen Antworten machen das Lernen
        kaputt, weil man nie weiß, welche gemeint ist.
        """

        question = front.strip()
        answer = back.strip()

        if len(question) < 3:
            return None, "Die Vorderseite ist zu kurz."
        if len(answer) < 1:
            return None, "Die Rückseite ist leer."

        for card in self._cards.values():
            if card.deck == deck and card.front.lower() == question.lower():
                return None, f"Im Stapel '{deck}' gibt es diese Frage bereits."

        card = Card(
            card_id=uuid.uuid4().hex[:12],
            front=question,
            back=answer,
            deck=deck.strip() or "allgemein",
            tags=[str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()],
        )
        self._cards[card.card_id] = card
        self._save()
        return card, f"Karte im Stapel '{card.deck}' angelegt."

    def add_many(self, pairs: list[tuple[str, str]], *, deck: str = "allgemein") -> dict[str, Any]:
        """Legt mehrere Karten auf einmal an."""

        created = 0
        skipped: list[str] = []
        for front, back in pairs:
            card, message = self.add(front, back, deck=deck)
            if card is not None:
                created += 1
            else:
                skipped.append(f"{front[:40]}: {message}")

        self._save()
        return {"created": created, "skipped": skipped, "deck": deck}

    def remove(self, card_id: str) -> tuple[bool, str]:
        """Entfernt eine Karte."""

        card = self._cards.pop(card_id, None)
        if card is None:
            return False, "Diese Karte gibt es nicht."
        self._save()
        return True, f"Karte entfernt: {card.front[:50]}"

    # --- Abfragen ---------------------------------------------------------------------

    def due_cards(self, *, deck: str = "", limit: int = 20, include_new: bool = True) -> list[Card]:
        """Die Karten, die jetzt dran sind.

        Sortiert wird nach Fälligkeit, wobei überfällige zuerst kommen. Neue
        Karten werden ans Ende gestellt – erst wiederholen, was man schon
        angefangen hat, dann Neues aufnehmen. Andersherum wächst der Stapel
        schneller, als man ihn abbauen kann.
        """

        now = time.time()
        candidates = [
            card
            for card in self._cards.values()
            if (not deck or card.deck == deck) and card.is_due(now)
        ]

        if not include_new:
            candidates = [card for card in candidates if not card.is_new()]

        candidates.sort(key=lambda card: (card.is_new(), card.due_at))
        return candidates[: max(1, limit)]

    def next_card(self, *, deck: str = "") -> Card | None:
        """Die nächste fällige Karte."""

        due = self.due_cards(deck=deck, limit=1)
        return due[0] if due else None

    def review(self, card_id: str, grade: Any) -> tuple[Card | None, str]:
        """Bewertet eine Karte und legt den nächsten Termin fest.

        Das ist das Herzstück. Die Regeln:

        * „nochmal" setzt die Serie zurück; die Karte kommt am nächsten Tag
          wieder und die Leichtigkeit sinkt.
        * Sonst wächst der Abstand mit der Leichtigkeit. Der erste richtige
          Abstand ist ein Tag, der zweite sechs – dann wird multipliziert.
        * Die Leichtigkeit steigt bei „sofort gewusst" und sinkt bei
          „mühsam", bleibt aber immer über der Untergrenze.
        """

        card = self._cards.get(card_id)
        if card is None:
            return None, "Diese Karte gibt es nicht."

        resolved = Grade.parse(grade)
        card.reviews += 1
        card.last_reviewed = time.time()

        if resolved is Grade.AGAIN:
            card.lapses += 1
            card.streak = 0
            card.interval_days = 1.0
            card.ease = max(MINIMUM_EASE, card.ease - 0.2)
        else:
            card.streak += 1

            if card.streak == 1:
                card.interval_days = 1.0
            elif card.streak == 2:
                card.interval_days = 6.0
            else:
                card.interval_days = card.interval_days * card.ease

            if resolved is Grade.HARD:
                card.interval_days = max(1.0, card.interval_days * 0.6)
                card.ease = max(MINIMUM_EASE, card.ease - 0.15)
            elif resolved is Grade.EASY:
                card.interval_days *= 1.3
                card.ease = min(3.2, card.ease + 0.15)

            # Obergrenze: Ein Jahr genügt. Alles darüber verschwindet aus dem
            # Blick, und Wissen, das man ein Jahr nicht braucht, ist ohnehin
            # weg.
            card.interval_days = min(365.0, card.interval_days)

        card.due_at = time.time() + card.interval_days * DAY
        self._save()

        when = datetime.fromtimestamp(card.due_at).strftime("%d.%m.%Y")
        return card, f"{resolved.label()} – nächste Abfrage am {when}."

    # --- Fortschritt -----------------------------------------------------------------------

    def decks(self) -> list[dict[str, Any]]:
        """Alle Stapel mit ihrem Stand."""

        grouped: dict[str, list[Card]] = {}
        for card in self._cards.values():
            grouped.setdefault(card.deck, []).append(card)

        now = time.time()
        result = []
        for name, cards in sorted(grouped.items()):
            result.append(
                {
                    "deck": name,
                    "total": len(cards),
                    "due": sum(1 for card in cards if card.is_due(now)),
                    "new": sum(1 for card in cards if card.is_new()),
                    "mastered": sum(1 for card in cards if card.interval_days >= 60),
                    "shaky": sum(1 for card in cards if card.reviews > 0 and card.streak == 0),
                }
            )
        return result

    def weak_cards(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Die Karten, die am meisten Mühe machen.

        Maßstab ist die Zahl der Rückfälle im Verhältnis zu den Abfragen –
        nicht die absolute Zahl, sonst stünden nur die ältesten Karten oben.
        """

        scored = [
            (card.lapses / max(1, card.reviews), card)
            for card in self._cards.values()
            if card.reviews >= 2 and card.lapses > 0
        ]
        scored.sort(key=lambda item: (item[0], item[1].lapses), reverse=True)

        return [
            {**card.to_dict(), "difficulty": round(ratio, 2)}
            for ratio, card in scored[:limit]
        ]

    def forecast(self, days: int = 7) -> list[dict[str, Any]]:
        """Wie viele Karten in den nächsten Tagen anstehen.

        Nützlich, um zu sehen, ob sich ein Berg aufbaut – und um vor einer
        Prüfung zu planen.
        """

        now = datetime.now()
        buckets: list[dict[str, Any]] = []

        for offset in range(max(1, min(60, days))):
            day_start = (now + timedelta(days=offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_end = day_start + timedelta(days=1)

            count = sum(
                1
                for card in self._cards.values()
                if day_start.timestamp() <= card.due_at < day_end.timestamp()
            )

            # Was heute schon überfällig ist, gehört auf den ersten Tag.
            if offset == 0:
                count += sum(1 for card in self._cards.values() if card.due_at < day_start.timestamp())

            buckets.append(
                {
                    "date": day_start.strftime("%d.%m.%Y"),
                    "weekday": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][day_start.weekday()],
                    "count": count,
                }
            )

        return buckets

    def cards(self, *, deck: str = "", limit: int = 200) -> list[dict[str, Any]]:
        """Alle Karten, wahlweise eines Stapels."""

        selected = [
            card for card in self._cards.values() if not deck or card.deck == deck
        ]
        selected.sort(key=lambda card: card.due_at)
        return [card.to_dict() for card in selected[:limit]]

    def clear(self, *, deck: str = "") -> int:
        """Löscht Karten – einen Stapel oder alle."""

        if deck:
            targets = [card_id for card_id, card in self._cards.items() if card.deck == deck]
        else:
            targets = list(self._cards)

        for card_id in targets:
            self._cards.pop(card_id, None)
        self._save()

        logger.info("Karteikarten gelöscht: %d.", len(targets))
        return len(targets)

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        now = time.time()
        return {
            "total": len(self._cards),
            "due": sum(1 for card in self._cards.values() if card.is_due(now)),
            "new": sum(1 for card in self._cards.values() if card.is_new()),
            "mastered": sum(1 for card in self._cards.values() if card.interval_days >= 60),
            "decks": self.decks(),
            "store": str(self._store.path),
        }
