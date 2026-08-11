"""Tagesrhythmus des Orb (v2 Phase 22).

Der Orb soll nicht rund um die Uhr gleich auftreten. Um drei Uhr nachts
denselben munteren Ton anzuschlagen wie am Vormittag wirkt gedankenlos –
und ein Orb, der nachts hell leuchtet, während man vor dem Rechner
einschläft, ist schlicht störend.

Dieses Modul bildet deshalb einen Tagesverlauf ab. Es liefert kein Verhalten,
sondern eine Einschätzung: Wie viel Tatendrang passt gerade? Wie hell darf
es sein? Ist eine Begrüßung angebracht?

Bewusst schlicht gehalten. Es gibt keine Vorhersage, wann der Benutzer müde
ist – so etwas zu behaupten wäre Anmaßung. Grundlage ist die Uhrzeit, und wo
Beobachtungen vorliegen, werden sie hinzugezogen: Wer regelmäßig um
Mitternacht arbeitet, soll um Mitternacht keinen schlafenden Orb vorfinden.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class DayPhase(Enum):
    """Die Abschnitte des Tages."""

    NIGHT = "nacht"
    EARLY_MORNING = "frueher_morgen"
    MORNING = "morgen"
    MIDDAY = "mittag"
    AFTERNOON = "nachmittag"
    EVENING = "abend"
    LATE_EVENING = "spaeter_abend"

    def greeting(self) -> str:
        """Die passende Begrüßung."""

        return {
            DayPhase.NIGHT: "Noch wach?",
            DayPhase.EARLY_MORNING: "Guten Morgen.",
            DayPhase.MORNING: "Guten Morgen.",
            DayPhase.MIDDAY: "Mahlzeit.",
            DayPhase.AFTERNOON: "Guten Tag.",
            DayPhase.EVENING: "Guten Abend.",
            DayPhase.LATE_EVENING: "Guten Abend.",
        }[self]

    def description(self) -> str:
        return {
            DayPhase.NIGHT: "Tiefe Nacht",
            DayPhase.EARLY_MORNING: "Früher Morgen",
            DayPhase.MORNING: "Vormittag",
            DayPhase.MIDDAY: "Mittagszeit",
            DayPhase.AFTERNOON: "Nachmittag",
            DayPhase.EVENING: "Abend",
            DayPhase.LATE_EVENING: "Später Abend",
        }[self]


#: Von welcher Stunde an welche Phase gilt.
_PHASE_BOUNDARIES: list[tuple[int, DayPhase]] = [
    (0, DayPhase.NIGHT),
    (5, DayPhase.EARLY_MORNING),
    (8, DayPhase.MORNING),
    (12, DayPhase.MIDDAY),
    (14, DayPhase.AFTERNOON),
    (18, DayPhase.EVENING),
    (22, DayPhase.LATE_EVENING),
]


@dataclass
class RhythmState:
    """Die Einschätzung zum jetzigen Zeitpunkt."""

    phase: DayPhase
    hour: int
    #: Wie viel Tatendrang angemessen ist (0.0 bis 1.0).
    energy: float
    #: Wie hell der Orb sein darf (0.0 bis 1.0).
    brightness: float
    #: Ob eine Begrüßung angebracht wäre.
    should_greet: bool
    #: Ob der Benutzer zu dieser Stunde üblicherweise da ist.
    is_usual_time: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "description": self.phase.description(),
            "hour": self.hour,
            "energy": round(self.energy, 3),
            "brightness": round(self.brightness, 3),
            "should_greet": self.should_greet,
            "is_usual_time": self.is_usual_time,
            "greeting": self.phase.greeting(),
        }


class DailyRhythm:
    """Bewertet die Tageszeit."""

    def __init__(
        self,
        *,
        quiet_hours: tuple[int, int] = (22, 7),
        night_brightness: float = 0.55,
        greeting_gap_hours: float = 6.0,
    ) -> None:
        """
        Args:
            quiet_hours: Von wann bis wann es gedämpft zugeht. Der Zeitraum
                darf über Mitternacht reichen.
            night_brightness: Wie hell der Orb in der Ruhezeit höchstens ist.
            greeting_gap_hours: Nach wie vielen Stunden ohne Kontakt wieder
                begrüßt wird.
        """

        self._quiet_from, self._quiet_to = quiet_hours
        self._night_brightness = max(0.1, min(1.0, night_brightness))
        self._greeting_gap = max(0.5, greeting_gap_hours) * 3600.0

        self._last_greeting = 0.0
        #: Stunden, zu denen der Benutzer schon aktiv war.
        self._observed_hours: dict[int, int] = {}

    # --- Beobachtung ---------------------------------------------------------------

    def observe_activity(self, at: float | None = None) -> None:
        """Hält fest, dass der Benutzer gerade da war."""

        hour = datetime.fromtimestamp(at or time.time()).hour
        self._observed_hours[hour] = self._observed_hours.get(hour, 0) + 1

    def set_observed_hours(self, hours: dict[int, int]) -> None:
        """Übernimmt Beobachtungen aus dem Verhaltensspeicher."""

        self._observed_hours = dict(hours)

    def is_usual_time(self, hour: int | None = None) -> bool:
        """Ob der Benutzer zu dieser Stunde üblicherweise arbeitet.

        Maßstab ist die Hälfte der durchschnittlichen Stundenaktivität – so
        gilt eine Stunde als üblich, wenn sie nicht deutlich unter dem
        Üblichen liegt, und nicht erst, wenn sie die häufigste ist.
        """

        if not self._observed_hours:
            return False

        current = self._observed_hours.get(hour if hour is not None else datetime.now().hour, 0)
        average = sum(self._observed_hours.values()) / len(self._observed_hours)
        return current >= average * 0.5

    # --- Bewertung -------------------------------------------------------------------

    @staticmethod
    def phase_at(hour: int) -> DayPhase:
        """Die Tagesphase zu einer Stunde."""

        current = DayPhase.NIGHT
        for boundary, phase in _PHASE_BOUNDARIES:
            if hour >= boundary:
                current = phase
        return current

    def is_quiet_hour(self, hour: int | None = None) -> bool:
        """Ob gerade Ruhezeit ist."""

        current = hour if hour is not None else datetime.now().hour
        if self._quiet_from <= self._quiet_to:
            return self._quiet_from <= current < self._quiet_to
        # Der Zeitraum reicht über Mitternacht.
        return current >= self._quiet_from or current < self._quiet_to

    def current(self) -> RhythmState:
        """Die Einschätzung für jetzt."""

        now = datetime.now()
        hour = now.hour
        phase = self.phase_at(hour)
        quiet = self.is_quiet_hour(hour)
        usual = self.is_usual_time(hour)

        energy = {
            DayPhase.NIGHT: 0.25,
            DayPhase.EARLY_MORNING: 0.55,
            DayPhase.MORNING: 0.95,
            DayPhase.MIDDAY: 0.7,
            DayPhase.AFTERNOON: 0.85,
            DayPhase.EVENING: 0.6,
            DayPhase.LATE_EVENING: 0.4,
        }[phase]

        # Wer regelmäßig zu dieser Stunde arbeitet, bekommt keinen müden Orb.
        if usual:
            energy = min(1.0, energy + 0.2)

        brightness = self._night_brightness if quiet and not usual else 1.0

        elapsed = time.time() - self._last_greeting
        should_greet = elapsed > self._greeting_gap

        return RhythmState(
            phase=phase,
            hour=hour,
            energy=energy,
            brightness=brightness,
            should_greet=should_greet,
            is_usual_time=usual,
        )

    def greet(self) -> str:
        """Gibt eine Begrüßung zurück und merkt sich den Zeitpunkt."""

        state = self.current()
        self._last_greeting = time.time()
        return state.phase.greeting()

    def note_contact(self) -> None:
        """Hält fest, dass gerade Kontakt bestand – ohne zu begrüßen."""

        self._last_greeting = time.time()
        self.observe_activity()

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        state = self.current()
        return {
            **state.to_dict(),
            "quiet_hours": [self._quiet_from, self._quiet_to],
            "in_quiet_hours": self.is_quiet_hour(),
            "observed_hours": dict(sorted(self._observed_hours.items())),
        }
