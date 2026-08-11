"""Lernen aus der Nutzung (v2 Phase 18).

AI-Orb soll mit der Zeit besser passen. Nicht, indem er ein Modell
nachtrainiert – das wäre auf einem Arbeitsplatzrechner weder machbar noch
sinnvoll –, sondern indem er beobachtet, **wie** er benutzt wird, und daraus
wenige, überprüfbare Schlüsse zieht: Wie lang sollen Antworten sein? Wann
ist der Benutzer da? Welche Themen kommen immer wieder?

Drei Grundsätze halten das ehrlich:

**Nur Beobachtbares.** Gezählt wird, was tatsächlich geschehen ist – wie
lang eine Frage war, ob nachgefragt wurde, zu welcher Stunde. Es werden
keine Persönlichkeitsschlüsse gezogen; die Reflexionsvorgabe schließt
personenbezogene Schlussfolgerungen ausdrücklich aus.

**Erst ab genügend Belegen.** Eine Vorliebe gilt erst, wenn sie sich
mehrfach gezeigt hat. Aus einer einzigen kurzen Frage folgt nicht, dass
jemand immer Kurzfassungen will.

**Jederzeit einsehbar und löschbar.** Was gelernt wurde, steht im Klartext
in ``data/learning/preferences.json`` und lässt sich mit einem Aufruf
vergessen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.utils.store import JsonStore

logger = get_logger(__name__)

#: Ab wie vielen Beobachtungen eine Vorliebe als belegt gilt.
DEFAULT_MINIMUM_OBSERVATIONS = 8


@dataclass
class Preference:
    """Eine abgeleitete Vorliebe."""

    key: str
    value: Any
    #: Wie sicher – ergibt sich aus der Zahl der Belege.
    confidence: float
    #: Worauf sie beruht, im Klartext.
    evidence: str
    observations: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence,
            "observations": self.observations,
        }


class PreferenceLearner:
    """Beobachtet die Nutzung und leitet Vorlieben ab."""

    def __init__(self, *, store_filename: str = "learning/preferences.json") -> None:
        config = get_config()

        self._enabled = bool(config.get("learning.enabled", True))
        self._minimum = int(
            config.get("learning.minimum_observations", DEFAULT_MINIMUM_OBSERVATIONS)
        )

        self._store = JsonStore(
            store_filename,
            default={
                "interactions": 0,
                "question_lengths": [],
                "answer_ratings": [],
                "follow_up_count": 0,
                "hours": {},
                "topics": {},
                "voice_used": 0,
                "text_used": 0,
                "first_seen": time.time(),
            },
        )

    @property
    def enabled(self) -> bool:
        """Ob gelernt wird."""

        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Schaltet das Lernen ein oder aus."""

        self._enabled = enabled
        logger.info("Lernen aus der Nutzung %s.", "eingeschaltet" if enabled else "ausgeschaltet")

    # --- Beobachten ----------------------------------------------------------------

    def observe_interaction(
        self,
        *,
        question: str,
        answer: str,
        via_voice: bool = False,
        was_follow_up: bool = False,
        topics: list[str] | None = None,
    ) -> None:
        """Hält einen Austausch fest.

        Args:
            question: Was gefragt wurde.
            answer: Was geantwortet wurde.
            via_voice: Ob es gesprochen war.
            was_follow_up: Ob es eine Rückfrage zur vorigen Antwort war.
            topics: Erkannte Themen.
        """

        if not self._enabled:
            return

        data = self._store.data

        data["interactions"] = int(data.get("interactions", 0)) + 1

        lengths: list[int] = list(data.get("question_lengths", []))
        lengths.append(len(question))
        data["question_lengths"] = lengths[-200:]

        if was_follow_up:
            data["follow_up_count"] = int(data.get("follow_up_count", 0)) + 1

        if via_voice:
            data["voice_used"] = int(data.get("voice_used", 0)) + 1
        else:
            data["text_used"] = int(data.get("text_used", 0)) + 1

        hour = str(time.localtime().tm_hour)
        hours: dict[str, int] = dict(data.get("hours", {}))
        hours[hour] = hours.get(hour, 0) + 1
        data["hours"] = hours

        if topics:
            counted: dict[str, int] = dict(data.get("topics", {}))
            for topic in topics:
                cleaned = topic.strip().lower()
                if len(cleaned) >= 3:
                    counted[cleaned] = counted.get(cleaned, 0) + 1
            # Nur die häufigsten behalten, sonst wächst die Datei unbegrenzt.
            data["topics"] = dict(
                sorted(counted.items(), key=lambda item: item[1], reverse=True)[:100]
            )

        self._store.save()

    def observe_rating(self, helpful: bool) -> None:
        """Hält eine Rückmeldung des Benutzers fest."""

        if not self._enabled:
            return
        ratings: list[int] = list(self._store.data.get("answer_ratings", []))
        ratings.append(1 if helpful else 0)
        self._store.data["answer_ratings"] = ratings[-100:]
        self._store.save()

    # --- Ableiten ------------------------------------------------------------------------

    def preferences(self) -> list[Preference]:
        """Leitet die belegten Vorlieben ab.

        Nur was oft genug beobachtet wurde, erscheint hier. Alles andere
        wird weggelassen, statt es mit einer niedrigen Sicherheit anzugeben –
        eine unsichere Vorliebe ist schlechter als keine, weil sie das
        Verhalten in eine womöglich falsche Richtung lenkt.
        """

        data = self._store.data
        interactions = int(data.get("interactions", 0))
        found: list[Preference] = []

        if interactions < self._minimum:
            return found

        # --- Antwortlänge -----------------------------------------------------------
        lengths: list[int] = list(data.get("question_lengths", []))
        if len(lengths) >= self._minimum:
            average = sum(lengths) / len(lengths)
            if average < 40:
                found.append(
                    Preference(
                        "antwortlaenge",
                        "kurz",
                        self._confidence(len(lengths)),
                        f"Die Fragen sind im Schnitt {average:.0f} Zeichen lang – "
                        "kurz gefragt heißt meist: kurz geantwortet.",
                        len(lengths),
                    )
                )
            elif average > 140:
                found.append(
                    Preference(
                        "antwortlaenge",
                        "ausführlich",
                        self._confidence(len(lengths)),
                        f"Die Fragen sind im Schnitt {average:.0f} Zeichen lang und "
                        "damit ausführlich gestellt.",
                        len(lengths),
                    )
                )

        # --- Bevorzugter Weg ---------------------------------------------------------
        voice = int(data.get("voice_used", 0))
        text = int(data.get("text_used", 0))
        total = voice + text
        if total >= self._minimum:
            if voice > text * 2:
                found.append(
                    Preference(
                        "eingabeweg",
                        "sprache",
                        self._confidence(total),
                        f"{voice} von {total} Anfragen kamen gesprochen.",
                        total,
                    )
                )
            elif text > voice * 2:
                found.append(
                    Preference(
                        "eingabeweg",
                        "text",
                        self._confidence(total),
                        f"{text} von {total} Anfragen kamen getippt.",
                        total,
                    )
                )

        # --- Aktive Zeiten ------------------------------------------------------------
        hours: dict[str, int] = dict(data.get("hours", {}))
        if sum(hours.values()) >= self._minimum:
            busiest = sorted(hours.items(), key=lambda item: item[1], reverse=True)[:3]
            times = ", ".join(f"{hour} Uhr" for hour, _ in busiest)
            found.append(
                Preference(
                    "aktive_zeiten",
                    [int(hour) for hour, _ in busiest],
                    self._confidence(sum(hours.values())),
                    f"Am häufigsten bist du um {times} da.",
                    sum(hours.values()),
                )
            )

        # --- Wiederkehrende Themen -------------------------------------------------------
        topics: dict[str, int] = dict(data.get("topics", {}))
        recurring = [
            (topic, count) for topic, count in topics.items() if count >= max(3, self._minimum // 2)
        ]
        if recurring:
            recurring.sort(key=lambda item: item[1], reverse=True)
            names = [topic for topic, _ in recurring[:5]]
            found.append(
                Preference(
                    "themen",
                    names,
                    self._confidence(sum(count for _, count in recurring)),
                    "Wiederkehrende Themen: " + ", ".join(names),
                    len(recurring),
                )
            )

        # --- Rückfragequote ---------------------------------------------------------------
        follow_ups = int(data.get("follow_up_count", 0))
        if interactions >= self._minimum and follow_ups / max(1, interactions) > 0.35:
            found.append(
                Preference(
                    "nachfragen",
                    "haeufig",
                    self._confidence(interactions),
                    f"Auf {follow_ups} von {interactions} Antworten folgte eine "
                    "Rückfrage. Das spricht dafür, gleich mehr Zusammenhang zu geben.",
                    interactions,
                )
            )

        return found

    def _confidence(self, observations: int) -> float:
        """Rechnet die Zahl der Belege in eine Sicherheit um.

        Bewusst gedeckelt: Auch tausend Beobachtungen ergeben keine
        Gewissheit über einen Menschen.
        """

        if observations < self._minimum:
            return 0.0
        return min(0.85, 0.4 + 0.45 * min(1.0, observations / (self._minimum * 5)))

    def guidance(self) -> str:
        """Fasst die Vorlieben als Zusatz für den Systemprompt zusammen.

        Leer, solange nichts belegt ist – ein Systemprompt soll nicht mit
        Vermutungen aufgeblasen werden.
        """

        preferences = self.preferences()
        if not preferences:
            return ""

        lines: list[str] = []
        for preference in preferences:
            if preference.key == "antwortlaenge":
                lines.append(
                    "Halte dich kurz."
                    if preference.value == "kurz"
                    else "Antworte ausführlich und mit Zusammenhang."
                )
            elif preference.key == "eingabeweg" and preference.value == "sprache":
                lines.append(
                    "Deine Antworten werden meist vorgelesen. Schreibe deshalb so, "
                    "dass sie gesprochen gut klingen: ganze Sätze, keine "
                    "Aufzählungszeichen, keine Tabellen."
                )
            elif preference.key == "nachfragen":
                lines.append(
                    "Gib gleich etwas mehr Zusammenhang mit – es wird oft nachgefragt."
                )
            elif preference.key == "themen" and isinstance(preference.value, list):
                lines.append(
                    "Wiederkehrende Themen des Benutzers: " + ", ".join(preference.value[:5]) + "."
                )

        if not lines:
            return ""

        return "Was du über den Benutzer gelernt hast:\n" + "\n".join(f"- {line}" for line in lines)

    # --- Verwaltung ----------------------------------------------------------------------

    def forget(self) -> None:
        """Vergisst alles Gelernte."""

        self._store.clear()
        logger.info("Alles Gelernte wurde vergessen.")

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        data = self._store.data
        return {
            "enabled": self._enabled,
            "interactions": int(data.get("interactions", 0)),
            "minimum_observations": self._minimum,
            "preferences": [item.to_dict() for item in self.preferences()],
            "store": str(self._store.path),
        }
