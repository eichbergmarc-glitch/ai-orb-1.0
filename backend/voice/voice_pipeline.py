"""Die Sprachpipeline – hier wird aus Zuhören ein Gespräch.

Sie führt die Einzelteile zusammen: Das Mikrofon nimmt auf, die
Sprachaktivitätserkennung schneidet Äußerungen heraus, Whisper macht Text
daraus, die Weckworterkennung entscheidet, ob gemeint war, und die
Sprachausgabe antwortet.

Der Ablauf in einem Satz: **Schlafen, bis „Hallo Orb" fällt – dann zuhören,
antworten, und noch einen Moment wach bleiben.**

Vier Entscheidungen prägen das Verhalten:

**Das Weckwort schützt die Privatsphäre.** Im Schlafzustand wird zwar
zugehört, aber nichts weitergegeben: Der Text wird auf das Weckwort geprüft
und dann verworfen. Erst danach geht etwas an die KI. Aufnahmen werden nicht
dauerhaft gespeichert.

**Nach der Antwort bleibt der Orb wach.** Ein Gespräch besteht selten aus
einer Frage. Wer nach der Antwort weiterspricht, muss das Weckwort nicht
wiederholen; erst nach einer Ruhepause schläft der Orb wieder ein.

**Wer dazwischenredet, hat Vorrang.** Spricht der Benutzer, während der Orb
antwortet, bricht die Wiedergabe ab. Das ist der Unterschied zwischen einem
Gespräch und einer Ansage.

**Unsicheres wird nachgefragt, nicht geraten.** Liegt die Verlässlichkeit
der Erkennung unter der eingestellten Schwelle, fragt der Orb nach, statt
auf eine womöglich falsch verstandene Anweisung hin zu handeln.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.audio.audio_capture import AudioCapture
from backend.audio.player import AudioPlayer
from backend.config import get_config
from backend.events import event_types
from backend.events.event_bus import EventBus
from backend.security.security_engine import SecurityEngine
from backend.system.logging_setup import get_logger
from backend.diktat.diktat import KALIBRIERSATZ, Diktierer
from backend.tts.tts_manager import TtsManager
from backend.voice.speaker_id import Stimmerkennung, Urteil
from backend.whisper.transcriber import Transcriber, Transcript
from backend.whisper.wake_word import WakeWordDetector

logger = get_logger(__name__)


#: Wie viele zuletzt gesprochene Saetze fuer den Echo-Test behalten werden.
#:
#: Das Echo im Mikrofon hinkt der Ausgabe nach - wie weit, haengt an der
#: Puffergroesse der Soundkarte und ist von hier aus nicht zu wissen. Mit
#: nur einem Vorgaengersatz fiel ein Hoerfenster regelmaessig auf Woerter,
#: die der Orb schon vergessen hatte, und er hielt sich selbst fuer einen
#: Fremden. Fuenf Saetze sind ein paar Dutzend Woerter - fuer eine
#: Mengenpruefung nichts, und weit genug zurueck fuer jede Puffergroesse.
ECHO_SAETZE = 5

#: Ab welcher Aehnlichkeit ein gehoertes Wort als Verhoerer eines eigenen
#: gilt und nicht als fremdes.
#:
#: 0.75 laesst "Sprachausgabe"/"Sprachaufgabe" durchgehen, trennt aber
#: "Warte" von "Antwort". Niedriger, und ein echter Zwischenruf verschwindet
#: in der Aehnlichkeit; hoeher, und die Verhoerer kommen zurueck.
AEHNLICH_GENUG = 0.75

#: Ab welcher UNaehnlichkeit ein einzelnes langes Wort allein genuegt, um
#: die Antwort abzubrechen.
#:
#: Zwei Schwellen und nicht eine, weil es zwei verschiedene Fragen sind.
#:
#: Die erste lautet: Ist dieses Wort ein Verhoerer? Dafuer steht 0.75.
#: Die zweite lautet: Reicht dieses eine Wort, um eine laufende Antwort
#: abzubrechen? Das ist die viel groessere Behauptung, und sie darf sich
#: nicht auf einen knappen Fall stuetzen.
#:
#: Der Anlass ist gemessen: "verstehen" gegen das gesprochene "verstanden"
#: ergibt 0.74. Es faellt also knapp durch die erste Schwelle - und weil es
#: neun Zeichen hat, brach es die Antwort im Alleingang ab. Genau dieses
#: Knapp-daneben ist der haeufigste Verhoerer ueberhaupt, denn die
#: Erkennung verhoert sich an Endungen und nicht an Wortstaemmen.
#:
#: Wer dazwischenruft, sagt dagegen etwas, das mit dem laufenden Satz
#: nichts zu tun hat - dort liegt die Aehnlichkeit deutlich tiefer.
FREMD_GENUG = 0.55

#: Zeichen, die einen Satz beenden.
_SENTENCE_ENDINGS = ".!?…"

#: Ab so vielen Zeichen ohne Satzzeichen wird trotzdem gesprochen.
#:
#: Manche Antworten kommen als ein langer Fluss ohne Punkt – eine Aufzählung
#: mit Kommas, ein Nebensatzgebirge. Ewig zu warten hieße, gar nicht
#: anzufangen. Nach einer Weile wird deshalb am letzten Komma oder
#: Leerzeichen umbrochen, damit der Orb ins Reden kommt.
_SOFT_BREAK_AFTER = 160

#: Abkürzungen, deren Punkt kein Satzende ist.
#:
#: Ohne diese Liste bräche der Orb nach „Dr.“ oder „z. B.“ mitten im Satz
#: ab und spräche das Bruchstück für sich – „Doktor.“ als ganzer Satz klingt
#: wie ein Schluckauf. Die Liste ist bewusst kurz und deckt das Häufige ab.
_ABBREVIATIONS = frozenset({
    "dr", "prof", "hr", "fr", "nr", "z", "b", "u", "a", "d", "h",
    "usw", "etc", "ca", "bzw", "vgl", "ggf", "evtl", "inkl", "max", "min",
    "s", "sog", "bspw", "abb", "tab", "jh", "st",
})


def _take_complete_sentence(buffer: str) -> tuple[str, str]:
    """Holt den ersten vollständigen Satz aus einem wachsenden Puffer.

    Gibt den Satz und den Rest zurück. Ist noch kein Satz beisammen, kommt
    ein leerer Satz und der unveränderte Puffer zurück – der Aufrufer sammelt
    dann weiter.

    Die Erkennung achtet auf zwei Fallstricke, an denen ein Satz nur
    scheinbar endet: eine Abkürzung wie „Dr.“ und ein Satzzeichen mitten im
    Wort. Deshalb zählt ein Satzende nur, wenn danach ein Leerzeichen (oder
    das Ende) folgt und das Wort davor keine bekannte Abkürzung ist.
    """

    for index, char in enumerate(buffer):
        if char not in _SENTENCE_ENDINGS:
            continue

        after = buffer[index + 1 : index + 2]
        if after not in ("", " ", "\n", "\t"):
            continue

        candidate = buffer[: index + 1].strip()
        if len(candidate) < 3:
            continue

        # Endet der Satz auf einer Abkürzung? Dann ist der Punkt keiner.
        if char == ".":
            last_word = candidate[:-1].split()[-1].strip(".,;:").lower() if candidate[:-1].split() else ""
            if last_word in _ABBREVIATIONS:
                continue

        return candidate, buffer[index + 1 :].lstrip()

    # Kein Satzzeichen, aber der Puffer wird lang – weich umbrechen.
    if len(buffer) >= _SOFT_BREAK_AFTER:
        cut = max(buffer.rfind(", "), buffer.rfind(" "))
        if cut > 40:
            return buffer[:cut].strip(), buffer[cut:].lstrip()

    return "", buffer


class VoiceState(Enum):
    """Der Zustand der Sprachpipeline."""

    #: Ausgeschaltet.
    OFF = "aus"
    #: Wartet auf das Weckwort.
    SLEEPING = "schlafend"
    #: Wach, nimmt Anweisungen entgegen.
    LISTENING = "zuhoerend"
    #: Verarbeitet eine Anweisung.
    THINKING = "denkend"
    #: Spricht gerade.
    SPEAKING = "sprechend"


@dataclass
class VoiceTurn:
    """Ein Gesprächsdurchgang, für Protokoll und Anzeige."""

    transcript: str = ""
    confidence: float = 0.0
    woke: bool = False
    answered: bool = False
    interrupted: bool = False
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript,
            "confidence": round(self.confidence, 3),
            "woke": self.woke,
            "answered": self.answered,
            "interrupted": self.interrupted,
            "duration_seconds": round(self.duration_seconds, 2),
            "timestamp": self.timestamp,
        }


class VoicePipeline:
    """Führt Aufnahme, Erkennung, Antwort und Ausgabe zusammen."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        security: SecurityEngine,
        answer: Callable[..., Awaitable[tuple[str, bool]]],
        answer_stream: Any | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """
        Args:
            event_bus: Für Zustandsmeldungen an die Oberfläche.
            security: Die Mikrofonnutzung wird hierüber freigegeben.
            answer: Wird mit dem erkannten Text aufgerufen und liefert die
                Antwort sowie die Angabe, ob sie unterwegs bereits
                gesprochen wurde. In der Regel das Cognitive Core. Bekommt
                zusätzlich ``on_speech``: eine Funktion, mit der jeder
                fertig gedachte Satz sofort gesprochen wird, statt bis zum
                Ende der Antwort zu schweigen.
            loop: Die Kern-Event-Loop. Wird beim Start gesetzt, wenn nicht
                angegeben.
        """

        config = get_config()

        self._event_bus = event_bus
        self._security = security
        self._answer = answer
        #: Optionaler Streaming-Weg: liefert die Antwort in Stücken, damit
        #: der Orb den ersten Satz spricht, während er den Rest noch denkt.
        self._answer_stream = answer_stream
        self._loop = loop

        # --- Diktiermodus --------------------------------------------------------
        # Laeuft ein Diktat, uebernimmt eine kleine Zustandsmaschine die
        # Aeusserungen (weiter/langsamer/nochmal/stopp), statt sie ans
        # Sprachmodell zu geben. ``None`` = kein Diktat.
        self._diktat: Any = None
        self._diktat_phase = ""          # "" | "kalibrierung" | "diktat"
        self._diktat_start = 0.0
        self._diktat_ziel_sekunden = float(
            config.get("voice.diktat.ziel_sekunden", 12)
        )

        # --- Einstellungen -------------------------------------------------------
        self._enabled = bool(config.get("voice.enabled", True))
        self._always_on = bool(config.get("voice.wake_word.always_on", True))
        self._follow_up_seconds = float(config.get("voice.follow_up_seconds", 25.0))
        self._min_confidence = float(config.get("voice.input.min_confidence", 0.35))
        self._min_characters = int(config.get("voice.input.min_characters", 2))
        #: Unter dieser Sicherheit wird nachgefragt statt geantwortet.
        #:
        #: Der Benutzer meldete, der Orb verstehe ihn schlecht. Das
        #: Protokoll gab ihm recht: Von vierzehn erkannten Aeusserungen
        #: lagen acht unter 0.90, und mehrere waren Kauderwelsch -
        #: "Forte Forte, Dein Landtort", "Kommst du die Suche der Politen
        #: irgendwie?".
        #:
        #: Das Schlimme daran ist nicht die Fehlerkennung selbst. Es ist,
        #: dass der Orb darauf ANTWORTET. Er bekommt einen Satz, den nie
        #: jemand gesagt hat, denkt darueber nach und redet - und der
        #: Benutzer haelt IHN fuer kaputt.
        #:
        #: Ein Mensch fragt in so einem Fall nach. Genau das tut er jetzt
        #: auch. Die alte Schwelle (min_confidence 0.35) half dabei nicht:
        #: Sie warf nur weg, was ohnehin unbrauchbar war, und liess alles
        #: darueber als Befehl durchgehen.
        self._rueckfrage_unter = float(
            config.get("voice.input.rueckfrage_unter", 0.78)
        )
        self._rueckfrage_text = str(
            config.get(
                "voice.input.rueckfrage_text",
                "Das habe ich nicht sicher verstanden. Sagst du es noch einmal?",
            )
        )
        self._barge_in = bool(config.get("voice.barge_in", True))
        self._acknowledge = bool(config.get("voice.acknowledge_wake", True))
        self._acknowledge_text = str(config.get("voice.acknowledge_text", "Ja?"))

        # Wörter, die das Sprechen abbrechen. Bewusst kurz und markant, damit
        # der Orb sie nicht in seiner eigenen Antwort versehentlich auslöst.
        self._stop_words = {
            str(word).strip().lower()
            for word in (config.get("voice.stop_words", ["stop", "stopp", "halt"]) or [])
        }

        #: Ob die Antwort im Fluss gesprochen wird – denken, sprechen,
        #: weiterdenken, weitersprechen.
        #:
        #: Standardmäßig aus, und das aus einem sachlichen Grund: Der
        #: Fluss-Weg redet unmittelbar mit dem Sprachmodell und lässt dabei
        #: die Denkschicht aus – also auch den Geschichtsprofessor, die
        #: Werkzeuge und das Einordnen der Absicht. Für ein lockeres
        #: Gespräch ist das genau richtig und wunderbar flüssig; für „prüfe
        #: mich“ oder „analysiere diese Quelle“ wäre es ein Rückschritt.
        #:
        #: Der spürbare Gewinn an Flüssigkeit kommt ohnehin schon ohne
        #: diesen Schalter – daher, dass der nächste Satz vorbereitet wird,
        #: während der aktuelle läuft (siehe :meth:`_say`). Wer das reine,
        #: schnelle Gespräch will, schaltet ``voice.stream_speech`` ein.
        self._stream_speech = bool(config.get("voice.stream_speech", False))

        #: Wahr, solange der Orb spricht und nur auf das Stop-Wort horcht.
        #:
        #: In dieser Zeit nimmt das Mikrofon zwar auf, aber alles Gesagte
        #: wird ausschließlich daraufhin geprüft, ob ein Stop-Wort fiel –
        #: nichts wird als Befehl verarbeitet. So kann der Orb sich selbst
        #: hören, ohne auf die eigene Stimme zu reagieren: Seine Antwort
        #: enthält die kurzen Stop-Wörter praktisch nie.
        self._listening_for_stop = False

        # --- Bestandteile ----------------------------------------------------------
        self._wake_word = WakeWordDetector(
            config.get("voice.wake_word.phrases", ["Hallo Orb"]) or ["Hallo Orb"],
            threshold=float(config.get("voice.wake_word.threshold", 0.78)),
            max_leading_words=int(config.get("voice.wake_word.max_leading_words", 3)),
        )

        self._transcriber = Transcriber(
            model_size=str(config.get("voice.input.model_size", "small")),
            language=str(config.get("voice.input.language", "de")),
            device=str(config.get("voice.input.device", "auto")),
            compute_type=str(config.get("voice.input.compute_type", "int8")),
            beam_size=int(config.get("voice.input.beam_size", 1)),
            anfangshinweis=str(config.get("voice.input.initial_prompt", "")),
        )

        #: Eine zweite, absichtlich winzige Erkennung – nur für das
        #: Stop-Wort.
        #:
        #: Das große Modell braucht für ein Hörfenster ein bis drei
        #: Sekunden. Die Fenster kommen aber alle 600 Millisekunden. Wer
        #: das große Modell dafür benutzt, kommt nie hinterher: Die
        #: meisten Fenster werden vom nächsten überholt, bevor sie
        #: geprüft sind – und in diesen Lücken ging das „stop" verloren.
        #:
        #: Hier wird kein Satz verstanden, sondern nach drei kurzen,
        #: markanten Wörtern gehorcht. Dafür genügt „base" – schnell genug,
        #: um mit den Fenstern Schritt zu halten, und für kurze Befehle
        #: zuverlässig genug. („tiny" wäre noch schneller, verhört sich im
        #: Deutschen aber zu oft.)
        self._stop_transcriber = Transcriber(
            model_size=str(config.get("voice.stop_model_size", "base")),
            language=str(config.get("voice.input.language", "de")),
            device=str(config.get("voice.input.device", "auto")),
            compute_type=str(config.get("voice.input.compute_type", "int8")),
            beam_size=1,
        )

        # --- Auf wen gehoert wird ------------------------------------------
        #
        # Das Mikrofon hoert alles: den Fernseher, ein Gespraech nebenan,
        # eine Videokonferenz. Ohne diese Pruefung war dem Orb jede Stimme
        # gleich viel wert, und er nahm Saetze als Anweisung entgegen, die
        # niemand an ihn gerichtet hatte.
        from backend.utils.paths import get_data_dir

        self._stimme = Stimmerkennung(
            profil_pfad=get_data_dir() / "stimmprofil.json",
            mindestaehnlichkeit=float(config.get("voice.speaker.min_similarity", 0.55)),
            hoechstschwelle=float(config.get("voice.speaker.max_threshold", 0.80)),
            sicherheitsabstand=float(config.get("voice.speaker.margin", 0.06)),
            aktiv=bool(config.get("voice.speaker.enabled", True)),
        )
        #: Wie viele Aufnahmen zum Lernen gesammelt werden.
        self._stimme_anzahl = int(config.get("voice.speaker.enrollment_utterances", 3))
        #: Waehrend des Lernens gesammelte Aufnahmen. Leer heisst: kein Lernen.
        self._stimme_lernt: list[Path] | None = None
        #: Wie oft in Folge eine Probe als unbrauchbar zurueckgewiesen wurde.
        #: Verhindert eine Endlosschleife, wenn das Mikrofon dauerhaft zu leise
        #: oder zu laut ist - nach ein paar Versuchen wird die Probe dennoch
        #: genommen und das ehrliche Urteil faellt am Ende.
        self._stimme_rueckweisungen = 0
        #: Ob jede eigene Aeusserung die Sprachausgabe beendet - nicht nur
        #: das Stop-Wort. Setzt eine hinterlegte Stimme voraus.
        self._interrupt_on_speech = bool(
            config.get("voice.interrupt_on_speech", True)
        )
        #: Wie viele Hoerfenster nacheinander fremde Worte enthalten
        #: muessen, bevor der Wortvergleich unterbricht.
        #:
        #: Eins genuegte nicht. Der Wortvergleich arbeitet auf dem, was
        #: Whisper aus dem Echo der eigenen Stimme macht - und das ist
        #: keine saubere Abschrift, sondern ein Text mit verhoerten und
        #: erfundenen Woertern. Ein einzelnes solches Fenster reichte, um
        #: die Antwort abzubrechen.
        #:
        #: Wer wirklich dazwischenredet, tut das laenger als ein Fenster
        #: (gut eine Sekunde). Ein Verhoerer dagegen ist ein einmaliger
        #: Ausrutscher und im naechsten Fenster wieder weg. Zwei Fenster
        #: kosten also eine knappe Sekunde und trennen genau die beiden
        #: Faelle. Die Stimmerkennung bleibt davon unberuehrt - sie ist
        #: der starke Weg und unterbricht weiterhin sofort.
        self._fremd_fenster_noetig = max(
            1, int(config.get("voice.interrupt_windows", 2))
        )
        #: Wie sicher die Erkennung sein muss, damit ihr Text den
        #: Wortvergleich ueberhaupt ausloesen darf.
        #:
        #: Ein Hoerfenster mit dem Echo der eigenen Stimme wird schlecht
        #: erkannt, weil es kein sauberes Sprachsignal ist. Genau in diesen
        #: Faellen erfindet Whisper Woerter, und genau die sahen dann wie
        #: fremde Rede aus.
        self._fremd_mindestsicherheit = float(
            config.get("voice.interrupt_min_confidence", 0.45)
        )
        #: Ab welcher Stimm-Aehnlichkeit ein Hoerfenster die laufende Rede
        #: ABBRICHT - bewusst HOCH und getrennt von der Akzeptanzschwelle
        #: der Sprechererkennung.
        #:
        #: Genau hier lag der Grund, warum der Orb "mitten im Satz abbrach":
        #: Waehrend er spricht, ist sein eigenes Echo im Hoerfenster, und die
        #: Akzeptanzschwelle war (fuer das Wiedererkennen des Benutzers) auf
        #: 0.55 gesenkt. Damit galt schon das eigene Echo als "der Benutzer
        #: redet" - und die Antwort brach ab. Ein ABBRUCH ist aber eine viel
        #: staerkere Behauptung als ein blosses "das ist der Benutzer": Er
        #: verlangt, dass wirklich jemand DEUTLICH ueber die laufende Rede
        #: spricht. Darum eine eigene, hohe Schwelle. Das Stop-Wort und der
        #: Wortvergleich unterbrechen weiterhin unabhaengig davon.
        self._barge_in_min_aehnlichkeit = float(
            config.get("voice.barge_in_min_aehnlichkeit", 0.82)
        )
        #: Wie viele Fenster in Folge bisher fremde Worte enthielten.
        self._fremd_folge = 0

        # Der Denk-Klang.
        #
        # Der Orb zeigte bisher nur, dass er nachdenkt. Wer gerade nicht
        # hinsieht - und das ist bei einem Sprachassistenten die Regel -,
        # hoerte nach der Frage bloss Stille und wusste nicht, ob sie
        # angekommen ist.
        # Geholt, nicht gebaut: Dieselben Klänge braucht auch die
        # Werkzeugschleife, wenn der Orb ein Programm startet. Zwei eigene
        # Sätze hiessen zwei Player und beim Suchen eines fehlenden Klangs
        # zwei Orte statt einem.
        from backend.audio.sounds import klaenge

        self._klaenge = klaenge()

        self._tts = TtsManager()

        self._player = AudioPlayer(
            on_level=self._on_playback_level,
            on_started=self._on_playback_started,
            on_finished=self._on_playback_finished,
        )

        self._capture = AudioCapture(
            self._on_utterance,
            on_interruption=self._on_interruption,
            on_stop_window=self._on_stop_window,
            stop_window_ms=float(config.get("voice.stop_window_ms", 1200)),
            interruption_hold_ms=float(config.get("voice.barge_in_hold_ms", 270)),
            device=config.get("voice.input.microphone", None),
            preroll_ms=float(config.get("voice.input.preroll_ms", 400)),
            silence_ms=float(config.get("voice.input.silence_ms", 900)),
            threshold_factor=float(config.get("voice.input.threshold_factor", 3.0)),
            minimum_speech_ms=float(config.get("voice.input.minimum_speech_ms", 350)),
            max_utterance_seconds=float(config.get("voice.input.max_utterance_seconds", 20)),
        )

        # --- Zustand ------------------------------------------------------------------
        self._state = VoiceState.OFF
        self._awake_until = 0.0

        #: Gesetzt, sobald der Benutzer dem Orb ins Wort gefallen ist.
        #:
        #: Wird vom Aufnahme-Thread gesetzt und in der Sprechschleife
        #: gelesen – deshalb ein Ereignis und kein einfaches Wahrheitswert-
        #: Feld.
        self._interrupted = threading.Event()
        #: Die Woerter, die der Orb gerade sagt - fuer den Echo-Test.
        self._gesprochene_woerter: set[str] = set()
        #: Die Wortmengen der zuletzt gesprochenen Saetze.
        #:
        #: Frueher stand hier ein einziger Vorgaengersatz. Das reichte
        #: nicht: Das Echo im Mikrofon hinkt der Ausgabe nach, und wie weit,
        #: haengt an der Puffergroesse der Soundkarte. Faellt ein
        #: Hoerfenster auf einen Satz, der schon zwei Saetze zurueckliegt,
        #: kennt der Orb dessen Woerter nicht mehr - und haelt sich selbst
        #: fuer einen Fremden. Genau so unterbrach er sich selbst.
        self._letzte_saetze: deque[set[str]] = deque(maxlen=ECHO_SAETZE)
        #: Ob gerade ein Hörfenster erkannt wird – Fenster, die währenddessen
        #: eintreffen, werden verworfen statt gestaut.
        self._stop_check_busy = False
        #: Gesetzt, sobald Spracherkennung UND Sprachausgabe geladen sind.
        #:
        #: Der Orb meldete bisher „Ich bin bereit", sobald der Kern stand –
        #: das Whisper-Modell lud danach noch mehrere Sekunden. Wer sofort
        #: etwas sagte, wartete trotz Bereitmeldung. Die Meldung war damit
        #: ein Versprechen, das erst später eingelöst wurde.
        self._warmed_up = asyncio.Event()
        #: Sprechsperre: verhindert, dass sich zwei Reden ineinander schieben.
        self._speech_lock = asyncio.Lock()
        #: Kurze Atempause zwischen zwei Sätzen. Die Satz-Vorbereitung hat
        #: die Lücken zwischen Sätzen technisch beseitigt – ganz ohne Pause
        #: klingt das aber gehetzt. Ein Mensch atmet zwischen Sätzen.
        self._sentence_pause = max(
            0.0, float(config.get("voice.output.sentence_pause_ms", 180)) / 1000.0
        )
        self._history: list[VoiceTurn] = []
        self._max_history = int(config.get("voice.max_history", 50))
        self._last_error = ""
        self._speaking_task: asyncio.Task[None] | None = None
        self._processing = False
        #: Die gerade laufende Antwort-Aufgabe - damit ein "Stop" sie auch
        #: WAEHREND des Denkens abbrechen kann, nicht erst beim Sprechen.
        self._antwort_task: asyncio.Task | None = None

    # --- Lebenszyklus ------------------------------------------------------------------

    @property
    def state(self) -> VoiceState:
        """Der aktuelle Zustand."""

        return self._state

    @property
    def is_running(self) -> bool:
        """Ob das Mikrofon läuft."""

        return self._capture.is_running

    @property
    def is_awake(self) -> bool:
        """Ob der Orb gerade auf Anweisungen hört."""

        return self._state in (VoiceState.LISTENING, VoiceState.THINKING, VoiceState.SPEAKING)

    async def start(self) -> bool:
        """Startet die Sprachsteuerung.

        Vor dem Öffnen des Mikrofons wird die Erlaubnis eingeholt – ein
        Assistent, der ungefragt mithört, wäre genau das, was die
        Sicherheitsvorgaben ausschließen.

        Returns:
            ``True``, wenn zugehört wird.
        """

        if not self._enabled:
            self._last_error = "Die Sprachsteuerung ist in config.yaml ausgeschaltet."
            logger.info(self._last_error)
            return False

        if self._capture.is_running:
            return True

        self._loop = self._loop or asyncio.get_running_loop()

        decision = await self._security.require(
            "voice",
            "microphone",
            "Dauerhaft auf das Weckwort '"
            + "', '".join(self._wake_word.phrases)
            + "' hören. Es wird nichts aufgezeichnet und nichts übertragen, "
            "solange das Weckwort nicht gefallen ist.",
            context={"always_on": self._always_on},
        )

        if not decision.allowed:
            self._last_error = decision.reason
            logger.warning("Die Sprachsteuerung wurde nicht freigegeben: %s", decision.reason)
            await self._publish_state()
            return False

        problems = self._check_requirements()
        if problems:
            self._last_error = problems
            logger.error(problems)
            await self._publish_state()
            return False

        if not self._capture.start():
            self._last_error = (
                "Das Mikrofon ließ sich nicht öffnen. Prüfe unter "
                "Windows-Einstellungen → Datenschutz → Mikrofon, ob der Zugriff "
                "erlaubt ist."
            )
            await self._publish_state()
            return False

        self._last_error = ""
        await self._set_state(VoiceState.SLEEPING)
        self._security.record_action(
            "voice", "microphone", "Mikrofon geöffnet, wartet auf das Weckwort."
        )

        # Modelle im Hintergrund vorwärmen, damit die erste Antwort nicht
        # spürbar länger dauert als alle folgenden.
        asyncio.create_task(self._warm_up(), name="ai-orb-voice-warmup")

        logger.info(
            "Sprachsteuerung aktiv. Sag '%s', um mich anzusprechen.",
            self._wake_word.phrases[0] if self._wake_word.phrases else "Hallo Orb",
        )
        return True

    async def stop(self) -> None:
        """Beendet die Sprachsteuerung und gibt das Mikrofon frei."""

        self._player.stop()
        if self._speaking_task is not None and not self._speaking_task.done():
            self._speaking_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._speaking_task
        self._speaking_task = None

        await asyncio.to_thread(self._capture.stop)
        self._capture.cleanup(keep_last=0)
        await self._set_state(VoiceState.OFF)
        self._security.record_action("voice", "microphone", "Mikrofon freigegeben.")

    def _check_requirements(self) -> str:
        """Prüft, ob alles Nötige vorhanden ist. Leerer Text heißt: alles gut."""

        missing: list[str] = []

        if not AudioCapture.is_available():
            missing.append(AudioCapture.installation_hint())
        if not Transcriber.is_available():
            missing.append(Transcriber.installation_hint())
        if not AudioPlayer.is_available():
            missing.append(AudioPlayer.installation_hint())
        if not self._tts.available_engines():
            missing.append(self._tts.diagnose())

        if not missing:
            return ""
        return "Die Sprachsteuerung ist noch nicht einsatzbereit:\n" + "\n".join(missing)

    async def _warm_up(self) -> None:
        """Lädt Erkennung und Ausgabe im Hintergrund vor."""

        try:
            await self._transcriber.preload()
            await self._tts.preload()
        except Exception:  # noqa: BLE001 - das Vorwärmen darf nichts abbrechen.
            logger.exception("Das Vorwärmen der Sprachmodelle ist fehlgeschlagen.")
        finally:
            # Auch nach einem Fehlschlag freigeben: Lieber sprechen, als
            # wegen eines misslungenen Vorwärmens für immer zu schweigen.
            self._warmed_up.set()
            logger.info("Spracherkennung und Sprachausgabe sind bereit.")

        # Das kleine Stop-Modell danach und ausdrücklich NACH der
        # Bereitmeldung: Es wird erst gebraucht, wenn der Orb spricht, und
        # beim allerersten Start muss es womöglich noch geladen werden. Das
        # darf die Bereitmeldung nicht aufhalten – sie soll ehrlich bleiben,
        # aber nicht länger dauern als nötig.
        try:
            await self._stop_transcriber.preload()
            logger.info("Die Stop-Wort-Erkennung ist bereit.")
        except Exception:  # noqa: BLE001
            logger.exception("Das kleine Stop-Modell ließ sich nicht laden.")

    # --- Aufnahme (läuft im Audio-Thread) ---------------------------------------------

    def _on_interruption(self) -> None:
        """Der Benutzer spricht, während der Orb spricht.

        Läuft im Aufnahme-Thread und muss deshalb kurz sein. Die
        Wiedergabe wird sofort gestoppt und das Mikrofon wieder
        freigegeben, damit vom Gesagten möglichst wenig verlorengeht –
        wer unterbricht, will in aller Regel sofort etwas loswerden.
        """

        if not self._barge_in:
            return

        if not self._player.is_playing:
            return

        self._interrupted.set()
        self._player.stop()
        self._capture.mute(False)

        logger.info("Der Benutzer ist dazwischengegangen – der Orb hört auf zu sprechen.")

    def _on_stop_window(self, path: Path) -> None:
        """Bekommt während des Sprechens ein kurzes Hörfenster.

        Läuft im Aufnahme-Thread – hier wird nur threadsicher an die
        Kern-Loop übergeben.
        """

        if self._loop is None or not self._listening_for_stop:
            path.unlink(missing_ok=True)
            return
        asyncio.run_coroutine_threadsafe(self._check_stop_window(path), self._loop)

    async def _check_stop_window(self, window: Path) -> None:
        """Prüft ein Hörfenster auf das Stop-Wort.

        Warum das nötig ist: Die gewöhnliche Äußerungserkennung wartet auf
        Stille – und solange der Orb spricht, hört das Mikrofon seine
        eigene Stimme und findet keine. Ein „stop" mitten in der Antwort
        landete deshalb in einer Endlos-Aufnahme, die erst nach der Antwort
        fertig wurde – zu spät. Die Hörfenster sind kurz (etwa eine
        Sekunde), werden sofort erkannt, und das Stop-Wort greift, solange
        es noch etwas zu unterbrechen gibt.

        Ist die Erkennung mit dem vorigen Fenster noch beschäftigt, wird
        das neue Fenster nicht verworfen, sondern gemerkt und direkt danach
        geprüft. Vorher flogen bei langsamer Erkennung fast alle Fenster
        raus – und mit ihnen das „stop". Gemerkt wird immer nur das
        NEUESTE: Ein Stau alter Fenster würde die Erkennung immer weiter
        hinter die Gegenwart zurückfallen lassen.

        Wer hier etwas ändert, achte auf die Dateien: Ein gemerktes Fenster
        darf erst gelöscht werden, wenn es geprüft oder überholt ist. Ein zu
        frühes Löschen war der Grund, warum die Erkennung auf Dateien lief,
        die es nicht mehr gab.
        """

        if not self._listening_for_stop or self._interrupted.is_set():
            window.unlink(missing_ok=True)
            return

        if self._stop_check_busy:
            veraltet = self._pending_stop_window
            self._pending_stop_window = window
            if veraltet is not None and veraltet != window:
                veraltet.unlink(missing_ok=True)
            return

        self._stop_check_busy = True
        try:
            aktuell: Path | None = window
            while aktuell is not None:
                try:
                    if not self._listening_for_stop or self._interrupted.is_set():
                        return

                    # Spricht der Benutzer selbst, hört der Orb auf – ganz
                    # gleich, was er sagt.
                    #
                    # Möglich wird das erst durch die Stimmerkennung, und
                    # zwar aus einem Grund, der vorher unüberwindbar war:
                    # Das Mikrofon hört während des Sprechens vor allem den
                    # Orb selbst. Ohne zu wissen, WESSEN Stimme da liegt,
                    # hätte jede Silbe seiner eigenen Antwort ihn
                    # unterbrochen. Die Prüfung trennt beides – seine
                    # Stimme aus dem Lautsprecher gleicht der hinterlegten
                    # nicht.
                    #
                    # Ohne hinterlegte Stimme bleibt es beim Stop-Wort:
                    # Dann wäre nicht zu unterscheiden, wer da redet.
                    # BEIDE Pruefungen, nicht die eine ODER die andere.
                    #
                    # Hier stand vorher, dass die Stimmerkennung benutzt
                    # wird, WENN eine Stimme hinterlegt ist - und der
                    # Wortvergleich nur sonst. Das war ein Denkfehler, und
                    # er machte das Hinterlegen der Stimme zum Nachteil:
                    #
                    # Das Hoerfenster ist gut eine Sekunde lang und
                    # enthaelt waehrend des Sprechens vor allem den ORB.
                    # Eine kurze Zwischenbemerkung des Benutzers geht darin
                    # unter, die Aehnlichkeit bleibt unter der Schwelle -
                    # und weil eine Stimme hinterlegt war, kam der
                    # Wortvergleich gar nicht mehr zum Zug. Wer seine
                    # Stimme hinterlegte, konnte den Orb also SCHLECHTER
                    # unterbrechen als vorher.
                    #
                    # Jetzt genuegt, dass eine der beiden Pruefungen
                    # anschlaegt. Beide beantworten dieselbe Frage - ist
                    # das da drin jemand anderes als ich selbst? - nur auf
                    # verschiedenen Wegen, und ein Ja von einer reicht.
                    if self._interrupt_on_speech and self._stimme.aktiv:
                        urteil = self._stimme.pruefen(aktuell)
                        # Fuer den ABBRUCH zaehlt nicht die (niedrige)
                        # Akzeptanzschwelle, sondern eine eigene, HOHE:
                        # sonst bricht das eigene Echo die Antwort ab.
                        schwelle = getattr(self, "_barge_in_min_aehnlichkeit", 0.82)
                        if urteil.geprueft and urteil.aehnlichkeit >= schwelle:
                            logger.info(
                                "Der Benutzer spricht deutlich dazwischen "
                                "(Ähnlichkeit %.2f ≥ %.2f) – die Sprachausgabe "
                                "wird beendet.",
                                urteil.aehnlichkeit,
                                schwelle,
                            )
                            self.interrupt()
                            return
                    # Ließ sich das kleine Modell nicht laden, lieber
                    # langsam hinhören als gar nicht: dann übernimmt das
                    # große. Ein spätes „stop" ist besser als keines.
                    erkennung = (
                        self._transcriber
                        if self._stop_transcriber.load_failed
                        else self._stop_transcriber
                    )
                    transcript = await erkennung.transcribe(aktuell)
                    if self._listening_for_stop and self._contains_stop_word(
                        transcript.text
                    ):
                        logger.info("Stop-Wort erkannt – Sprachausgabe wird beendet.")
                        self.interrupt()
                        return

                    # Der Vergleich mit dem eigenen Satz – jetzt IMMER,
                    # nicht nur ohne hinterlegte Stimme. Er ist gröber als
                    # die Stimmerkennung und faengt genau das, was ihr
                    # entgeht: die kurze Zwischenbemerkung, die im
                    # Hoerfenster neben der eigenen Stimme untergeht.
                    if self._listening_for_stop and self._interrupt_on_speech:
                        # Schlecht erkannte Fenster zaehlen gar nicht erst.
                        # In ihnen erfindet die Erkennung, und Erfundenes
                        # sah bisher aus wie ein Zwischenruf.
                        sicher = (
                            transcript.confidence >= self._fremd_mindestsicherheit
                        )
                        if sicher and self._ist_fremde_rede(transcript.text):
                            self._fremd_folge += 1
                        else:
                            self._fremd_folge = 0

                        if self._fremd_folge >= self._fremd_fenster_noetig:
                            logger.info(
                                "Fremde Worte in %d Hörfenstern in Folge "
                                "(%r, Sicherheit %.2f) – die Sprachausgabe "
                                "wird beendet.",
                                self._fremd_folge,
                                transcript.text[:60],
                                transcript.confidence,
                            )
                            self.interrupt()
                            return
                        if self._fremd_folge:
                            logger.debug(
                                "Möglicher Zwischenruf (%d/%d): %r",
                                self._fremd_folge,
                                self._fremd_fenster_noetig,
                                transcript.text[:60],
                            )
                except Exception:  # noqa: BLE001 - der Späher darf nie den Kern reissen.
                    logger.exception("Das Hörfenster ließ sich nicht prüfen.")
                finally:
                    aktuell.unlink(missing_ok=True)

                # Ist während der Erkennung ein neues Fenster eingetroffen,
                # gleich weitermachen – sonst entstünde genau dort die Lücke,
                # in die das „stop" fällt.
                aktuell = self._pending_stop_window
                self._pending_stop_window = None
        finally:
            self._stop_check_busy = False
            rest = self._pending_stop_window
            self._pending_stop_window = None
            if rest is not None:
                rest.unlink(missing_ok=True)

    def _on_utterance(self, path: Path, duration: float) -> None:
        """Wird vom Aufnahme-Thread für jede erkannte Äußerung aufgerufen.

        Hier wird nichts verarbeitet – nur threadsicher in die Kern-Loop
        übergeben. Der Audio-Thread darf nicht warten.
        """

        if self._loop is None:
            return

        # Redet der Benutzer, während der Orb spricht, bricht die Wiedergabe
        # sofort ab. Das geschieht hier und nicht in der Loop, damit es ohne
        # Verzögerung greift.
        if self._barge_in and self._player.is_playing:
            self._player.stop()
            logger.debug("Wiedergabe abgebrochen – der Benutzer spricht.")

        asyncio.run_coroutine_threadsafe(self._handle_utterance(path, duration), self._loop)

    # --- Verarbeitung (läuft in der Kern-Loop) ------------------------------------------

    async def _handle_utterance(self, path: Path, duration: float) -> None:
        """Verarbeitet eine aufgenommene Äußerung."""

        started = time.perf_counter()
        turn = VoiceTurn(duration_seconds=duration)

        try:
            # Solange der Orb spricht, gilt nur eine Frage: Fiel das
            # Stop-Wort? Alles andere wird überhört – auch die eigene
            # Stimme des Orb, die das Mikrofon mithört. Deshalb wird hier
            # trotz laufender Ausgabe transkribiert, aber nichts als Befehl
            # ausgeführt.
            if self._listening_for_stop:
                transcript = await self._transcriber.transcribe(path)
                if self._contains_stop_word(transcript.text):
                    logger.info("Stop-Wort erkannt – Sprachausgabe wird beendet.")
                    self.interrupt()
                return

            if self._processing:
                # Ein kurzes "Stop" bricht den LAUFENDEN Auftrag ab - das
                # war das Loch, durch das jedes "Stop" während des Denkens
                # fiel: Die Äußerung wurde hier kommentarlos verworfen, der
                # Orb dachte weiter und redete Sekunden später los.
                if await self._ist_kurzer_stop(path, duration):
                    logger.info(
                        "Stop-Wort während der Verarbeitung – der laufende "
                        "Auftrag wird abgebrochen."
                    )
                    self.verarbeitung_abbrechen()
                    return
                # Während eine Anweisung läuft, wird die nächste verworfen.
                # Zwei gleichzeitige Aufträge würden nur durcheinandergehen.
                logger.debug("Äußerung übergangen – es läuft bereits eine.")
                return

            # Wird gerade die Stimme gelernt, ist diese Aufnahme eine Probe
            # und keine Anweisung.
            if self._stimme_lernt is not None:
                await self._stimme_sammeln(path)
                return

            # Die Stimmprüfung steht VOR der Spracherkennung, und das ist
            # kein Zufall: Sie kostet Millisekunden, die Erkennung Sekunden.
            # Was von einer fremden Stimme kommt, wird gar nicht erst
            # verstanden – das spart Rechenzeit und ist zugleich die
            # sauberere Trennung: Der Satz eines Fremden wird nirgends
            # aufgeschrieben.
            urteil = self._stimme.pruefen(path)
            if not urteil.akzeptiert:
                # Die Notbremse gilt auch hier: Ein kurzer Ausruf wie
                # "Stop!" liefert zu wenig Stimme für einen verlässlichen
                # Abdruck und fiel im Protokoll des Benutzers reihenweise
                # durch die Prüfung (Ähnlichkeit 0.3-0.5). Stoppen ist
                # gefahrlos - schlimmstenfalls verstummt der Orb -, also
                # darf es nicht an der Identität scheitern.
                if await self._ist_kurzer_stop(path, duration):
                    logger.info(
                        "Stop-Wort trotz nicht erkannter Stimme – die "
                        "Notbremse greift."
                    )
                    self.verarbeitung_abbrechen()
                    return
                logger.info(
                    "Fremde Stimme überhört (Ähnlichkeit %.2f, Schwelle %.2f).",
                    urteil.aehnlichkeit,
                    urteil.schwelle,
                )
                await self._event_bus.publish("voice.speaker.rejected", urteil.to_dict())
                return

            # Ab hier ist klar: Der Benutzer hat gesprochen, und es ist
            # wirklich er. Was er vorher unterbrochen hat, ist damit
            # abgeschlossen - die naechste Rede darf wieder sprechen.
            self._neue_rede()

            transcript = await self._transcriber.transcribe(path)
            turn.transcript = transcript.text
            turn.confidence = transcript.confidence

            if transcript.is_empty:
                return

            # Auf "info" und nicht auf "debug".
            #
            # Das stand auf "debug" und war damit unsichtbar. Als der
            # Benutzer sagte, der Orb verstehe ihn schlecht, liess sich das
            # deshalb nicht nachsehen: Im Protokoll stand, WANN etwas
            # ankam, aber nie WAS. Eine Fehlerkennung, die man nicht sieht,
            # kann man auch nicht beheben - man kann nur an Einstellungen
            # drehen und hoffen.
            logger.info(
                "Verstanden (%.2f): %s", transcript.confidence, transcript.text
            )

            # Kauderwelsch gar nicht erst weiterreichen.
            #
            # Whisper verhakt sich gelegentlich und wiederholt dasselbe
            # Wort ("ruhig ruhig ruhig ruhig ruhig") - ein bekanntes
            # Verhalten, das mit dem Gesagten nichts zu tun hat. Solche
            # Aeusserungen sind kein Befehl und auch keine Nachfrage wert.
            if _ist_geplapper(transcript.text):
                logger.info("Verworfen: Wortwiederholung ohne Inhalt.")
                return

            await self._event_bus.publish(
                event_types.SPEECH_TRANSCRIBED,
                {
                    "text": transcript.text,
                    "confidence": round(transcript.confidence, 3),
                    "awake": self.is_awake,
                },
            )

            if self._is_asleep():
                await self._handle_while_asleep(transcript, turn)
            else:
                await self._handle_while_awake(transcript, turn)

        except Exception:  # noqa: BLE001 - die Sprachsteuerung darf nie abstürzen.
            logger.exception("Fehler bei der Verarbeitung einer Äußerung.")
            self._last_error = "Bei der Verarbeitung ist etwas schiefgegangen."
        finally:
            # Die Aufnahme wird nicht aufbewahrt. Vorgabe: Keine
            # Mikrofonaufnahmen werden dauerhaft gespeichert.
            with contextlib.suppress(OSError):
                path.unlink()
            turn.duration_seconds = time.perf_counter() - started
            self._remember(turn)

    # --- Die Stimme lernen ----------------------------------------------------

    async def stimme_lernen_starten(self) -> str:
        """Beginnt, sich die Stimme des Benutzers zu merken.

        Die nächsten Aufnahmen gelten dann als Proben und nicht als
        Anweisungen. Gesammelt werden mehrere, nicht eine – aus einer
        einzigen liesse sich nicht abschätzen, wie sehr die eigene Stimme
        von Mal zu Mal schwankt, und genau daraus entsteht die Schwelle,
        ab der eine Stimme als bekannt gilt.
        """

        self._stimme_lernt = []
        self._stimme_rueckweisungen = 0
        anzahl = max(2, self._stimme_anzahl)
        return (
            f"Ich höre jetzt genau hin. Sag mir bitte {anzahl} ganze Sätze, "
            "einen nach dem anderen – der Inhalt ist gleichgültig, es geht "
            "nur um den Klang. Jeder sollte ein paar Sekunden dauern."
        )

    async def stimme_neu_einlernen(self) -> str:
        """Lernt die Stimme SAUBER neu – erst vergessen, dann frisch sammeln.

        Der Unterschied zum gewöhnlichen Lernen liegt im Vorher: Ein altes,
        womöglich verrutschtes Profil wird zuerst gelöscht, damit es sich
        nicht mit den neuen Aufnahmen mischt. Danach ist der Ablauf derselbe,
        nur dass jede Probe sofort auf Brauchbarkeit geprüft wird.
        """

        if self._stimme.gelernt:
            self._stimme.vergessen()
        beginn = await self.stimme_lernen_starten()
        return "Ich fange mit deiner Stimme noch einmal von vorn an. " + beginn

    def stimme_lernen_abbrechen(self) -> str:
        """Bricht das Lernen ab, ohne etwas zu ändern."""

        self._stimme_aufraeumen()
        return "Gut, ich lasse es. Deine hinterlegte Stimme bleibt, wie sie war."

    def stimme_vergessen(self) -> str:
        """Löscht das Stimmprofil – danach hört der Orb wieder auf jeden."""

        self._stimme_aufraeumen()
        return self._stimme.vergessen()

    def stimme_status(self) -> dict[str, Any]:
        """Was über die hinterlegte Stimme bekannt ist."""

        status = self._stimme.status()
        status["lernt_gerade"] = self._stimme_lernt is not None
        status["gesammelt"] = len(self._stimme_lernt or [])
        status["benoetigt"] = max(2, self._stimme_anzahl)
        return status

    async def _stimme_sammeln(self, path: Path) -> None:
        """Nimmt eine Probe entgegen und lernt, sobald genug beisammen sind."""

        if self._stimme_lernt is None:
            return

        from backend.utils.paths import get_data_dir

        ordner = get_data_dir() / "stimmproben"
        try:
            ordner.mkdir(parents=True, exist_ok=True)
            # Kopieren, nicht verschieben: Die Aufnahme wird gleich nach der
            # Verarbeitung gelöscht (es werden grundsätzlich keine
            # Mikrofonaufnahmen aufbewahrt), und diese Kopie überlebt nur
            # bis zum Ende des Lernens.
            ziel = ordner / f"probe-{len(self._stimme_lernt) + 1}.wav"
            ziel.write_bytes(path.read_bytes())
        except OSError as fehler:
            logger.error("Die Stimmprobe ließ sich nicht ablegen: %s", fehler)
            self._stimme_aufraeumen()
            await self._say(
                "Ich konnte die Aufnahme nicht ablegen und breche das Lernen ab."
            )
            return

        # Jede Probe wird SOFORT geprüft, nicht erst am Ende.
        #
        # Das ist der Kern des sauberen Wiedereinlernens: Früher wurde jede
        # Aufnahme gezählt und erst nach der letzten festgestellt, dass zwei
        # davon zu kurz oder zu leise waren - dann musste alles von vorn
        # beginnen. Jetzt sagt der Orb bei genau der Probe, die nichts taugt,
        # dass sie zu wiederholen ist, und zählt sie nicht mit.
        from backend.voice.speaker_id import abdruck

        brauchbar = True
        try:
            if abdruck(ziel) is None:
                brauchbar = False
        except Exception as fehler:  # noqa: BLE001 - eine schlechte Probe darf nie abbrechen.
            logger.debug("Stimmprobe nicht auswertbar: %s", fehler)
            brauchbar = False

        if not brauchbar:
            with contextlib.suppress(OSError):
                ziel.unlink()
            self._stimme_rueckweisungen += 1
            # Nach drei erfolglosen Versuchen wird nachgegeben: Die Probe wird
            # doch genommen, damit niemand endlos wiederholt. Das ehrliche
            # Urteil fällt dann beim eigentlichen Lernen.
            if self._stimme_rueckweisungen < 3:
                await self._say(
                    "Diese Aufnahme war zu kurz oder zu leise, um deine Stimme "
                    "darin zu erkennen. Sag den Satz bitte noch einmal - ruhig "
                    "etwas länger und in normaler Lautstärke.",
                    emotion="freundlich",
                )
                return
            # Nachgeben: doch aufnehmen.
            try:
                ziel.write_bytes(path.read_bytes())
                self._stimme_lernt.append(ziel)
            except OSError:
                self._stimme_aufraeumen()
                await self._say("Ich konnte die Aufnahme nicht ablegen und höre auf.")
                return
        else:
            # Brauchbare Probe: mitzählen und den Rückweiser-Zähler leeren.
            self._stimme_lernt.append(ziel)
            self._stimme_rueckweisungen = 0

        noch = max(2, self._stimme_anzahl) - len(self._stimme_lernt)

        if noch > 0:
            await self._say(
                "Danke, noch einen Satz." if noch == 1 else f"Danke, noch {noch} Sätze."
            )
            return

        proben = list(self._stimme_lernt)
        geklappt, meldung = self._stimme.lernen(proben)
        self._stimme_aufraeumen()

        await self._event_bus.publish("voice.speaker.enrolled", self._stimme.status())
        await self._say(meldung)

        if not geklappt:
            logger.warning("Die Stimme ließ sich nicht lernen: %s", meldung)

    def _stimme_aufraeumen(self) -> None:
        """Räumt die Proben weg und beendet das Lernen.

        Die Proben sind Mikrofonaufnahmen; sie bleiben nur so lange liegen,
        wie sie gebraucht werden. Der Abdruck im Profil ist eine Handvoll
        Zahlen, aus denen sich keine Sprache zurückgewinnen lässt.
        """

        for probe in self._stimme_lernt or []:
            with contextlib.suppress(OSError):
                probe.unlink()
        self._stimme_lernt = None
        self._stimme_rueckweisungen = 0

    #: Saetze, die das Hinterlegen der Stimme ausloesen.
    #:
    #: Bewusst mehrere Formulierungen, weil niemand den einen richtigen Satz
    #: raet. Geprueft wird auf Teilzeichenketten und nicht auf Gleichheit:
    #: "Kannst du dir bitte meine Stimme merken?" soll ebenso greifen wie
    #: der nackte Befehl.
    _STIMME_LERNEN = (
        "meine stimme lernen",
        "lerne meine stimme",
        "lern meine stimme",
        "meine stimme merken",
        "merk dir meine stimme",
        "merke dir meine stimme",
        "stimme hinterlegen",
        "hinterlege meine stimme",
        "meine stimme hinterlegen",
        "stimme einlernen",
    )

    #: Saetze, die die Stimme SAUBER neu einlernen - erst vergessen, dann neu.
    #: Bewusst vor dem gewoehnlichen Lernen geprueft, weil "lern meine stimme
    #: neu" sonst schon von "lern meine stimme" gefangen wuerde.
    _STIMME_NEU = (
        "stimme neu einlernen",
        "stimme neu lernen",
        "stimme neu einrichten",
        "lern meine stimme neu",
        "lerne meine stimme neu",
        "meine stimme neu einlernen",
        "meine stimme neu lernen",
        "stimme sauber neu",
        "stimme noch einmal einlernen",
        "stimme nochmal einlernen",
    )

    #: Saetze, die das Hinterlegte wieder loeschen.
    _STIMME_VERGESSEN = (
        "meine stimme vergessen",
        "vergiss meine stimme",
        "stimme loeschen",
        "stimme löschen",
        "lösche meine stimme",
    )

    #: Saetze, die nach dem Stand fragen.
    _STIMME_STATUS = (
        "kennst du meine stimme",
        "stimme status",
        "status meiner stimme",
        "hast du meine stimme",
    )

    async def _stimme_befehl(self, text: str) -> bool:
        """Behandelt die Saetze rund um die hinterlegte Stimme.

        Returns:
            Ob der Satz einer davon war und behandelt wurde.
        """

        klein = text.lower()

        # Das saubere Neu-Einlernen zuerst - es enthaelt die Woerter des
        # gewoehnlichen Lernens und wuerde sonst von ihm gefangen.
        if any(satz in klein for satz in self._STIMME_NEU):
            await self._say(await self.stimme_neu_einlernen(), emotion="freundlich")
            return True

        if any(satz in klein for satz in self._STIMME_LERNEN):
            await self._say(await self.stimme_lernen_starten(), emotion="freundlich")
            return True

        if any(satz in klein for satz in self._STIMME_VERGESSEN):
            await self._say(self.stimme_vergessen(), emotion="freundlich")
            return True

        if any(satz in klein for satz in self._STIMME_STATUS):
            stand = self.stimme_status()
            if stand.get("lernt_gerade"):
                await self._say(
                    f"Ich sammle gerade. {stand['gesammelt']} von "
                    f"{stand['benoetigt']} Sätzen habe ich."
                )
            elif stand.get("gelernt"):
                await self._say(
                    f"Ja. Ich habe deine Stimme aus {stand['aufnahmen']} "
                    "Aufnahmen hinterlegt und höre nur auf dich."
                )
            else:
                await self._say(
                    "Nein, noch nicht. Sag: lerne meine Stimme. Dann "
                    "hinterlege ich sie."
                )
            return True

        return False

    def _is_asleep(self) -> bool:
        """Ob das Weckwort nötig ist."""

        if self._state is VoiceState.SLEEPING:
            return True
        return time.time() > self._awake_until and self._state is not VoiceState.THINKING

    async def _handle_while_asleep(self, transcript: Transcript, turn: VoiceTurn) -> None:
        """Prüft eine Äußerung auf das Weckwort.

        Der Text wird hier nicht weitergegeben. Fällt das Weckwort nicht,
        endet die Verarbeitung – nichts geht an die KI, nichts wird
        gespeichert.
        """

        match = self._wake_word.detect(transcript.text)
        if not match.detected:
            return

        turn.woke = True
        logger.info("Weckwort erkannt (%.0f %%): '%s'", match.score * 100, match.phrase)

        self._wake()
        await self._event_bus.publish(
            "voice.wake_word.detected",
            {"phrase": match.phrase, "score": round(match.score, 3), "command": match.command},
        )

        if match.has_command:
            # „Hallo Orb, wie spät ist es?" – gleich weiterarbeiten, statt
            # nachzufragen.
            await self._respond(match.command, turn)
        elif self._acknowledge:
            await self._set_state(VoiceState.LISTENING)
            await self._say(self._acknowledge_text, emotion="aufmerksam")
            self._wake()
        else:
            await self._set_state(VoiceState.LISTENING)

    # --- Diktiermodus ------------------------------------------------------------

    _DIKTAT_AUSLOESER = (
        "diktier", "diktat", "nimm ein diktat", "diktiere mir", "diktiermodus",
    )

    async def _nichts_sprechen(self, *args: Any, **kwargs: Any) -> bool:
        """Ein on_speech, das nichts spricht - fuers stille Erzeugen des Textes."""

        return False

    async def _diktat_befehl(self, text: str) -> bool:
        """Startet den Diktiermodus, wenn der Benutzer darum bittet."""

        klein = text.lower()
        if not any(a in klein for a in self._DIKTAT_AUSLOESER):
            return False
        thema = self._diktat_thema(text)
        await self._diktat_starten(thema)
        return True

    @staticmethod
    def _diktat_thema(text: str) -> str:
        """Zieht das Thema aus 'diktiere mir das Vorgehen zu X' heraus."""

        rest = text
        for stich in (
            "diktiere mir bitte", "diktier mir bitte", "diktiere mir",
            "diktier mir", "nimm ein diktat ueber", "nimm ein diktat über",
            "diktiermodus", "diktiere", "diktier", "diktat über", "diktat ueber",
            "diktat zu", "diktat",
        ):
            idx = rest.lower().find(stich)
            if idx != -1:
                rest = rest[idx + len(stich):]
                break
        # Fuellwoerter am Anfang wegnehmen.
        rest = rest.strip(" ,:-")
        for vor in ("mir", "bitte", "ein", "das thema", "das", "die", "der", "über", "ueber", "zu", "zum", "zur"):
            if rest.lower().startswith(vor + " "):
                rest = rest[len(vor):].strip()
        return rest.strip(" ,:-.")

    async def _diktat_starten(self, thema: str) -> None:
        """Erzeugt den Diktattext und beginnt mit der Tempo-Messung."""

        if not thema:
            await self._say("Worüber soll ich dir diktieren?", emotion="fragend")
            return

        await self._say("Einen Moment, ich bereite das Diktat vor.", emotion="freundlich")

        auftrag = (
            f"Erstelle einen klar gegliederten, sachlichen Text zum DIKTIEREN "
            f"über: {thema}. Er wird laut vorgelesen und von Hand mitgeschrieben. "
            "Nimm vollständige, eher kurze Sätze in sinnvoller Reihenfolge. "
            "Keine Aufzählungszeichen, keine Überschriften, keine Klammern, keine "
            "Emojis - reiner Fließtext. Beginne direkt mit dem Inhalt."
        )
        self._processing = True
        try:
            inhalt, _ = await self._answer(auftrag, on_speech=self._nichts_sprechen)
        except Exception:  # noqa: BLE001 - der Diktatstart darf den Orb nie reissen.
            logger.exception("Der Diktattext liess sich nicht erzeugen.")
            await self._say(
                "Ich konnte den Text für das Diktat gerade nicht vorbereiten.",
                emotion="nachdenklich",
            )
            return
        finally:
            self._processing = False

        inhalt = (inhalt or "").strip()
        if not inhalt:
            await self._say(
                "Mir fällt dazu gerade kein Text zum Diktieren ein.",
                emotion="nachdenklich",
            )
            return

        self._diktat = Diktierer(ziel_sekunden=self._diktat_ziel_sekunden)
        self._diktat.beginnen(inhalt)
        self._diktat_phase = "kalibrierung"
        await self._say(
            "Wir messen zuerst kurz dein Schreibtempo. Schreib diesen Satz mit, "
            "und sag 'weiter', sobald du fertig bist: " + KALIBRIERSATZ,
            emotion="freundlich",
        )
        # Die Zeit laeuft ab JETZT - erst nach dem gesprochenen Satz, damit
        # nur das Schreiben gemessen wird, nicht das Vorlesen.
        self._diktat_start = time.time()

    async def _diktat_weiter(self, text: str) -> None:
        """Verarbeitet eine Aeusserung, waehrend ein Diktat laeuft."""

        if self._diktat is None:
            return
        klein = text.lower()

        if any(w in klein for w in (
            "stopp", "stop", "beende", "abbrechen", "abbruch", "schluss",
            "hör auf", "hoer auf", "aufhören", "aufhoeren", "genug", "beenden",
        )):
            await self._diktat_beenden(freundlich=True)
            return

        if self._diktat_phase == "kalibrierung":
            if any(w in klein for w in ("weiter", "fertig", "hab ich", "habs", "hab es", "okay", "ok", "los", "bereit")):
                sekunden = max(0.5, time.time() - self._diktat_start)
                self._diktat.kalibrieren(len(KALIBRIERSATZ), sekunden)
                self._diktat_phase = "diktat"
                await self._say(
                    "Danke. Ich diktiere jetzt in deinem Tempo. Sag 'weiter' für "
                    "den nächsten Teil, oder 'nochmal', 'langsamer', 'schneller', "
                    "'stopp'.",
                    emotion="freundlich",
                )
                await self._diktat_abschnitt()
            else:
                await self._say(
                    "Sag 'weiter', sobald du den Satz aufgeschrieben hast.",
                    emotion="fragend",
                )
            return

        # Phase: Diktat laeuft.
        if any(w in klein for w in ("langsamer", "zu schnell", "nicht so schnell")):
            self._diktat.langsamer()
            await self._say("Gut, langsamer.", emotion="freundlich")
            await self._diktat_abschnitt(wiederholen=True)
            return
        if any(w in klein for w in ("schneller", "zu langsam", "geht schneller")):
            self._diktat.schneller()
            await self._say("Gut, schneller.", emotion="freundlich")
            return
        if any(w in klein for w in ("nochmal", "noch mal", "wiederhol", "noch einmal", "zurück", "zurueck")):
            await self._diktat_abschnitt(wiederholen=True)
            return
        if any(w in klein for w in ("weiter", "fertig", "nächstes", "naechstes", "hab ich", "habs", "okay", "ok", "los", "und dann", "bereit")):
            await self._diktat_abschnitt()
            return

        await self._say(
            "Sag 'weiter' für den nächsten Teil, oder 'nochmal', 'langsamer', "
            "'schneller', 'stopp'.",
            emotion="fragend",
        )

    async def _diktat_abschnitt(self, *, wiederholen: bool = False) -> None:
        """Diktiert den naechsten (oder denselben) Abschnitt - oder beendet."""

        if self._diktat is None:
            return
        stueck = self._diktat.wiederholen() if wiederholen else self._diktat.naechster_abschnitt()
        if not stueck:
            await self._say(
                "Das war der ganze Text. Fertig mit dem Diktat.",
                emotion="freundlich",
            )
            await self._diktat_beenden(freundlich=False)
            return
        await self._say(stueck)

    async def _diktat_beenden(self, *, freundlich: bool) -> None:
        """Beendet den Diktiermodus."""

        self._diktat = None
        self._diktat_phase = ""
        if freundlich:
            await self._say("Diktat beendet.", emotion="freundlich")

    async def _handle_while_awake(self, transcript: Transcript, turn: VoiceTurn) -> None:
        """Behandelt eine Anweisung im wachen Zustand."""

        # Ein erneutes Weckwort wird abgeschnitten, damit „Hallo Orb, und
        # jetzt …" nicht als Teil der Frage bei der KI landet.
        text = self._wake_word.strip_wake_word(transcript.text).strip()

        # Laeuft ein Diktat, gehen ALLE Aeusserungen an die Diktatsteuerung -
        # zuerst, noch vor der Laengen- und Sicherheitspruefung, weil die
        # Steuerworte kurz sind ("weiter", "stopp") und sicher durchkommen
        # muessen.
        if self._diktat is not None:
            self._wake()
            with contextlib.suppress(Exception):
                await self._diktat_weiter(text)
            return

        if len(text) < self._min_characters:
            self._wake()
            return

        # Nachfragen statt raten.
        #
        # Kurze Aeusserungen und das Stop-Wort bleiben ausgenommen: Sie
        # werden regelmaessig unsicher erkannt, und das Risiko einer
        # Fehlhandlung ist bei ihnen klein - schlimmstenfalls hoert der Orb
        # auf zu reden. Bei einem ganzen Satz dagegen fuehrt eine
        # Fehlerkennung zu einer Antwort auf etwas, das niemand gesagt hat.
        if (
            transcript.confidence < self._rueckfrage_unter
            and len(text.split()) >= 3
            and not self._contains_stop_word(text)
        ):
            logger.info(
                "Nur %.2f sicher - es wird nachgefragt statt geantwortet: %r",
                transcript.confidence,
                text[:80],
            )
            self._wake()
            await self._set_state(VoiceState.LISTENING)
            await self._say(self._rueckfrage_text, emotion="fragend")
            return

        # Die Stimme zu hinterlegen laeuft an der KI vorbei.
        #
        # Es gibt zwar ein Werkzeug dafuer, aber es zu treffen setzt voraus,
        # dass das Sprachmodell es waehlt - und wer seine Stimme hinterlegen
        # will, soll nicht darauf angewiesen sein, dass eine Antwort zufaellig
        # richtig ausfaellt. Das hier ist eine Einrichtungshandlung, kein
        # Gespraech: Ein fester Satz, eine feste Wirkung.
        if await self._stimme_befehl(text):
            self._wake()
            return

        # Diktiermodus starten - eine feste Einrichtungshandlung, kein
        # Gespraech (wie das Hinterlegen der Stimme). Wer "diktier mir ..."
        # sagt, soll nicht darauf angewiesen sein, dass das Sprachmodell
        # zufaellig den richtigen Weg waehlt.
        if await self._diktat_befehl(text):
            self._wake()
            return

        if transcript.confidence < self._min_confidence:
            logger.info(
                "Zu unsicher verstanden (%.2f < %.2f) – es wird nachgefragt.",
                transcript.confidence,
                self._min_confidence,
            )
            await self._say(
                "Das habe ich nicht sicher verstanden. Sagst du es noch einmal?",
                emotion="nachdenklich",
            )
            self._wake()
            return

        if self._is_dismissal(text):
            await self._say("Alles klar. Sag Bescheid, wenn du mich brauchst.", emotion="freundlich")
            await self._set_state(VoiceState.SLEEPING)
            self._awake_until = 0.0
            return

        await self._respond(text, turn)

    @staticmethod
    def _is_dismissal(text: str) -> bool:
        """Ob der Benutzer das Gespräch beendet hat."""

        lowered = text.lower().strip(" .!?")
        return lowered in {
            "danke",
            "danke dir",
            "das wars",
            "das war's",
            "schlaf",
            "schlaf gut",
            "ruhe",
            "stopp",
            "stop",
            "nichts",
            "vergiss es",
            "ende",
        }

    async def _respond(self, text: str, turn: VoiceTurn) -> None:
        """Holt eine Antwort und spricht sie."""

        self._processing = True
        # Die eigene Aufgabe merken: Ein "Stop" waehrend des Denkens bricht
        # genau sie ab (siehe verarbeitung_abbrechen).
        self._antwort_task = asyncio.current_task()
        try:
            await self._set_state(VoiceState.THINKING)

            # Der Fluss-Weg, wenn er bereitsteht: denken, sprechen,
            # weiterdenken, weitersprechen. Er kommt zuerst, weil er das
            # ist, was sich für den Benutzer am flüssigsten anfühlt.
            if self._stream_speech and self._answer_stream is not None:
                spoke = await self._respond_streaming(text, turn)
                if spoke:
                    return

            # Der gewöhnliche Weg – aber nicht mehr stumm bis zum Schluss:
            # Jeder fertig gedachte Satz wird sofort gesprochen, während
            # der Rest noch entsteht. Der Denkweg bleibt dabei vollständig,
            # mit Absicht, Gedächtnis, Professor und Werkzeugen.
            gesprochen = False
            try:
                answer, gesprochen = await self._answer(text, on_speech=self._sprich_satz)
            except Exception:  # noqa: BLE001
                logger.exception("Die Antwort konnte nicht erzeugt werden.")
                answer = (
                    "Da ist bei mir etwas schiefgegangen. Die Einzelheiten "
                    "stehen im Protokoll."
                )
                gesprochen = False

            turn.answered = True

            if gesprochen:
                # Schon im Fluss gesagt. Ein zweites Vorlesen wäre kein
                # Nachdruck, sondern ein Fehler.
                return

            if not answer.strip():
                answer = "Dazu fällt mir gerade nichts ein."

            await self._say(answer)
        finally:
            self._processing = False
            self._antwort_task = None
            self._wake()

    async def _sprich_satz(self, satz: str) -> bool:
        """Spricht einen einzelnen, fertig gedachten Satz.

        Diese Fassung geht an die Denkschicht: Sie ruft sie auf, sobald ein
        Satz beisammen ist – und zwar bevor die Antwort fertig ist. Wurde
        unterbrochen, wird nichts mehr gesprochen; „stop" soll auch
        mitten in einer entstehenden Antwort greifen.
        """

        if self._interrupted.is_set():
            return False
        return await self._say(satz)

    async def _respond_streaming(self, text: str, turn: VoiceTurn) -> bool:
        """Spricht die Antwort im Fluss, Satz für Satz, während sie entsteht.

        Die Stücke des Sprachmodells kommen selten als ganze Sätze – mal ein
        Wort, mal eine Silbe. Deshalb werden sie hier gesammelt, bis ein
        vollständiger Satz beisammen ist, und erst dann gesprochen. So bricht
        die Stimme nicht mitten im Wort ab, und der Orb fängt trotzdem an zu
        reden, lange bevor der letzte Satz gedacht ist.

        Returns:
            Ob tatsächlich gesprochen wurde. Bei ``False`` fällt der Aufrufer
            auf den gewöhnlichen Weg zurück – etwa wenn der Stream leer blieb
            oder scheiterte.
        """

        buffer = ""
        spoke_anything = False
        turn.answered = True

        try:
            async for piece in self._answer_stream(text):
                buffer += piece
                sentence, buffer = _take_complete_sentence(buffer)
                while sentence:
                    if await self._say(sentence):
                        spoke_anything = True
                    if self._interrupted.is_set():
                        return spoke_anything
                    sentence, buffer = _take_complete_sentence(buffer)

            # Was nach dem letzten Satzzeichen übrig blieb, noch sprechen.
            rest = buffer.strip()
            if rest:
                if await self._say(rest):
                    spoke_anything = True
        except Exception:  # noqa: BLE001 - Fluss gescheitert, dann eben normal.
            logger.exception("Der Streaming-Weg ist gescheitert; Rückfall auf den ganzen Text.")
            return spoke_anything

        return spoke_anything

    # --- Sprechen -------------------------------------------------------------------------

    async def _say(self, text: str, *, emotion: str = "") -> bool:
        """Spricht einen Text aus.

        Lange Antworten werden abschnittsweise gesprochen, damit die erste
        Silbe früh kommt und ein Abbruch nicht die ganze Antwort verwirft.

        Returns:
            ``True``, wenn vollständig gesprochen wurde.
        """

        if not self._tts.enabled:
            return False

        # Immer nur EINE Rede zur Zeit. Ohne diese Sperre konnten sich zwei
        # Reden verzahnen – etwa eine Begrüßung und eine Antwort, oder ein
        # Hinweis von sich aus mitten in einer laufenden Antwort. Die Sätze
        # beider Texte wechselten sich dann pausenlos ab, und was aus dem
        # Lautsprecher kam, klang wie viel zu schnelles, unverständliches
        # Durcheinander. Wer sprechen will, wartet, bis der Vorredner
        # fertig ist.
        async with self._speech_lock:
            return await self._say_locked(text, emotion=emotion)

    async def _say_locked(self, text: str, *, emotion: str = "") -> bool:
        """Der eigentliche Sprechvorgang – läuft unter der Sprechsperre."""

        # Was gerade gesagt wird, zusammen mit dem vorigen Satz: Das Echo
        # im Mikrofon hinkt der Ausgabe nach, und ein Hoerfenster faellt
        # regelmaessig ueber die Grenze zwischen zwei Saetzen. Ohne den
        # Vorgaenger haette der Orb sich dort selbst fuer einen Fremden
        # gehalten.
        self._letzte_saetze.append(self._woerter(text))
        self._gesprochene_woerter = set().union(*self._letzte_saetze)

        await self._set_state(VoiceState.SPEAKING)
        await self._event_bus.publish(event_types.TTS_STARTED, {"text": text})

        # Während der Orb spricht, horcht der Stop-Späher auf das Stop-Wort:
        # kurze, feste Hörfenster statt der gewöhnlichen Äußerungserkennung.
        # Die wartet nämlich auf Stille – und die gibt es nicht, solange die
        # eigene Stimme aus dem Lautsprecher kommt. Die normale Aufnahme
        # wird derweil stummgeschaltet, damit der Orb seine eigene Antwort
        # nicht als Befehl versteht.
        # Hier stand frueher self._interrupted.clear() - und das war der
        # Fehler, wegen dem der Orb weitersprach, wenn man ihn unterbrach.
        #
        # Eine Antwort besteht aus mehreren Saetzen, und seit die Antwort im
        # Fluss gesprochen wird, ist jeder Satz ein eigener Aufruf dieser
        # Funktion. Wer den vierten Satz unterbrach, stoppte also nur den
        # vierten: Der fuenfte kam als neuer Aufruf herein, loeschte das
        # Abbruchzeichen und sprach munter weiter. Von aussen sah das aus,
        # als habe die Unterbrechung gar nicht gegriffen - sie hatte
        # gegriffen, aber nur fuer eine Sekunde.
        #
        # Geloescht wird das Zeichen jetzt an genau EINER Stelle: wenn eine
        # neue Rede beginnt (siehe _neue_rede). Wer unterbricht, bringt
        # damit die ganze Antwort zum Schweigen und nicht bloss den Satz,
        # der gerade lief.
        self._listening_for_stop = True
        self._capture.mute(True)
        self._capture.set_stop_spotting(True)

        completed = True
        interrupted = False

        try:
            prepared = self._tts.prepare_text(text)
            chunks = self._tts.split_into_chunks(prepared)

            # Den nächsten Satz erzeugen, WÄHREND der aktuelle abgespielt
            # wird.
            #
            # Vorher lief das streng nacheinander: einen Satz berechnen,
            # abspielen, den nächsten berechnen, abspielen. Zwischen zwei
            # Sätzen entstand dabei jedes Mal eine Lücke – so lang, wie das
            # Berechnen dauert. Das ließ den Orb stockend wirken.
            #
            # Jetzt wird der nächste Satz vorbereitet, während der aktuelle
            # noch läuft. Die Wiedergabe blockiert in einem Thread, das
            # Berechnen läuft daneben in der Ereignisschleife – wenn ein
            # Satz zu Ende ist, steht der nächste meist schon bereit. Die
            # Lücken verschwinden, und nur der allererste Satz kostet noch
            # Wartezeit.
            if not chunks:
                completed = False
            else:
                # Den ersten Satz erzeugen.
                pending = asyncio.ensure_future(
                    self._tts.speak(chunks[0], state="speaking", emotion=emotion)
                )

                for index in range(len(chunks)):
                    if self._interrupted.is_set():
                        interrupted = True
                        completed = False
                        pending.cancel()
                        break

                    result = await pending

                    if not result.succeeded:
                        self._last_error = result.error
                        logger.error("Die Sprachausgabe ist fehlgeschlagen: %s", result.error)
                        completed = False
                        break

                    # Den nächsten Satz sofort in Arbeit geben, bevor der
                    # aktuelle abgespielt wird – das ist der ganze Trick.
                    if index + 1 < len(chunks):
                        pending = asyncio.ensure_future(
                            self._tts.speak(
                                chunks[index + 1], state="speaking", emotion=emotion
                            )
                        )

                    if self._interrupted.is_set():
                        interrupted = True
                        completed = False
                        if index + 1 < len(chunks):
                            pending.cancel()
                        break

                    played = await asyncio.to_thread(
                        self._player.play_blocking, result.audio_path
                    )

                    if self._interrupted.is_set():
                        interrupted = True
                        completed = False
                        if index + 1 < len(chunks):
                            pending.cancel()
                        break

                    if not played:
                        completed = False
                        if index + 1 < len(chunks):
                            pending.cancel()
                        break

                    # Zwischen zwei Sätzen kurz Luft holen. Ohne diese Pause
                    # klebten die Sätze aneinander, und die Rede wirkte
                    # gehetzt bis unverständlich.
                    if index + 1 < len(chunks):
                        await asyncio.sleep(self._sentence_pause)
        finally:
            self._listening_for_stop = False
            self._capture.set_stop_spotting(False)
            self._capture.mute(False)
            await self._event_bus.publish(
                event_types.TTS_FINISHED,
                {"completed": completed, "interrupted": interrupted},
            )

        if interrupted:
            # Wer unterbricht, will reden. Also wach bleiben und zuhören,
            # ohne dass das Weckwort noch einmal fallen muss.
            self._wake()
            await self._set_state(VoiceState.LISTENING)

        # Auch hier stand frueher ein clear(). Es machte den Aufrufern die
        # Pruefung unmoeglich: Sie fragen nach der Rueckkehr, ob unterbrochen
        # wurde, und bekamen immer nein - das Zeichen war eine Zeile vorher
        # geloescht worden.
        return completed

    async def wait_until_warm(self, timeout: float = 90.0) -> bool:
        """Wartet, bis Erkennung und Ausgabe wirklich geladen sind.

        Damit lässt sich die Begrüßung an den Zeitpunkt hängen, zu dem der
        Orb tatsächlich antworten kann – und nicht an den, zu dem er
        lediglich gestartet ist.
        """

        try:
            await asyncio.wait_for(self._warmed_up.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Das Vorwärmen dauert länger als %.0f s – es wird trotzdem "
                "fortgefahren.", timeout,
            )
            return False

    def _neue_rede(self) -> None:
        """Beginnt eine neue Rede und hebt einen frueheren Abbruch auf.

        Das Abbruchzeichen gilt fuer eine ganze Antwort, nicht fuer einen
        Satz. Es muss deshalb genau dann fallen, wenn etwas Neues zu sagen
        beginnt - und nur dann.

        Zwei Stellen rufen das: eine neue Anweisung des Benutzers und ein
        Hinweis, den der Orb von sich aus gibt. Beides ist eine neue Rede.
        Der naechste Satz derselben Antwort ist es nicht, und genau daran
        scheiterte es vorher.
        """

        self._interrupted.clear()
        # Auch die angefangene Zaehlung faellt: Ein halber Verdacht aus der
        # vorigen Antwort darf die neue nicht gleich im ersten Fenster
        # abbrechen.
        #
        # Die Wortmenge wird dabei NICHT geleert. Sie zu leeren waere die
        # naheliegende Ordnung und der falsche Handel: Beim Start einer
        # neuen Rede kann das Echo der vorigen noch unterwegs sein, und
        # ohne deren Woerter waere genau dieses Echo wieder "fremde Rede".
        # Stehen bleiben sie zu lassen kostet dagegen nur, dass ein
        # Zwischenruf mit denselben Woertern uebersehen wird - und das ist
        # der viel seltenere Fall.
        self._fremd_folge = 0

    async def say(self, text: str, *, emotion: str = "") -> bool:
        """Lässt den Orb etwas sagen, ohne dass gefragt wurde.

        Für Hinweise von sich aus – etwa wenn ein langer Auftrag fertig ist.
        """

        self._neue_rede()
        spoken = await self._say(text, emotion=emotion)
        await self._set_state(
            VoiceState.LISTENING if self.is_awake else VoiceState.SLEEPING
        )
        return spoken

    @staticmethod
    def _woerter(text: str) -> set[str]:
        """Zerlegt einen Text in vergleichbare Woerter."""

        return {
            wort.strip(".,!?;:\u201e\u201c\"'()").lower()
            for wort in text.split()
            if len(wort.strip(".,!?;:\u201e\u201c\"'()")) >= 4
        }

    def _ist_fremde_rede(self, text: str) -> bool:
        """Ob in einem Hoerfenster jemand anderes redet als der Orb selbst.

        Das ist der Ersatz fuer die Stimmerkennung, solange keine Stimme
        hinterlegt ist - und ohne ihn kann man den Orb nur mit dem Wort
        "stop" unterbrechen, nicht durch blosses Dazwischenreden.

        Das Problem dabei ist immer dasselbe: Waehrend der Orb spricht,
        hoert das Mikrofon vor allem IHN. Jede Silbe seiner eigenen Antwort
        wuerde ihn unterbrechen, und er kaeme nie ueber den ersten Satz
        hinaus.

        Die Stimmerkennung loest das ueber die Frage, WESSEN Stimme da
        liegt. Ohne hinterlegte Stimme geht auch das hier: Der Orb weiss,
        WAS er gerade sagt. Steht im Hoerfenster etwas, das in seinem
        eigenen Satz nicht vorkommt, kann es nicht sein Echo sein.

        Verlangt werden zwei unbekannte Woerter und nicht eines. Ein
        einzelnes erfindet die Erkennung leicht aus einem Rauschen oder
        einem halb gehoerten Wort - und ein Orb, der bei jedem Knacken
        verstummt, ist schlimmer als einer, der einmal zu lange redet.
        """

        if not text:
            return False

        # Nicht der genaue Vergleich, sondern der aehnliche.
        #
        # Hier stand eine Mengendifferenz: Was nicht Zeichen fuer Zeichen im
        # eigenen Satz stand, galt als fremd. Das ist der Grund, warum sich
        # der Orb selbst unterbrach.
        #
        # Was aus dem Lautsprecher kommt und durch den Raum zurueck ins
        # Mikrofon laeuft, kommt bei Whisper nicht als saubere Abschrift an.
        # "Sprachausgabe" wird zu "Sprachaufgabe", "Verstanden" zu
        # "Verstehen", aus einem zusammengesetzten Wort werden zwei. Jedes
        # dieser Verhoerer war nach der alten Regel ein fremdes Wort - und
        # weil Deutsch lange Woerter hat, schlug schon eines davon die
        # Sieben-Zeichen-Regel und brach die Antwort ab.
        #
        # Verglichen wird deshalb auf Aehnlichkeit. Ein Wort, das einem
        # gerade gesprochenen nahekommt, ist ein Verhoerer und kein
        # Zwischenruf.
        naehe = {wort: self._naehe_zum_eigenen(wort) for wort in self._woerter(text)}
        fremd = [wort for wort, n in naehe.items() if n < AEHNLICH_GENUG]
        if len(fremd) >= 2:
            return True

        # Ein einzelnes LANGES Wort genuegt ebenfalls - aber nur, wenn es
        # dem eigenen Satz auch wirklich fernsteht.
        #
        # Die Regel bleibt, weil sie den haeufigsten Fall faengt: die kurze
        # Zwischenbemerkung. "Nein, warte" hat nur ein Wort ueber vier
        # Zeichen.
        #
        # Sie verlangt jetzt aber die schaerfere Schwelle. Ein einzelnes
        # Wort, das knapp unter der Verhoerergrenze liegt, ist fast immer
        # eine verhoerte Endung - "verstehen" statt "verstanden" - und
        # keine Wortmeldung. Eine ganze Antwort daran abzubrechen, war die
        # Behauptung, die nicht traegt.
        return any(
            len(wort) >= 7 and naehe[wort] < FREMD_GENUG for wort in fremd
        )

    def _naehe_zum_eigenen(self, wort: str) -> float:
        """Wie nahe ein gehoertes Wort dem aehnlichsten gerade gesagten kommt.

        Zuerst der billige Test - steht es woertlich da -, danach der
        teure. Der teure laeuft nur ueber Woerter aehnlicher Laenge: Ein
        Vergleich von "ja" mit "Sprachausgabe" kann nicht nahe ausfallen,
        und ihn zu rechnen waere verschenkte Zeit in einer Schleife, die
        waehrend jedes Satzes mehrmals laeuft.
        """

        if wort in self._gesprochene_woerter:
            return 1.0
        beste = 0.0
        for eigenes in self._gesprochene_woerter:
            if abs(len(eigenes) - len(wort)) > 3:
                continue
            wert = SequenceMatcher(None, wort, eigenes).ratio()
            if wert > beste:
                beste = wert
                if beste >= 1.0:
                    break
        return beste

    def _contains_stop_word(self, text: str) -> bool:
        """Ob eine Äußerung ein Stop-Wort enthält.

        Geprüft wird auf ganze Wörter, nicht auf Teilzeichenketten: „halt“
        soll nicht in „Gehalt“ oder „Haltung“ anschlagen, sonst bräche der
        Orb mitten im eigenen Satz ab.
        """

        if not self._stop_words or not text:
            return False

        words = {
            word.strip(".,!?;:").lower()
            for word in text.split()
        }
        return bool(words & self._stop_words)

    def interrupt(self) -> None:
        """Bricht die laufende Sprachausgabe ab.

        Wird von der Enter-Taste ausgelöst (über ``/voice/interrupt``) und
        früher vom akustischen Dazwischenreden. Neben dem Stoppen der
        Wiedergabe wird das Abbruch-Signal gesetzt: Sonst spräche die
        Sprechschleife nach dem gestoppten Satz einfach den nächsten,
        und der Abbruch wirkte wie ein kurzes Stottern statt wie ein Halt.
        """

        self._interrupted.set()
        self._player.stop()
        # Das Mikrofon wieder freigeben – wer unterbricht, will meist reden.
        self._capture.mute(False)
        logger.info("Sprachausgabe unterbrochen.")

    def verarbeitung_abbrechen(self) -> None:
        """Die Notbremse: bricht Sprachausgabe UND laufende Verarbeitung ab.

        ``interrupt`` stoppt nur das Sprechen. Sagte der Benutzer aber
        „Stop", während der Orb noch DACHTE, lief der Auftrag ungerührt
        weiter und redete Sekunden später los - für den Benutzer sah das
        aus, als reagiere der Orb auf „Stop" gar nicht. Hier wird deshalb
        zusätzlich die Antwort-Aufgabe selbst abgebrochen.
        """

        self.interrupt()
        task = self._antwort_task
        if task is not None and not task.done():
            task.cancel()
            logger.info("Laufende Verarbeitung auf Stop-Wunsch abgebrochen.")

    async def _ist_kurzer_stop(self, path: Path, duration: float) -> bool:
        """Ob eine KURZE Äußerung ein Stop-Wort enthält.

        Die schnelle Prüfung für die Notbremse: Nur kurze Ausrufe (bis etwa
        drei Sekunden) kommen infrage - „Stop!", „Halt!" -, und erkannt
        wird mit dem kleinen, schnellen Modell. Länge zuerst, damit nicht
        jede verworfene Äußerung eine Erkennung kostet.
        """

        if duration > 3.0 or not self._stop_words:
            return False
        try:
            erkennung = (
                self._transcriber
                if self._stop_transcriber.load_failed
                else self._stop_transcriber
            )
            transcript = await erkennung.transcribe(path)
        except Exception:  # noqa: BLE001 - die Notbremse darf nie selbst reissen.
            logger.debug("Stop-Kurzprüfung nicht möglich.", exc_info=True)
            return False
        return self._contains_stop_word(transcript.text)

    # --- Zustandsführung ---------------------------------------------------------------------

    def _wake(self) -> None:
        """Verlängert die Wachphase."""

        self._awake_until = time.time() + self._follow_up_seconds

    async def _set_state(self, state: VoiceState) -> None:
        if self._state is state:
            return
        vorher = self._state
        self._state = state

        # Beim Übergang ins Nachdenken erklingt der Denk-Klang – nur beim
        # Übergang, nicht bei jedem Aufruf. Sonst käme er mehrfach, denn
        # der Zustand wird während einer Anweisung öfter gesetzt.
        if state is VoiceState.THINKING and vorher is not VoiceState.THINKING:
            self._klaenge.denken()

        # Und beim Übergang ins Zuhören der Hör-Klang. Beim Wechsel vom
        # Denken oder Sprechen zurück ins Zuhören bleibt er aus: Das ist
        # kein Anfang, sondern das Ende der Antwort – dort ertönte er
        # sonst nach jedem Satz.
        if state is VoiceState.LISTENING and vorher in (
            VoiceState.SLEEPING,
            VoiceState.OFF,
        ):
            self._klaenge.zuhoeren()

        await self._publish_state()

    async def _publish_state(self) -> None:
        """Meldet den Zustand an die Oberfläche, damit der Orb ihn zeigt."""

        orb_state = {
            VoiceState.OFF: "idle",
            VoiceState.SLEEPING: "idle",
            VoiceState.LISTENING: "listening",
            VoiceState.THINKING: "thinking",
            VoiceState.SPEAKING: "speaking",
        }[self._state]

        await self._event_bus.publish(
            "voice.state.changed",
            {
                "voice_state": self._state.value,
                "orb_state": orb_state,
                "awake": self.is_awake,
                "error": self._last_error,
            },
        )
        await self._event_bus.publish(event_types.ORB_STATE_CHANGED, {"state": orb_state})

    def _on_playback_level(self, level: float) -> None:
        """Meldet den Pegel, damit der Orb beim Sprechen mitschwingt."""

        if self._loop is None:
            return
        self._event_bus.publish_threadsafe(
            self._loop, "voice.level", {"level": round(level, 4), "source": "output"}
        )

    def _on_playback_started(self, path: Path) -> None:
        logger.debug("Wiedergabe beginnt: %s", path.name)

    def _on_playback_finished(self, path: Path, completed: bool) -> None:
        logger.debug(
            "Wiedergabe %s: %s", "beendet" if completed else "abgebrochen", path.name
        )

    def _remember(self, turn: VoiceTurn) -> None:
        """Legt einen Durchgang im Verlauf ab."""

        if not turn.transcript:
            return
        self._history.append(turn)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

    # --- Auskunft ---------------------------------------------------------------------------

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Die jüngsten Gesprächsdurchgänge."""

        return [turn.to_dict() for turn in self._history[-limit:]][::-1]

    def status(self) -> dict[str, Any]:
        """Gesamtstatus der Sprachsteuerung."""

        remaining = max(0.0, self._awake_until - time.time())
        return {
            "enabled": self._enabled,
            "state": self._state.value,
            "running": self.is_running,
            "awake": self.is_awake,
            "awake_seconds_left": round(remaining, 1),
            "wake_words": self._wake_word.phrases,
            "always_on": self._always_on,
            "barge_in": self._barge_in,
            "last_error": self._last_error,
            "capture": self._capture.status(),
            "transcriber": self._transcriber.status(),
            "tts": self._tts.status(),
            "player": self._player.status(),
            "turns": len(self._history),
        }

    def is_ready(self) -> bool:
        """Ob alles Nötige für die Sprachsteuerung vorhanden ist.

        Bewusst als eigene Methode und nicht als Textprüfung auf
        :meth:`requirements_report`: Ein „noch nicht einsatzbereit" enthält
        das Wort „einsatzbereit", und wer darauf prüft, bekommt genau das
        Gegenteil dessen heraus, was er wissen wollte.
        """

        return not self._check_requirements()

    def requirements_report(self) -> str:
        """Erklärt im Klartext, was noch fehlt."""

        problems = self._check_requirements()
        if problems:
            return problems
        return (
            "Die Sprachsteuerung ist einsatzbereit. Sag '"
            + (self._wake_word.phrases[0] if self._wake_word.phrases else "Hallo Orb")
            + "'."
        )


def _ist_geplapper(text: str) -> bool:
    """Ob eine Erkennung nur aus Wortwiederholungen besteht.

    Whisper verhakt sich gelegentlich und gibt dasselbe Wort ein Dutzend
    Mal aus. Im Protokoll des Benutzers steht so ein Fall woertlich:
    "Ja... ruhig ruhig ruhig ruhig ruhig ruhig ruhig...".

    Das ist keine Aeusserung, sondern ein Artefakt. Es weiterzureichen
    hiesse, das Sprachmodell ueber ein Wort nachdenken zu lassen, das
    niemand gesagt hat.
    """

    woerter = [w.strip(".,!?;:\u2026").lower() for w in text.split()]
    woerter = [w for w in woerter if w]
    if len(woerter) < 5:
        return False

    laengste = 1
    lauf = 1
    for vorher, jetzt in zip(woerter, woerter[1:]):
        lauf = lauf + 1 if jetzt == vorher else 1
        laengste = max(laengste, lauf)
    if laengste >= 4:
        return True

    # Oder: fast nur ein einziges Wort, egal in welcher Reihenfolge.
    haeufigstes = max(woerter.count(w) for w in set(woerter))
    return haeufigstes / len(woerter) >= 0.6
