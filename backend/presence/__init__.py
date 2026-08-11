"""Präsenz des Orb (v2 Phasen 21, 22 und 24).

Macht aus einem Programm ein Gegenüber: eine Stimmung, die sich verändert,
ein Tagesrhythmus, der die Tageszeit berücksichtigt, und eine Persönlichkeit,
die den Ton setzt.

Eine Grenze wird dabei ausdrücklich gezogen: Der Orb gibt sich nicht als
Mensch aus und behauptet keine Gefühle, die er nicht hat. Die Stimmung färbt
Darstellung und Wortwahl – sie ist keine Aussage über ein Innenleben.
"""

from backend.presence.daily_rhythm import DailyRhythm, DayPhase, RhythmState
from backend.presence.emotional_state import MOOD_EVENTS, EmotionalState, Mood, MoodEvent
from backend.presence.personality import INVARIANTS, TRAIT_DEFINITIONS, Personality, Trait
from backend.presence.presence_engine import PresenceEngine, ProactiveMessage

__all__ = [
    "INVARIANTS",
    "MOOD_EVENTS",
    "TRAIT_DEFINITIONS",
    "DailyRhythm",
    "DayPhase",
    "EmotionalState",
    "Mood",
    "MoodEvent",
    "Personality",
    "PresenceEngine",
    "ProactiveMessage",
    "RhythmState",
    "Trait",
]
