"""Verwaltung der Sprachausgabe.

Der Manager wählt aus den in ``config.yaml`` eingetragenen Verfahren das
erste, das auf diesem Rechner tatsächlich arbeitet, und weicht bei einem
Fehler auf das nächste aus. Damit gilt: **Solange irgendein Verfahren
verfügbar ist, spricht AI-Orb.** Ein fehlendes Modell oder eine abgerissene
Netzverbindung führt nicht zum Verstummen.

Zwei Dinge sind hier wichtig.

Erstens der **Zwischenspeicher**: Sätze wie „Ich bin da" oder „Einen
Moment" spricht der Orb oft. Sie jedes Mal neu zu erzeugen kostet Zeit und
Strom. Das Ergebnis wird deshalb unter einem Namen abgelegt, der sich aus
Text, Stimme und Geschwindigkeit ergibt.

Zweitens die **Aufteilung langer Texte**: Ein Sprachmodell wird bei sehr
langen Eingaben ungenau, und die erste Silbe soll früh kommen. Lange
Antworten werden deshalb an Satzgrenzen zerlegt, sodass die Wiedergabe
beginnen kann, während der Rest noch entsteht.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from backend.config import get_config
from backend.system.logging_setup import get_logger
from backend.tts import emotion as emotion_module
from backend.tts.base_engine import SpeechRequest, SpeechResult, TtsEngine
from backend.tts.elevenlabs_engine import ElevenLabsEngine
from backend.tts.kokoro_engine import KokoroEngine
from backend.tts.piper_engine import PiperEngine
from backend.tts.remote_tts_engine import RemoteTtsEngine
from backend.tts.sapi_engine import SapiEngine
from backend.tts.speechgen_engine import SpeechGenEngine
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: Die bekannten Verfahren.
ENGINE_CLASSES: dict[str, type[TtsEngine]] = {
    "piper": PiperEngine,
    "sapi": SapiEngine,
    "kokoro": KokoroEngine,
    "elevenlabs": ElevenLabsEngine,
    "speechgen": SpeechGenEngine,
    "remote": RemoteTtsEngine,
}

# Nur diese Verfahren erzeugen Sprache vollstaendig auf dem Rechner.
# Im Offlinebetrieb werden alle anderen vor jeder Verfuegbarkeitspruefung
# ausgefiltert, damit nicht einmal ein Probeaufruf die Cloud beruehrt.
LOCAL_ENGINE_NAMES: frozenset[str] = frozenset({"piper", "sapi", "kokoro"})

#: Satzenden, an denen ein langer Text zerlegt werden darf.
_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+")

#: Zeichen, die gesprochen störend wirken (Aufzählungspunkte, Auszeichnung).
_SPOKEN_NOISE = re.compile(r"[*_`#>|]+")

#: Ein Codeblock wird nicht vorgelesen, sondern angekündigt.
_CODE_BLOCK = re.compile(r"```[\s\S]*?```")


class TtsManager:
    """Wählt ein Sprachausgabe-Verfahren und erzeugt damit Sprache."""

    def __init__(self) -> None:
        config = get_config()

        self._enabled = bool(config.get("voice.output.enabled", True))
        self._cache_enabled = bool(config.get("voice.output.cache_enabled", True))
        self._max_characters = int(config.get("voice.output.max_characters", 1200))
        self._configured_speed = float(config.get("voice.output.speed", 1.0))
        self._base_speed = self._configured_speed
        self._base_volume = float(config.get("voice.output.volume", 1.0))
        self._stable_volume = bool(config.get("voice.output.stable_volume", True))
        self._emotions_enabled = bool(config.get("voice.output.emotions_enabled", True))

        self._output_directory = get_data_dir() / "tts"
        self._output_directory.mkdir(parents=True, exist_ok=True)

        requested: list[str] = [
            str(name).strip().lower()
            for name in (config.get("voice.output.engines", ["piper", "sapi", "kokoro"]) or [])
        ]

        self._engines: list[TtsEngine] = []
        for name in requested:
            engine_class = ENGINE_CLASSES.get(name)
            if engine_class is None:
                logger.warning(
                    "Das Sprachausgabe-Verfahren '%s' ist unbekannt und wird "
                    "übergangen. Bekannt sind: %s",
                    name,
                    ", ".join(sorted(ENGINE_CLASSES)),
                )
                continue
            options = config.get(f"voice.output.{name}", {}) or {}
            self._engines.append(
                engine_class(output_directory=self._output_directory, options=options)
            )

        self._active: TtsEngine | None = None
        self._last_result: SpeechResult | None = None
        self._spoken_count = 0
        self._offline_mode = False

    # --- Verfahrenswahl -------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Ob die Sprachausgabe eingeschaltet ist."""

        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Schaltet die Sprachausgabe ein oder aus."""

        self._enabled = enabled
        logger.info("Sprachausgabe %s.", "eingeschaltet" if enabled else "ausgeschaltet")

    def set_offline_mode(self, enabled: bool) -> None:
        """Erzwingt lokale Sprachausgabe ohne Netzwerkverfahren."""

        self._offline_mode = bool(enabled)
        if self._offline_mode and self._active is not None:
            if self._active.name not in LOCAL_ENGINE_NAMES:
                self._active = None
        logger.info(
            "Sprachausgabe arbeitet %s.",
            "ausschliesslich lokal" if self._offline_mode else "wieder im Automatikbetrieb",
        )

    @property
    def base_speed(self) -> float:
        return self._configured_speed

    def set_rhythm_speed(self, factor: float) -> None:
        """Passt nur das Tempo moderat an, niemals Stimme oder Klangfarbe."""

        self._base_speed = max(
            0.75, min(1.15, self._configured_speed * float(factor))
        )

    @property
    def active_name(self) -> str:
        """Das zuletzt benutzte Verfahren."""

        return self._active.name if self._active is not None else ""

    def available_engines(self) -> list[TtsEngine]:
        """Die Verfahren, die auf diesem Rechner arbeiten können."""

        return [engine for engine in self._eligible_engines() if engine.is_available()]

    def _eligible_engines(self) -> list[TtsEngine]:
        if not self._offline_mode:
            return list(self._engines)
        return [engine for engine in self._engines if engine.name in LOCAL_ENGINE_NAMES]

    def diagnose(self) -> str:
        """Erklärt im Klartext, warum gesprochen wird oder nicht."""

        eligible = self._eligible_engines()
        if not eligible:
            if self._offline_mode:
                return (
                    "Im Offlinebetrieb ist keine lokale Stimme konfiguriert. "
                    "Trage piper, sapi oder kokoro unter 'voice.output.engines' ein."
                )
            return (
                "Es ist kein Sprachausgabe-Verfahren eingetragen. Trage unter "
                "'voice.output.engines' in config.yaml mindestens eines ein."
            )

        available = self.available_engines()
        if available:
            names = ", ".join(engine.name for engine in available)
            return f"Sprachausgabe bereit über: {names}."

        lines = ["Kein Sprachausgabe-Verfahren ist einsatzbereit:"]
        for engine in eligible:
            lines.append(f"  {engine.name}: {engine.installation_hint()}")
        return "\n".join(lines)

    # --- Textaufbereitung -------------------------------------------------------------

    @staticmethod
    def prepare_text(text: str) -> str:
        """Bereitet Text so auf, dass er gesprochen sinnvoll klingt.

        Auszeichnungszeichen aus Markdown würden sonst mitgelesen, und ein
        Codeblock ergibt vorgelesen keinen Sinn – er wird angekündigt statt
        wiedergegeben.
        """

        without_code = _CODE_BLOCK.sub(" Ich habe dir Code geschrieben, er steht im Fenster. ", text)
        without_noise = _SPOKEN_NOISE.sub(" ", without_code)
        # Aufzählungsstriche am Zeilenanfang entfernen.
        without_bullets = re.sub(r"(?m)^\s*[-–—]\s+", "", without_noise)
        return re.sub(r"\s+", " ", without_bullets).strip()

    def split_into_chunks(self, text: str, *, max_characters: int = 0) -> list[str]:
        """Zerlegt einen langen Text an Satzgrenzen.

        Args:
            text: Der aufbereitete Text.
            max_characters: Obergrenze je Abschnitt. 0 nimmt den Wert aus
                der Konfiguration.

        Returns:
            Die Abschnitte in ihrer Reihenfolge.
        """

        limit = max_characters or self._max_characters
        if len(text) <= limit:
            return [text] if text else []

        chunks: list[str] = []
        current = ""

        for sentence in _SENTENCE_END.split(text):
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(sentence) > limit:
                # Ein einzelner überlanger Satz wird an Kommas geteilt und
                # notfalls hart umbrochen – besser ein ungeschickter Schnitt
                # als eine abgeschnittene Antwort.
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_hard(sentence, limit))
                continue

            if len(current) + len(sentence) + 1 <= limit:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _split_hard(sentence: str, limit: int) -> list[str]:
        parts: list[str] = []
        current = ""
        for piece in sentence.split(", "):
            if len(current) + len(piece) + 2 <= limit:
                current = f"{current}, {piece}".strip(", ")
            else:
                if current:
                    parts.append(current)
                current = piece[:limit]
        if current:
            parts.append(current)
        return parts or [sentence[:limit]]

    # --- Erzeugung ---------------------------------------------------------------------

    async def speak(
        self,
        text: str,
        *,
        state: str = "",
        emotion: str = "",
        speed: float = 0.0,
        volume: float = 0.0,
        voice: str = "",
    ) -> SpeechResult:
        """Erzeugt Sprache aus Text.

        Args:
            text: Was gesagt werden soll.
            state: Der Zustand des Orb, für die Gefühlslage.
            emotion: Feste Gefühlslage; leer bedeutet ableiten.
            speed: Feste Geschwindigkeit; 0 nimmt die Konfiguration.
            volume: Feste Lautstärke; 0 nimmt die Konfiguration.
            voice: Feste Stimme; leer nimmt die des Verfahrens.

        Returns:
            Das Ergebnis mit dem Pfad zur WAV-Datei.
        """

        if not self._enabled:
            return SpeechResult(error="Die Sprachausgabe ist ausgeschaltet.")

        prepared = self.prepare_text(text)
        if not prepared:
            return SpeechResult(error="Es gab nichts zu sagen.")

        profile = (
            emotion_module.get_emotion(emotion)
            if emotion
            else emotion_module.detect(prepared, state=state)
        )
        if not self._emotions_enabled:
            profile = emotion_module.get_emotion("neutral")

        # Die Geschwindigkeit wird begrenzt: Grundtempo mal Gefühlslage darf
        # die Rede nie so beschleunigen, dass sie unverständlich wird –
        # und nie so bremsen, dass sie einschläft.
        final_speed = max(0.75, min(1.15, (speed or self._base_speed) * profile.speed))

        request = SpeechRequest(
            text=prepared,
            voice=voice,
            speed=final_speed,
            pitch=profile.pitch,
            # Ausdruck ja, Lautstärkesprünge nein. Gefühl bleibt in Tempo,
            # Tonhöhe und Prosodie; der Grundpegel bleibt über alle Sätze
            # gleich. Der Player gleicht anschließend kleine Unterschiede
            # der tatsächlich erzeugten WAV-Dateien aus.
            volume=(volume or self._base_volume)
            * (1.0 if self._stable_volume else profile.volume),
            emotion=profile.name,
        )

        result = await self._synthesize_with_fallback(request)
        self._last_result = result
        if result.succeeded:
            self._spoken_count += 1
        return result

    async def _synthesize_with_fallback(self, request: SpeechRequest) -> SpeechResult:
        """Versucht die Verfahren der Reihe nach."""

        eligible = self._eligible_engines()
        if not eligible:
            return SpeechResult(error=self.diagnose())

        problems: list[str] = []

        for engine in eligible:
            if not engine.is_available():
                problems.append(f"{engine.name}: nicht einsatzbereit")
                continue

            target = engine.target_path(request)

            if self._cache_enabled and target.exists() and target.stat().st_size > 44:
                self._active = engine
                return SpeechResult(
                    audio_path=target,
                    engine=engine.name,
                    duration_seconds=engine.wav_duration(target),
                    from_cache=True,
                )

            result = await asyncio.to_thread(engine.synthesize_blocking, request, target)

            if result.succeeded:
                self._active = engine
                if not self._cache_enabled:
                    # Ohne Zwischenspeicher wird die Datei nach der Wiedergabe
                    # entfernt; das übernimmt cleanup().
                    pass
                return result

            problems.append(f"{engine.name}: {result.error}")
            logger.warning(
                "Sprachausgabe über '%s' fehlgeschlagen, es wird das nächste "
                "Verfahren versucht. Grund: %s",
                engine.name,
                result.error,
            )

        return SpeechResult(
            error="Kein Verfahren konnte sprechen.\n" + "\n".join(problems)
        )

    async def preload(self) -> bool:
        """Wärmt das erste verfügbare Verfahren vor.

        Beim ersten Sprechen muss ein neuronales Modell geladen oder sogar
        heruntergeladen werden. Das nach dem Start im Hintergrund zu tun,
        erspart dem Benutzer die Wartezeit im Gespräch.

        Returns:
            ``True``, wenn ein Verfahren bereit ist.
        """

        if not self._enabled:
            return False

        result = await self.speak(
            str(get_config().get("voice.output.warmup_text", "Bereit.")),
            emotion="neutral",
        )
        if result.succeeded:
            logger.info(
                "Sprachausgabe vorgewärmt über '%s' (%.1f s).",
                result.engine,
                result.processing_seconds,
            )
            return True

        logger.warning("Die Sprachausgabe ließ sich nicht vorwärmen: %s", result.error)
        return False

    # --- Pflege ------------------------------------------------------------------------

    def cleanup(self, *, keep: int = 60, max_age_hours: float = 72.0) -> int:
        """Räumt alte Sprachdateien auf.

        Args:
            keep: Wie viele der jüngsten Dateien in jedem Fall bleiben.
            max_age_hours: Ab welchem Alter gelöscht werden darf.

        Returns:
            Anzahl der gelöschten Dateien.
        """

        files = sorted(
            self._output_directory.glob("*.wav"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
            reverse=True,
        )

        cutoff = time.time() - max_age_hours * 3600.0
        removed = 0
        for path in files[keep:]:
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    # --- Auskunft ------------------------------------------------------------------------

    def voices(self) -> dict[str, list[dict[str, str]]]:
        """Die Stimmen aller Verfahren."""

        return {engine.name: engine.voices() for engine in self._engines}

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {
            "enabled": self._enabled,
            "offline_mode": self._offline_mode,
            "active_engine": self.active_name,
            "engines": [engine.status() for engine in self._engines],
            "available": [engine.name for engine in self.available_engines()],
            "spoken_count": self._spoken_count,
            "emotions_enabled": self._emotions_enabled,
            "stable_volume": self._stable_volume,
            "cache_enabled": self._cache_enabled,
            "cache_directory": str(self._output_directory),
            "diagnosis": self.diagnose(),
            "last_error": self._last_result.error if self._last_result else "",
        }
