"""Gefühlslage der Sprachausgabe (v2 Phase 13).

Eine Stimme, die jeden Satz gleich betont, wirkt nach wenigen Minuten
mechanisch. Dieses Modul bildet deshalb einen kleinen Satz Gefühlslagen ab
und übersetzt sie in die drei Größen, die ein Sprachmodell versteht:
Geschwindigkeit, Tonhöhe und Lautstärke.

Bewusst zurückhaltend gehalten. Ein Assistent, der übertrieben fröhlich oder
betroffen klingt, wirkt aufdringlich; die Werte weichen deshalb selten mehr
als fünfzehn Prozent vom Normalen ab. Der Unterschied ist hörbar, ohne
aufzufallen.

Die Gefühlslage wird nicht geraten, sondern aus dem Zustand des Orb und aus
eindeutigen Merkmalen des Textes abgeleitet – eine Frage klingt anders als
eine Fehlermeldung.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmotionProfile:
    """Wie eine Gefühlslage klingt."""

    name: str
    #: Beschreibung für die Transparenzansicht.
    description: str
    #: Faktor auf die Sprechgeschwindigkeit.
    speed: float = 1.0
    #: Verschiebung der Tonhöhe in Halbtönen.
    pitch: float = 0.0
    #: Faktor auf die Lautstärke.
    volume: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "speed": self.speed,
            "pitch": self.pitch,
            "volume": self.volume,
        }


#: Die verfügbaren Gefühlslagen.
EMOTIONS: dict[str, EmotionProfile] = {
    profile.name: profile
    for profile in (
        EmotionProfile("neutral", "Sachlich, der Normalfall"),
        EmotionProfile("freundlich", "Zugewandt, etwas wärmer", speed=1.02, pitch=0.5),
        EmotionProfile("aufmerksam", "Wach und zugewandt, beim Zuhören", speed=1.0, pitch=0.3),
        EmotionProfile("nachdenklich", "Langsamer, mit mehr Ruhe", speed=0.9, pitch=-0.4),
        EmotionProfile("erfreut", "Spürbar aufgeräumt", speed=1.08, pitch=1.0, volume=1.05),
        EmotionProfile("bedauernd", "Zurückhaltend, bei einem Fehler", speed=0.92, pitch=-0.8, volume=0.95),
        EmotionProfile("dringlich", "Deutlich und schnell, bei Warnungen", speed=1.12, pitch=0.6, volume=1.08),
        EmotionProfile("leise", "Gedämpft, in Ruhephasen", speed=0.95, pitch=-0.2, volume=0.7),
    )
}

#: Wortstämme, die auf eine Gefühlslage hindeuten. Bewusst kurz gehalten:
#: Je mehr Regeln, desto häufiger greift eine davon daneben.
_TEXT_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(fehler|fehlgeschlagen|leider|konnte nicht|nicht möglich)\b", re.I), "bedauernd"),
    (re.compile(r"\b(achtung|warnung|vorsicht|dringend|sofort)\b", re.I), "dringlich"),
    (re.compile(r"\b(fertig|erledigt|geschafft|erfolgreich|gerne)\b", re.I), "erfreut"),
    (re.compile(r"\b(vermutlich|möglicherweise|ich denke|unsicher|schätze)\b", re.I), "nachdenklich"),
]

#: Welche Gefühlslage zu welchem Orb-Zustand passt.
_STATE_EMOTIONS: dict[str, str] = {
    "idle": "neutral",
    "listening": "aufmerksam",
    "thinking": "nachdenklich",
    "speaking": "freundlich",
    "busy": "neutral",
    "error": "bedauernd",
    "sleep": "leise",
}


def get_emotion(name: str) -> EmotionProfile:
    """Sucht eine Gefühlslage; unbekannte ergeben ``neutral``."""

    return EMOTIONS.get(name.strip().lower(), EMOTIONS["neutral"])


def for_state(state: str) -> EmotionProfile:
    """Die Gefühlslage, die zu einem Orb-Zustand gehört."""

    return get_emotion(_STATE_EMOTIONS.get(state.strip().lower(), "neutral"))


def detect(text: str, *, state: str = "", default: str = "neutral") -> EmotionProfile:
    """Leitet die Gefühlslage aus Text und Zustand ab.

    Die Regel: Ein eindeutiges Merkmal im Text schlägt den Zustand, denn
    eine Fehlermeldung soll auch dann bedauernd klingen, wenn der Orb sonst
    gerade munter ist. Findet sich nichts, gilt der Zustand, und sonst die
    Vorgabe.

    Args:
        text: Der zu sprechende Text.
        state: Der aktuelle Zustand des Orb.
        default: Was gilt, wenn nichts zutrifft.

    Returns:
        Die passende Gefühlslage.
    """

    stripped = text.strip()

    for pattern, emotion in _TEXT_HINTS:
        if pattern.search(stripped):
            return get_emotion(emotion)

    if state:
        return for_state(state)

    return get_emotion(default)


def catalog() -> list[dict[str, Any]]:
    """Alle Gefühlslagen für die Transparenzansicht."""

    return [profile.to_dict() for profile in EMOTIONS.values()]
