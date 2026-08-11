"""Gefühlszustand des Orb (v2 Phase 22).

Ein Assistent, der immer gleich klingt und immer gleich aussieht, wirkt wie
ein Formular. Dieses Modul gibt dem Orb eine Stimmung, die sich verändert –
langsam, nachvollziehbar und mit einer Rückkehr zur Mitte.

Die Stimmung wird über zwei Größen beschrieben, wie es in der
Emotionsforschung üblich ist:

* **Tönung** (von -1 unangenehm bis +1 angenehm): Ist gerade etwas gelungen
  oder schiefgegangen?
* **Erregung** (von 0 ruhig bis 1 aufgedreht): Wie viel ist los?

Aus diesen beiden ergibt sich alles Weitere: die Farbe des Orb, die
Sprechgeschwindigkeit, die Wahl der Worte.

Zwei Vorkehrungen halten das seriös. Erstens **kehrt die Stimmung zurück**:
Ohne neue Ereignisse nähert sie sich stetig wieder der Mitte, sodass ein
Ärgernis von gestern das Verhalten von heute nicht mehr färbt. Zweitens ist
sie **gedeckelt**: Der Orb wird weder euphorisch noch niedergeschlagen. Ein
Programm, das Kummer vortäuscht, wäre eine Zumutung – es geht um eine
lebendige Anmutung, nicht um vorgespielte Gefühle.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

#: Obergrenzen. Die Stimmung bleibt in einem gemäßigten Bereich.
MAX_VALENCE = 0.75
MIN_VALENCE = -0.6
MAX_AROUSAL = 0.9
MIN_AROUSAL = 0.05

#: Nach wie vielen Sekunden die Hälfte einer Auslenkung abgeklungen ist.
VALENCE_HALF_LIFE = 900.0
AROUSAL_HALF_LIFE = 300.0

#: Ruhelage, zu der zurückgekehrt wird.
BASELINE_VALENCE = 0.15
BASELINE_AROUSAL = 0.3


@dataclass
class MoodEvent:
    """Ein Ereignis, das auf die Stimmung wirkt."""

    name: str
    valence: float
    arousal: float
    description: str = ""


#: Was die Stimmung bewegt. Die Werte sind klein gehalten – eine einzelne
#: gelungene Antwort soll den Orb nicht in Begeisterung versetzen.
MOOD_EVENTS: dict[str, MoodEvent] = {
    event.name: event
    for event in (
        MoodEvent("frage_beantwortet", 0.08, 0.15, "Eine Frage wurde beantwortet"),
        MoodEvent("aufgabe_erledigt", 0.18, 0.20, "Eine Aufgabe wurde abgeschlossen"),
        MoodEvent("lob", 0.30, 0.25, "Der Benutzer war zufrieden"),
        MoodEvent("fehler", -0.22, 0.30, "Etwas ist schiefgegangen"),
        MoodEvent("missverstanden", -0.12, 0.20, "Etwas wurde falsch verstanden"),
        MoodEvent("abgelehnt", -0.08, 0.10, "Eine Anfrage wurde abgelehnt"),
        MoodEvent("angesprochen", 0.10, 0.35, "Der Benutzer hat den Orb geweckt"),
        MoodEvent("lange_still", -0.02, -0.25, "Es war lange nichts los"),
        MoodEvent("viel_los", 0.05, 0.30, "Es wird viel gearbeitet"),
    )
}


@dataclass
class Mood:
    """Die aktuelle Stimmung."""

    valence: float = BASELINE_VALENCE
    arousal: float = BASELINE_AROUSAL
    updated_at: float = field(default_factory=time.time)

    def label(self) -> str:
        """Ein Wort für die Stimmung, für Anzeige und Sprachausgabe."""

        if self.valence < -0.25:
            return "zerknirscht" if self.arousal < 0.45 else "angespannt"
        if self.valence > 0.4:
            return "aufgeräumt" if self.arousal > 0.45 else "zufrieden"
        if self.arousal > 0.6:
            return "wach"
        if self.arousal < 0.2:
            return "ruhig"
        return "gelassen"

    def to_emotion(self) -> str:
        """Die passende Gefühlslage für die Sprachausgabe.

        Die Namen entsprechen denen in :mod:`backend.tts.emotion`.
        """

        if self.valence < -0.25:
            return "bedauernd"
        if self.valence > 0.4 and self.arousal > 0.45:
            return "erfreut"
        if self.arousal > 0.6:
            return "dringlich" if self.valence < 0 else "freundlich"
        if self.arousal < 0.2:
            return "leise"
        return "freundlich" if self.valence > 0.1 else "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "label": self.label(),
            "emotion": self.to_emotion(),
            "updated_at": self.updated_at,
        }


class EmotionalState:
    """Führt die Stimmung des Orb nach."""

    def __init__(
        self,
        *,
        baseline_valence: float = BASELINE_VALENCE,
        baseline_arousal: float = BASELINE_AROUSAL,
        intensity: float = 1.0,
    ) -> None:
        """
        Args:
            baseline_valence: Die Ruhelage der Tönung.
            baseline_arousal: Die Ruhelage der Erregung.
            intensity: Faktor auf alle Ausschläge. 0 schaltet die Stimmung
                praktisch ab, ohne dass etwas anderes umgebaut werden müsste.
        """

        self._baseline_valence = baseline_valence
        self._baseline_arousal = baseline_arousal
        self._intensity = max(0.0, min(2.0, intensity))

        self._valence = baseline_valence
        self._arousal = baseline_arousal
        self._last_update = time.time()
        self._recent: list[tuple[float, str]] = []

    # --- Nachführen -----------------------------------------------------------------

    def _decay(self) -> None:
        """Lässt die Stimmung zur Ruhelage zurückkehren.

        Der Abfall ist exponentiell, wie beim Abklingen eines Reizes: Am
        Anfang geht es schnell, dann immer langsamer. Das fühlt sich
        natürlicher an als ein gleichmäßiges Zurücklaufen.
        """

        now = time.time()
        elapsed = max(0.0, now - self._last_update)
        self._last_update = now

        if elapsed <= 0.0:
            return

        valence_factor = math.pow(0.5, elapsed / VALENCE_HALF_LIFE)
        arousal_factor = math.pow(0.5, elapsed / AROUSAL_HALF_LIFE)

        self._valence = self._baseline_valence + (self._valence - self._baseline_valence) * valence_factor
        self._arousal = self._baseline_arousal + (self._arousal - self._baseline_arousal) * arousal_factor

    def register(self, event_name: str, *, strength: float = 1.0) -> Mood:
        """Verarbeitet ein Ereignis.

        Args:
            event_name: Einer der Namen aus :data:`MOOD_EVENTS`.
            strength: Faktor auf die Wirkung.

        Returns:
            Die Stimmung danach.
        """

        self._decay()

        event = MOOD_EVENTS.get(event_name)
        if event is not None:
            factor = self._intensity * max(0.0, min(3.0, strength))
            self._valence += event.valence * factor
            self._arousal += event.arousal * factor
            self._clamp()

            self._recent.append((time.time(), event_name))
            self._recent = self._recent[-40:]

        return self.current()

    def _clamp(self) -> None:
        self._valence = max(MIN_VALENCE, min(MAX_VALENCE, self._valence))
        self._arousal = max(MIN_AROUSAL, min(MAX_AROUSAL, self._arousal))

    def current(self) -> Mood:
        """Die Stimmung jetzt."""

        self._decay()
        return Mood(valence=self._valence, arousal=self._arousal, updated_at=self._last_update)

    def reset(self) -> Mood:
        """Setzt auf die Ruhelage zurück."""

        self._valence = self._baseline_valence
        self._arousal = self._baseline_arousal
        self._last_update = time.time()
        self._recent.clear()
        return self.current()

    # --- Wirkung nach außen -------------------------------------------------------------

    def visual_hint(self) -> dict[str, float]:
        """Wie sich die Stimmung auf die Darstellung auswirkt.

        Die Werte sind Faktoren, keine absoluten Größen – die Darstellung
        entscheidet selbst, wie stark sie darauf eingeht.
        """

        mood = self.current()
        return {
            # Bei guter Stimmung etwas heller.
            "brightness": round(1.0 + mood.valence * 0.18, 3),
            # Bei Erregung schneller.
            "speed": round(0.85 + mood.arousal * 0.5, 3),
            # Bei Erregung mehr Partikel.
            "particle_intensity": round(0.4 + mood.arousal * 0.5, 3),
            # Bei schlechter Stimmung leicht zusammengezogen.
            "scale": round(1.0 + mood.valence * 0.06, 3),
        }

    def speech_hint(self) -> dict[str, Any]:
        """Wie sich die Stimmung auf die Sprachausgabe auswirkt."""

        mood = self.current()
        return {
            "emotion": mood.to_emotion(),
            "speed": round(0.95 + mood.arousal * 0.15, 3),
        }

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Die jüngsten Ereignisse, für die Transparenzansicht."""

        return [
            {
                "event": name,
                "description": MOOD_EVENTS[name].description if name in MOOD_EVENTS else "",
                "at": at,
            }
            for at, name in self._recent[-limit:]
        ][::-1]

    def status(self) -> dict[str, Any]:
        """Statusangaben."""

        mood = self.current()
        return {
            "mood": mood.to_dict(),
            "intensity": self._intensity,
            "baseline": {
                "valence": self._baseline_valence,
                "arousal": self._baseline_arousal,
            },
            "visual": self.visual_hint(),
            "speech": self.speech_hint(),
            "recent": self.recent_events(5),
        }
