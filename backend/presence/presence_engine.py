"""Presence Engine – der Orb als Gegenüber (v2 Phasen 21, 22 und 24).

Führt Stimmung, Tagesrhythmus und Persönlichkeit zusammen und beantwortet
damit drei Fragen, die im laufenden Betrieb ständig anfallen:

* Wie soll der Orb gerade **aussehen**? (Helligkeit, Tempo, Größe)
* Wie soll er **klingen**? (Gefühlslage, Sprechgeschwindigkeit)
* Was soll im **Systemprompt** stehen? (Ton, Zusammenhang, Gelerntes)

Dazu kommt eine vierte, heiklere: Wann darf der Orb **von sich aus** etwas
sagen? Die Antwort ist bewusst streng. Ein Assistent, der ungefragt
dazwischenredet, wird nach zwei Tagen ausgeschaltet. Deshalb gilt: von sich
aus höchstens einmal je Zeitfenster, nie in der Ruhezeit, nie während einer
Vollbildanwendung, und nur wenn es tatsächlich etwas zu sagen gibt.

Der Zustand hier ist flüchtig, mit einer Ausnahme: Die Stunden, zu denen der
Benutzer aktiv war, kommen aus dem Verhaltensspeicher und überdauern damit
einen Neustart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import get_config
from backend.presence.daily_rhythm import DailyRhythm, RhythmState
from backend.presence.emotional_state import EmotionalState, Mood
from backend.presence.personality import Personality
from backend.system.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class ProactiveMessage:
    """Ein Hinweis, den der Orb von sich aus geben möchte."""

    text: str
    #: Wie dringend – bestimmt, ob gesprochen oder nur angezeigt wird.
    urgency: str = "normal"
    reason: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "urgency": self.urgency,
            "reason": self.reason,
            "created_at": self.created_at,
        }


class PresenceEngine:
    """Bündelt Stimmung, Rhythmus und Persönlichkeit."""

    def __init__(self, *, behavior_engine: Any | None = None, learner: Any | None = None) -> None:
        """
        Args:
            behavior_engine: Liefert die beobachteten Arbeitszeiten.
            learner: Liefert, was über den Benutzer gelernt wurde.
        """

        config = get_config()

        self._behavior = behavior_engine
        self._learner = learner

        self.personality = Personality(config.get("personality", {}) or {})

        self.emotions = EmotionalState(
            baseline_valence=float(config.get("presence.baseline_valence", 0.15)),
            baseline_arousal=float(config.get("presence.baseline_arousal", 0.3)),
            intensity=float(config.get("presence.emotion_intensity", 1.0)),
        )

        quiet = config.get("presence.quiet_hours", [22, 7]) or [22, 7]
        self.rhythm = DailyRhythm(
            quiet_hours=(int(quiet[0]), int(quiet[1])),
            night_brightness=float(config.get("presence.night_brightness", 0.55)),
            greeting_gap_hours=float(config.get("presence.greeting_gap_hours", 6.0)),
        )

        self._proactive_enabled = bool(config.get("presence.proactive_enabled", False))
        self._proactive_gap = float(config.get("presence.proactive_gap_minutes", 45)) * 60.0
        self._last_proactive = 0.0
        self._suppressed_until = 0.0
        self._pending: list[ProactiveMessage] = []

        self._load_observed_hours()

    def _load_observed_hours(self) -> None:
        """Übernimmt die beobachteten Arbeitszeiten aus dem Verhaltensspeicher."""

        if self._behavior is None:
            return
        try:
            snapshot = self._behavior.snapshot()
            hours = snapshot.get("working_hours", {}) or {}
            self.rhythm.set_observed_hours(
                {int(hour): int(count) for hour, count in hours.items() if str(hour).isdigit()}
            )
        except Exception:  # noqa: BLE001 - ohne Beobachtungen läuft es auch.
            logger.debug("Arbeitszeiten ließen sich nicht laden.", exc_info=True)

    # --- Ereignisse -----------------------------------------------------------------

    def on_interaction(self, *, succeeded: bool = True, woke: bool = False) -> Mood:
        """Meldet einen Austausch mit dem Benutzer."""

        self.rhythm.note_contact()
        if woke:
            self.emotions.register("angesprochen")
        return self.emotions.register(
            "frage_beantwortet" if succeeded else "fehler"
        )

    def on_task_completed(self) -> Mood:
        """Meldet eine abgeschlossene Aufgabe."""

        return self.emotions.register("aufgabe_erledigt")

    def on_error(self, *, severe: bool = False) -> Mood:
        """Meldet einen Fehler."""

        return self.emotions.register("fehler", strength=1.5 if severe else 1.0)

    def on_misunderstanding(self) -> Mood:
        """Meldet, dass etwas falsch verstanden wurde."""

        return self.emotions.register("missverstanden")

    def on_feedback(self, helpful: bool) -> Mood:
        """Meldet eine Rückmeldung des Benutzers."""

        return self.emotions.register("lob" if helpful else "missverstanden")

    def on_idle(self, minutes: float) -> Mood:
        """Meldet eine längere Ruhephase."""

        if minutes >= 20:
            return self.emotions.register("lange_still", strength=min(2.0, minutes / 30.0))
        return self.emotions.current()

    # --- Darstellung ------------------------------------------------------------------

    def visual_state(self) -> dict[str, Any]:
        """Wie der Orb gerade aussehen soll.

        Die Werte sind Faktoren auf die Grundeinstellung aus ``config.yaml``,
        keine absoluten Angaben. Die Darstellung bleibt Herrin über ihre
        eigenen Grenzen.
        """

        visual = self.emotions.visual_hint()
        rhythm = self.rhythm.current()

        return {
            "brightness": round(visual["brightness"] * rhythm.brightness, 3),
            "speed": round(visual["speed"] * (0.7 + rhythm.energy * 0.45), 3),
            "particle_intensity": round(visual["particle_intensity"] * rhythm.brightness, 3),
            "scale": visual["scale"],
            "mood": self.emotions.current().label(),
            "phase": rhythm.phase.value,
            "quiet": self.rhythm.is_quiet_hour(),
        }

    def speech_settings(self) -> dict[str, Any]:
        """Wie der Orb gerade klingen soll."""

        speech = self.emotions.speech_hint()
        rhythm = self.rhythm.current()

        # Nachts leiser und etwas langsamer.
        volume = 0.75 if self.rhythm.is_quiet_hour() and not rhythm.is_usual_time else 1.0

        return {
            "emotion": speech["emotion"],
            "speed": round(speech["speed"] * (0.92 + rhythm.energy * 0.12), 3),
            "volume": volume,
        }

    # --- Systemprompt --------------------------------------------------------------------

    def system_prompt(self, base: str = "") -> str:
        """Baut den Systemprompt für die nächste Anfrage."""

        mood = self.emotions.current()
        rhythm = self.rhythm.current()

        rhythm_hint = ""
        if self.rhythm.is_quiet_hour() and not rhythm.is_usual_time:
            rhythm_hint = (
                f"Es ist {rhythm.hour} Uhr – späte Stunde. Halte dich kürzer als "
                "sonst und dränge dich nicht auf."
            )

        learned = ""
        if self._learner is not None:
            try:
                learned = self._learner.guidance()
            except Exception:  # noqa: BLE001
                logger.debug("Gelerntes ließ sich nicht abrufen.", exc_info=True)

        return self.personality.system_prompt(
            base=base,
            mood=mood.label(),
            rhythm=rhythm_hint,
            learned=learned,
        )

    def greeting(self) -> str:
        """Eine Begrüßung, falls jetzt eine angebracht ist.

        Leer, wenn nicht – die Stelle, die das aufruft, muss nicht selbst
        entscheiden, wann eine Begrüßung passt.
        """

        state = self.rhythm.current()
        if not state.should_greet:
            return ""
        return self.personality.greeting_style(self.rhythm.greet())

    def acknowledgment(self) -> str:
        """Was der Orb sagt, wenn er geweckt wird."""

        return self.personality.acknowledgment()

    # --- Von sich aus sprechen -----------------------------------------------------------

    def suggest(self, text: str, *, urgency: str = "normal", reason: str = "") -> bool:
        """Meldet einen Hinweis an, den der Orb von sich aus geben möchte.

        Returns:
            ``True``, wenn er angenommen wurde. ``False`` heißt: gerade nicht.
        """

        if not self._proactive_enabled:
            return False
        if not text.strip():
            return False

        self._pending.append(ProactiveMessage(text=text.strip(), urgency=urgency, reason=reason))
        self._pending = self._pending[-10:]
        return True

    def may_speak_unprompted(self) -> tuple[bool, str]:
        """Ob der Orb jetzt ungefragt sprechen darf.

        Returns:
            Die Entscheidung und ihre Begründung im Klartext.
        """

        if not self._proactive_enabled:
            return False, "Von sich aus zu sprechen ist in config.yaml ausgeschaltet."

        now = time.time()

        if now < self._suppressed_until:
            remaining = (self._suppressed_until - now) / 60.0
            return False, f"Der Benutzer hat um Ruhe gebeten (noch {remaining:.0f} Minuten)."

        rhythm = self.rhythm.current()
        if self.rhythm.is_quiet_hour() and not rhythm.is_usual_time:
            return False, "Es ist Ruhezeit."

        if now - self._last_proactive < self._proactive_gap:
            waited = (now - self._last_proactive) / 60.0
            return False, (
                f"Zuletzt vor {waited:.0f} Minuten – es wird höchstens alle "
                f"{self._proactive_gap / 60.0:.0f} Minuten von sich aus gesprochen."
            )

        if not self._pending:
            return False, "Es gibt nichts zu sagen."

        return True, "Es gibt einen Hinweis und der Zeitpunkt passt."

    def take_message(self) -> ProactiveMessage | None:
        """Holt den nächsten Hinweis ab, falls jetzt einer gegeben werden darf."""

        allowed, _ = self.may_speak_unprompted()
        if not allowed:
            return None

        message = self._pending.pop(0)
        self._last_proactive = time.time()
        return message

    def suppress(self, minutes: float = 60.0) -> None:
        """Bittet den Orb, eine Weile zu schweigen."""

        self._suppressed_until = time.time() + max(1.0, minutes) * 60.0
        self._pending.clear()
        logger.info("Der Orb schweigt für %.0f Minuten.", minutes)

    def resume(self) -> None:
        """Hebt das Schweigen auf."""

        self._suppressed_until = 0.0

    @property
    def is_suppressed(self) -> bool:
        """Ob der Benutzer gerade ausdrücklich um Ruhe gebeten hat.

        Getrennt von :meth:`may_speak_unprompted` und mit Absicht schmaler:
        Dort spielt auch der Mindestabstand zwischen zwei Hinweisen hinein,
        und der darf eine Terminerinnerung nicht verschlucken. "In zehn
        Minuten beginnt dein Termin" ist eine halbe Stunde später falsch,
        nicht nur verspätet.
        """

        return time.time() < self._suppressed_until

    # --- Auskunft ---------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Der gesamte Präsenzzustand."""

        allowed, reason = self.may_speak_unprompted()
        return {
            "mood": self.emotions.current().to_dict(),
            "rhythm": self.rhythm.current().to_dict(),
            "personality": self.personality.status(),
            "visual": self.visual_state(),
            "speech": self.speech_settings(),
            "proactive": {
                "enabled": self._proactive_enabled,
                "allowed_now": allowed,
                "reason": reason,
                "pending": len(self._pending),
                "suppressed_until": self._suppressed_until,
            },
        }

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return self.snapshot()
