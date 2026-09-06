"""Verwaltung der Sprachausgabe.

Der Manager wählt aus den in ``config.yaml`` eingetragenen Verfahren die
gewünschte Stimme. Optional kann er auf ein anderes Verfahren ausweichen;
für die feste Orb-Persona ist dieser Wechsel standardmäßig gesperrt. Ein
technischer Fehler darf sonst mitten in einer Antwort die Stimme austauschen.

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
from backend.tts.chatterbox_engine import ChatterboxEngine
from backend.tts.edge_neural_engine import EdgeNeuralEngine
from backend.tts.elevenlabs_engine import ElevenLabsEngine
from backend.tts.kokoro_engine import KokoroEngine
from backend.tts.german_text import jahreszahlen_sprechbar
from backend.tts.openai_tts_engine import OpenAITtsEngine
from backend.tts.openvoice_clone_engine import OpenVoiceCloneEngine
from backend.tts.piper_engine import PiperEngine
from backend.tts.pocket_tts_engine import PocketTtsEngine
from backend.tts.remote_tts_engine import RemoteTtsEngine
from backend.tts.sapi_engine import SapiEngine
from backend.tts.speechgen_engine import SpeechGenEngine
from backend.tts.supertonic_engine import SupertonicEngine
from backend.utils.paths import get_data_dir

logger = get_logger(__name__)

#: Die bekannten Verfahren.
ENGINE_CLASSES: dict[str, type[TtsEngine]] = {
    "supertonic": SupertonicEngine,
    "pocket_tts": PocketTtsEngine,
    "chatterbox": ChatterboxEngine,
    "openvoice_clone": OpenVoiceCloneEngine,
    "piper": PiperEngine,
    "sapi": SapiEngine,
    "kokoro": KokoroEngine,
    "elevenlabs": ElevenLabsEngine,
    "edge_neural": EdgeNeuralEngine,
    "openai_tts": OpenAITtsEngine,
    "speechgen": SpeechGenEngine,
    "remote": RemoteTtsEngine,
}

# Nur diese Verfahren erzeugen Sprache vollstaendig auf dem Rechner.
# Im Offlinebetrieb werden alle anderen vor jeder Verfuegbarkeitspruefung
# ausgefiltert, damit nicht einmal ein Probeaufruf die Cloud beruehrt.
LOCAL_ENGINE_NAMES: frozenset[str] = frozenset(
    {
        "supertonic",
        "pocket_tts",
        "chatterbox",
        "openvoice_clone",
        "piper",
        "sapi",
        "kokoro",
    }
)

#: Satzenden, an denen ein langer Text zerlegt werden darf.
_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+")

#: Abkuerzungen, deren Punkt kein Satzende ist - fuer die Heilung der
#: Bruchstellen in split_into_chunks. Bewusst dieselben wie in der
#: Sprachpipeline, damit beide Wege gleich zerlegen.
_KEINE_SATZENDEN = frozenset({
    "dr", "prof", "hr", "fr", "nr", "z", "b", "u", "a", "d", "h",
    "usw", "etc", "ca", "bzw", "vgl", "ggf", "evtl", "inkl", "max", "min",
    "s", "sog", "bspw", "abb", "tab", "jh", "st",
    "mio", "mrd", "tsd", "hrsg", "bd", "kap", "art", "abs",
})


def _kein_satzende(teil: str) -> bool:
    """Ob ein Abschnitt auf einem Punkt endet, der KEIN Satzende ist.

    Zwei Faelle: die Ordnungszahl ("im 6." vor "Jahrhundert") und die
    Abkuerzung ("z. B."). Jahreszahlen (drei, vier Ziffern) bleiben ein
    moegliches Satzende - "Der Kongress endete 1815." ist ein Satz.
    """

    knapp = teil.rstrip()
    if not knapp.endswith("."):
        return False
    worte = knapp[:-1].split()
    if not worte:
        return False
    letztes = worte[-1].strip(".,;:").lower()
    if letztes.isdigit() and len(letztes) <= 2:
        return True
    return letztes in _KEINE_SATZENDEN

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
        # Eine Antwort darf nicht je nach Satz mit einer anderen Klangfarbe
        # weitergehen. Die aktive, funktionierende Engine bleibt deshalb vorn,
        # bis sie wirklich ausfällt oder der Benutzer den Betriebsmodus ändert.
        self._consistent_voice = bool(
            config.get("voice.output.consistent_voice", True)
        )
        # Bei einer festen Persona ist eine andere Stimme kein hilfreicher
        # Rueckfall, sondern ein Identitaetsbruch. Ist das ausgeschaltet,
        # meldet ein Fehler die Ausgabe als fehlgeschlagen, statt mitten in
        # einer Antwort von Mann zu Frau oder Neuralstimme zu SAPI zu springen.
        self._allow_voice_fallback = bool(
            config.get("voice.output.allow_voice_fallback", False)
        )
        self._emotions_enabled = bool(config.get("voice.output.emotions_enabled", True))
        self._failure_cooldown_seconds = max(
            5.0, float(config.get("voice.output.failure_cooldown_seconds", 90))
        )

        # Die Frist auf EINEN Syntheseversuch.
        #
        # Sie fehlte, und das war der groesste einzelne Befund des
        # Betriebsprotokolls: Von 694 erzeugten Antworten wurden 281 nie
        # gesprochen - und nur 4 davon kamen ueberhaupt bis zum fertigen
        # Ton. Der Abbruch lag also VOR der Synthese.
        #
        # Der Grund steht eine Seite weiter unten: ``await
        # asyncio.to_thread(engine.synthesize_blocking, ...)`` hatte keine
        # Frist. Ein Verfahren, das FEHLSCHLAEGT, meldet sich und das
        # naechste uebernimmt. Ein Verfahren, das HAENGT, tat beides nicht:
        # keine Zeile im Protokoll, kein Wechsel, kein Ton - und der Orb
        # hielt sich weiter fuer sprechend (am 06.09. ueber eine Minute
        # lang, nachzuzaehlen an 202 Hoerfenstern des Stop-Spaehers).
        #
        # Auch ein Zeitlimit auf dem Socket schuetzt davor nicht: Es gilt je
        # Leseoperation, nicht fuer den ganzen Vorgang. Ein Dienst, der
        # langsam tropft, laeuft nie hinein.
        #
        # Die Frist waechst mit der Laenge des Satzes - ein langer Satz darf
        # laenger dauern als ein kurzer, aber nicht unbegrenzt.
        self._synthese_frist = max(
            5.0, float(config.get("voice.output.synthesis_timeout_seconds", 40))
        )
        self._synthese_frist_je_100 = max(
            0.0, float(config.get("voice.output.synthesis_timeout_per_100_chars", 8))
        )
        self._synthese_frist_hoechstens = max(
            self._synthese_frist,
            float(config.get("voice.output.synthesis_timeout_max_seconds", 180)),
        )

        self._engine_failed_until: dict[str, float] = {}
        self._engine_failure_reasons: dict[str, str] = {}
        # Ein bestaetigter Netzwerkfehler eines Sprachdienstes gilt fuer alle
        # Cloud-Stimmen. Sonst wuerde derselbe Satz nacheinander bei
        # ElevenLabs, Edge und OpenAI auf eine nicht vorhandene Verbindung
        # warten, bevor der lokale Klon uebernimmt.
        self._network_failed_until = 0.0

        self._output_directory = get_data_dir() / "tts"
        self._output_directory.mkdir(parents=True, exist_ok=True)

        requested: list[str] = [
            str(name).strip().lower()
            for name in (config.get("voice.output.engines", ["piper", "sapi", "kokoro"]) or [])
        ]
        self._offline_engine_names = [
            str(name).strip().lower()
            for name in (
                config.get(
                    "voice.output.offline_engines",
                    ["supertonic"],
                ) or []
            )
            if str(name).strip()
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
        if not self._offline_mode:
            # Ein Provider-Ereignis mit wiederhergestellter Cloud-Verbindung
            # hebt auch die voruebergehende TTS-Netzsperre auf.
            self._network_failed_until = 0.0
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

        now = time.monotonic()
        failed_until = getattr(self, "_engine_failed_until", {})
        return [
            engine
            for engine in self._eligible_engines()
            if engine.is_available() and failed_until.get(engine.name, 0.0) <= now
        ]

    def _eligible_engines(self) -> list[TtsEngine]:
        automatic_local = (
            getattr(self, "_network_failed_until", 0.0) > time.monotonic()
        )
        if not self._offline_mode and not automatic_local:
            geordnet = list(self._engines)
            return self._aktive_zuerst(geordnet)
        # Offline hat eine eigene Prioritaet: Dort soll die schnelle,
        # hochwertige Pocket-Stimme zuerst sprechen. Die natuerlichen
        # Online-Stimmen werden schon vor jeder Verfuegbarkeitspruefung
        # ausgeschlossen, damit kein Diktat versehentlich den Rechner
        # verlaesst.
        nach_name = {
            engine.name: engine
            for engine in self._engines
            if engine.name in LOCAL_ENGINE_NAMES
        }
        offline_names = getattr(
            self,
            "_offline_engine_names",
            ["supertonic"],
        )
        geordnet = [
            nach_name[name]
            for name in offline_names
            if name in nach_name
        ]
        # ``offline_engines`` ist bewusst eine Zulassungsliste, nicht nur
        # eine Sortierung. Steht dort ausschliesslich Chatterbox, darf ein
        # Fehler nicht still auf Piper/SAPI ausweichen und dem Benutzer eine
        # fremde Stimme als angeblichen Klon vorspielen.
        return self._aktive_zuerst(geordnet)

    def _aktive_zuerst(self, engines: list[TtsEngine]) -> list[TtsEngine]:
        """Haelt die gewaehlte Stimme stabil, solange sie einsatzberechtigt ist."""

        active = getattr(self, "_active", None)
        if not getattr(self, "_consistent_voice", False) or active not in engines:
            return engines
        return [active, *(engine for engine in engines if engine is not active)]

    @staticmethod
    def _is_network_failure(error: str) -> bool:
        lowered = str(error).lower()
        markers = (
            "network is unreachable",
            "network error",
            "name resolution",
            "getaddrinfo",
            "failed to fetch",
            "unable to connect",
            "cannot connect",
            "connection refused",
            "connection reset",
            "connection aborted",
            "connect timeout",
            "timed out",
            "enotfound",
            "econnrefused",
            "econnreset",
            "nicht erreichbar",
            "netzwerkfehler",
            "keine internetverbindung",
        )
        return any(marker in lowered for marker in markers)

    def diagnose(self) -> str:
        """Erklärt im Klartext, warum gesprochen wird oder nicht."""

        eligible = self._eligible_engines()
        if not eligible:
            if self._offline_mode:
                return (
                    "Im Offlinebetrieb ist keine lokale Stimme konfiguriert. "
                    "Trage supertonic unter "
                    "'voice.output.engines' ein."
                )
            return (
                "Es ist kein Sprachausgabe-Verfahren eingetragen. Trage unter "
                "'voice.output.engines' in config.yaml mindestens eines ein."
            )

        available = self.available_engines()
        if available:
            names = ", ".join(engine.name for engine in available)
            failures = getattr(self, "_engine_failure_reasons", {})
            if failures:
                ausgefallen = "; ".join(
                    f"{name}: {reason}" for name, reason in failures.items()
                )
                return (
                    f"Sprachausgabe bereit über: {names}. "
                    f"Nicht verfügbar: {ausgefallen}"
                )
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
        sprechbar = jahreszahlen_sprechbar(without_bullets)
        # Auslassungspunkte und eingeschobene Gedankenstriche fordern
        # synthetische Stimmen geradezu zu langen, zoegernden Pausen auf.
        # Inhaltlich sind sie beim Vorlesen ein normaler Satzabschluss bzw.
        # eine kurze Nebenbemerkung.
        sprechbar = re.sub(r"\.{3,}|…+", ". ", sprechbar)
        sprechbar = re.sub(r"\s+[–—]\s+", ", ", sprechbar)
        return re.sub(r"\s+", " ", sprechbar).strip()

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

        # Bruchstellen heilen, die keine Satzenden sind: Der Punkt einer
        # Ordnungszahl ("im 6. Jahrhundert") oder Abkuerzung ("z. B.")
        # zerlegte den Text sonst mitten im Gedanken - und zwischen zwei
        # Abschnitten macht die Wiedergabe eine Satzpause. Genau dort
        # entstanden die unnatuerlichen Luecken mitten im Satz (20.08.).
        teile: list[str] = []
        for sentence in _SENTENCE_END.split(text):
            if teile and _kein_satzende(teile[-1]):
                teile[-1] = f"{teile[-1]} {sentence}".strip()
            else:
                teile.append(sentence)

        for sentence in teile:
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
        _bypass_cache: bool = False,
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

        result = (
            await self._synthesize_with_fallback(request, bypass_cache=True)
            if _bypass_cache
            else await self._synthesize_with_fallback(request)
        )
        self._last_result = result
        if result.succeeded:
            self._spoken_count += 1
        return result

    def _frist_fuer(self, request: SpeechRequest) -> float:
        """Wie lange ein einzelnes Verfahren fuer diesen Satz brauchen darf.

        ``getattr`` mit Vorgabewert wie an den Nachbarstellen: Der Manager
        wird an mehreren Stellen ueber ``__new__`` aufgebaut, und eine
        fehlende Einstellung darf nicht die Sprachausgabe reissen - dann
        gaebe es wieder genau die Stille, gegen die diese Frist steht.
        """

        grund = float(getattr(self, "_synthese_frist", 40.0))
        je_100 = float(getattr(self, "_synthese_frist_je_100", 8.0))
        hoechstens = float(getattr(self, "_synthese_frist_hoechstens", 180.0))
        return min(hoechstens, grund + len(request.text) / 100.0 * je_100)

    async def _synthesize_with_fallback(
        self, request: SpeechRequest, *, bypass_cache: bool = False
    ) -> SpeechResult:
        """Versucht die Verfahren der Reihe nach."""

        eligible = self._eligible_engines()
        if not eligible:
            return SpeechResult(error=self.diagnose())

        problems: list[str] = []
        local_only_for_request = bool(
            self._offline_mode
            or getattr(self, "_network_failed_until", 0.0) > time.monotonic()
        )

        for engine in eligible:
            if local_only_for_request and engine.name not in LOCAL_ENGINE_NAMES:
                problems.append(
                    f"{engine.name}: wegen fehlender Netzwerkverbindung uebersprungen"
                )
                continue
            failed_until = self._engine_failed_until.get(engine.name, 0.0)
            if failed_until > time.monotonic():
                problems.append(f"{engine.name}: nach Fehler voruebergehend pausiert")
                continue
            if not engine.is_available():
                problems.append(f"{engine.name}: nicht einsatzbereit")
                continue

            target = engine.target_path(request)

            if (
                not bypass_cache
                and self._cache_enabled
                and target.exists()
                and target.stat().st_size > 44
            ):
                self._engine_failed_until.pop(engine.name, None)
                getattr(self, "_engine_failure_reasons", {}).pop(engine.name, None)
                self._active = engine
                return SpeechResult(
                    audio_path=target,
                    engine=engine.name,
                    duration_seconds=engine.wav_duration(target),
                    from_cache=True,
                )

            frist = self._frist_fuer(request)
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(engine.synthesize_blocking, request, target),
                    timeout=frist,
                )
            except asyncio.TimeoutError:
                # Der Arbeitsfaden laeuft weiter - ``to_thread`` laesst sich
                # nicht abbrechen. Das ist hinnehmbar: Er schreibt in eine
                # eigene Zieldatei und endet von selbst. Wichtig ist, dass
                # DIESER Weg weitergeht, statt fuer immer zu warten.
                result = SpeechResult(
                    error=(
                        f"{engine.name}: hat innerhalb von {frist:.0f} s nicht "
                        "geliefert und wurde aufgegeben."
                    )
                )

            if result.succeeded:
                self._engine_failed_until.pop(engine.name, None)
                getattr(self, "_engine_failure_reasons", {}).pop(engine.name, None)
                self._active = engine
                if not self._cache_enabled:
                    # Ohne Zwischenspeicher wird die Datei nach der Wiedergabe
                    # entfernt; das übernimmt cleanup().
                    pass
                return result

            problems.append(f"{engine.name}: {result.error}")
            fatal_for_session = bool(result.context.get("fatal_for_session", False))
            self._engine_failed_until[engine.name] = (
                float("inf")
                if fatal_for_session
                else time.monotonic() + self._failure_cooldown_seconds
            )
            getattr(self, "_engine_failure_reasons", {})[engine.name] = result.error
            if (
                engine.name not in LOCAL_ENGINE_NAMES
                and self._is_network_failure(result.error)
            ):
                local_only_for_request = True
                self._network_failed_until = (
                    time.monotonic() + self._failure_cooldown_seconds
                )
                logger.warning(
                    "Netzwerk fuer Cloud-Stimmen nicht erreichbar; "
                    "dieser und die naechsten Saetze verwenden sofort den "
                    "lokalen Stimmklon."
                )
            logger.warning(
                "Sprachausgabe über '%s' fehlgeschlagen%s%s. Grund: %s",
                engine.name,
                " und bleibt bis zum Neustart pausiert" if fatal_for_session else "",
                (
                    ", das nächste Verfahren wird versucht"
                    if getattr(self, "_allow_voice_fallback", True)
                    else ", ein Stimmwechsel ist gesperrt"
                ),
                result.error,
            )
            if not getattr(self, "_allow_voice_fallback", True):
                logger.error(
                    "Der Wechsel auf eine andere Stimme ist gesperrt; "
                    "die Ausgabe wird mit derselben Persona beendet."
                )
                break

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
            # Ein alter ElevenLabs-Cache beweist nicht, dass der aktuelle
            # Schluessel noch funktioniert. Der echte, sehr kurze Probezug
            # erkennt einen abgelaufenen Schluessel bereits beim Start und
            # meldet den Fallback ehrlich, statt erst bei der ersten Antwort.
            _bypass_cache=True,
        )
        stream = result.context.get("pcm_stream")
        if stream is not None:
            # Vorwaermen wird nicht abgespielt. Trotzdem den kurzen Strom
            # fertig erzeugen lassen, damit der erste echte Satz nicht hinter
            # dem Warmup auf die Modellsperre warten muss.
            await asyncio.to_thread(stream.wait_until_done, 30.0)
            if stream.error:
                result.error = f"Pocket-TTS-Warmup ist fehlgeschlagen: {stream.error}"
                result.audio_path = None
                result.context.pop("pcm_stream", None)
            else:
                result.duration_seconds = float(stream.duration_seconds)
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

    @property
    def output_directory(self) -> Path:
        """Wo die erzeugten Tondateien liegen.

        `status()` nennt denselben Ordner - ruft dabei aber `diagnose()`
        auf und befragt jedes Verfahren. Wer nur wissen will, wo eine
        Datei liegt, soll dafuer nicht den gesamten Selbsttest ausloesen.
        """

        return self._output_directory

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        clone_engine = next(
            (
                engine
                for engine in self._engines
                if engine.name in {
                    "supertonic",
                    "pocket_tts",
                    "openvoice_clone",
                    "chatterbox",
                }
            ),
            None,
        )
        clone_status = clone_engine.status() if clone_engine is not None else {}
        now = time.monotonic()
        failed_until = getattr(self, "_engine_failed_until", {})
        failure_reasons = getattr(self, "_engine_failure_reasons", {})
        engine_status: list[dict[str, Any]] = []
        for engine in self._engines:
            details = dict(engine.status())
            details["paused"] = failed_until.get(engine.name, 0.0) > now
            details["failure"] = failure_reasons.get(engine.name, "")
            engine_status.append(details)

        verfuegbar = self.available_engines()
        preferred = verfuegbar[0].name if verfuegbar else ""
        return {
            "enabled": self._enabled,
            "offline_mode": self._offline_mode,
            "automatic_local_fallback": bool(
                not self._offline_mode
                and getattr(self, "_network_failed_until", 0.0) > now
            ),
            "active_engine": self.active_name,
            "clone_model": (
                str(clone_status.get("model_variant", ""))
                if clone_status.get("model_variant")
                else ""
            ),
            "clone_ready": bool(clone_status.get("available", False)),
            "clone_cached": bool(clone_status.get("model_cached", False)),
            "preferred_engine": preferred,
            "fallback_active": bool(
                self.active_name and preferred and self.active_name != preferred
            ) or bool(failure_reasons),
            "engines": engine_status,
            "available": [engine.name for engine in verfuegbar],
            "spoken_count": self._spoken_count,
            "emotions_enabled": self._emotions_enabled,
            "stable_volume": self._stable_volume,
            "cache_enabled": self._cache_enabled,
            "cache_directory": str(self._output_directory),
            "diagnosis": self.diagnose(),
            "last_error": self._last_result.error if self._last_result else "",
            "degraded_reason": "; ".join(
                f"{name}: {reason}" for name, reason in failure_reasons.items()
            ),
        }
