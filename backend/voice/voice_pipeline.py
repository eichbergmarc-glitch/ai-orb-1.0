"""Die Sprachpipeline – hier wird aus Zuhören ein Gespräch.

Sie führt die Einzelteile zusammen: Das Mikrofon nimmt auf, die
Sprachaktivitätserkennung schneidet Äußerungen heraus, Whisper macht Text
daraus, die Weckworterkennung entscheidet, ob gemeint war, und die
Sprachausgabe antwortet.

Der Ablauf in einem Satz: **Auf die zugelassenen Stimmen hören – und für
alle anderen schlafen, bis „Hallo Synapse" fällt.**

Fünf Entscheidungen prägen das Verhalten:

**Die erkannte Stimme braucht kein Weckwort (freie Ansprache).** Ist eine
Stimme hinterlegt und wird sie in einer Äußerung sicher wiedererkannt, ist
der Orb ansprechbar - mitten im Gespräch wie für den ersten Satz. Der
Preis ist benannt: Was die erkannte Stimme sagt, wird verarbeitet, nicht
erst nach einem Weckwort. Wer den Orb wegschickt („das war's"), schaltet
ihn in Ruhe; dann holt ihn nur das Weckwort zurück. Der Benutzer kann
weitere Stimmen zulassen („hör auf diese Stimme") und widerrufen („hör
nur auf mich").

**Das Weckwort schützt vor allem Fremden.** Ohne hinterlegte Stimme - und
für jede nicht erkannte Stimme - wird im Schlafzustand zwar zugehört, aber
nichts weitergegeben: Der Text wird auf das Weckwort geprüft und dann
verworfen. Erst danach geht etwas an die KI. Aufnahmen werden nicht
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
import re
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
from backend.studium.vorlesungs_session import VorlesungsSession
from backend.system.logging_setup import get_logger
from backend.system.performance_trace import TurnTrace, mark_stage, reset_turn_trace, start_turn_trace
from backend.diktat.diktat import KALIBRIERSATZ, Diktierer
from backend.tts.tts_manager import TtsManager
from backend.voice.speaker_id import Stimmerkennung, Urteil
from backend.voice.stopwort import stopwort_finden
from backend.voice.human_speech import HumanSpeechPolicy
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


def _gesprochene_kurzfassung(text: str, *, max_zeichen: int = 700) -> str:
    """Entfernt technische Adressen und begrenzt einen TTS-Rueckfall.

    Der regulaere Satzstrom bleibt unveraendert. Diese Sicherung greift nur,
    wenn eine vollstaendige Antwort am Ende auf einmal an TTS faellt - genau
    dort konnten bisher rohe Werkzeugdaten minutenlang vorgelesen werden.
    """

    knapp = str(text or "").strip()
    # Bei Markdown-Links den lesbaren Titel behalten, die Adresse weglassen.
    knapp = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", knapp)
    knapp = re.sub(r"https?://\S+", "", knapp)
    knapp = " ".join(knapp.split())
    if len(knapp) <= max_zeichen:
        return knapp

    ausschnitt = knapp[:max_zeichen]
    enden = [ausschnitt.rfind(zeichen) for zeichen in _SENTENCE_ENDINGS]
    ende = max(enden)
    if ende >= max_zeichen // 2:
        ausschnitt = ausschnitt[: ende + 1]
    else:
        ausschnitt = ausschnitt.rsplit(" ", 1)[0].rstrip(" ,;:") + "."
    return ausschnitt.strip() + " Weitere Details fasse ich dir auf Wunsch kurz zusammen."

#: Ab so vielen Zeichen ohne Satzzeichen wird trotzdem gesprochen.
#:
#: Manche Antworten kommen als ein langer Fluss ohne Punkt – eine Aufzählung
#: mit Kommas, ein Nebensatzgebirge. Ewig zu warten hieße, gar nicht
#: anzufangen. Nach einer Weile wird deshalb am letzten Komma oder
#: Leerzeichen umbrochen, damit der Orb ins Reden kommt.
_SOFT_BREAK_AFTER = 240

# Ein Komma traegt nur eine kurze Fortsetzungsintonation. Wird genau dort
# eine Audiodatei beendet, klingt die technische Luecke danach wie
# Zoegern. Deshalb ist ein Komma erst bei wirklich langen Saetzen eine
# Notloesung; vorher wird nur an einem staerkeren Semikolon getrennt.
_COMMA_BREAK_AFTER = 400

#: Abkürzungen, deren Punkt kein Satzende ist.
#:
#: Ohne diese Liste bräche der Orb nach „Dr.“ oder „z. B.“ mitten im Satz
#: ab und spräche das Bruchstück für sich – „Doktor.“ als ganzer Satz klingt
#: wie ein Schluckauf. Die Liste ist bewusst kurz und deckt das Häufige ab.
_ABBREVIATIONS = frozenset({
    "dr", "prof", "hr", "fr", "nr", "z", "b", "u", "a", "d", "h",
    "usw", "etc", "ca", "bzw", "vgl", "ggf", "evtl", "inkl", "max", "min",
    "s", "sog", "bspw", "abb", "tab", "jh", "st",
    "mio", "mrd", "tsd", "hrsg", "bd", "kap", "art", "abs",
})

#: Ab dieser Pufferlaenge wird notfalls an einem blossen Leerzeichen
#: umbrochen - aber wirklich nur notfalls. Der gewoehnliche weiche
#: Umbruch wartet auf ein Komma oder Semikolon, denn dort macht auch
#: ein Mensch beim Sprechen eine kleine Pause. Ein Schnitt mitten im
#: Satzglied ("die Verschiebung der | Konsonanten") war der Grund fuer
#: die unnatuerlichen Luecken, die der Benutzer am 20.08. meldete.
_NOTBRUCH_AB = 600


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
            # Eine Ordnungszahl ist auch keiner: "Zwischen dem 6. und 8.
            # Jahrhundert" zerfiel sonst in Bruchstücke, und zwischen
            # ihnen entstand eine Sprechpause mitten im Gedanken. Ein bis
            # zwei Ziffern sind eine Ordnungszahl oder ein Datumsteil;
            # eine Jahreszahl ("... endete 1815.") bleibt ein Satzende.
            if last_word.isdigit() and len(last_word) <= 2:
                continue

        return candidate, buffer[index + 1 :].lstrip()

    # Kein Satzzeichen, aber der Puffer wird lang – weich umbrechen.
    #
    # Aber nur dort, wo auch ein Mensch Luft holt: an einem Komma oder
    # Semikolon. Der alte Umbruch am letzten LEERZEICHEN schnitt lange
    # Sätze mitten im Satzglied durch, und jede Schnittstelle wurde zur
    # hörbaren Lücke - genau die "unnatürlichen Lücken mitten im Satz",
    # die der Benutzer am 20.08. gemeldet hat. Erst wenn der Puffer sehr
    # lang wird und weit und breit kein Komma kommt, wird notfalls doch
    # am Leerzeichen gebrochen - besser eine Lücke als acht Sekunden
    # Schweigen vor einem Nebensatzgebirge.
    if len(buffer) >= _SOFT_BREAK_AFTER:
        cut = buffer.rfind("; ")
        if cut > 40:
            return buffer[: cut + 1].strip(), buffer[cut + 1 :].lstrip()
    if len(buffer) >= _COMMA_BREAK_AFTER:
        cut = buffer.rfind(", ")
        if cut > 80:
            return buffer[: cut + 1].strip(), buffer[cut + 1 :].lstrip()
    if len(buffer) >= _NOTBRUCH_AB:
        cut = buffer.rfind(" ")
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
    trace_id: str = ""
    timings: dict[str, float | str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript,
            "confidence": round(self.confidence, 3),
            "woke": self.woke,
            "answered": self.answered,
            "interrupted": self.interrupted,
            "duration_seconds": round(self.duration_seconds, 2),
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "timings": self.timings,
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
        # Tagebucheintraege sind ein echtes, mehrteiliges Sprachdiktat. Der
        # Zustand muss hier leben (und nicht nur im Orchestrator), weil jede
        # Mikrofon-Aeusserung ein eigener Verarbeitungslauf sein kann.
        self._tagebuch_diktat_aktiv = False
        self._tagebuch_diktat_teile: list[str] = []
        self._tagebuch_diktat_art = "neu"
        self._tagebuch_diktat_position = "letzter"

        # --- Einstellungen -------------------------------------------------------
        self._enabled = bool(config.get("voice.enabled", True))
        self._always_on = bool(config.get("voice.wake_word.always_on", True))
        self._follow_up_seconds = float(config.get("voice.follow_up_seconds", 25.0))
        #: Freie Ansprache: Wer nachweislich eine ZUGELASSENE Stimme ist
        #: (die hinterlegte des Benutzers oder eine von ihm freigegebene
        #: Gaststimme), braucht kein Weckwort - weder mitten im Gespraech
        #: noch fuer den ersten Satz. Der Benutzer hat es so verlangt:
        #: "er sollte mich ja immer erkennen, weil er ja meine Stimme
        #: kennt." Ohne hinterlegte Stimme bleibt alles beim Weckwort,
        #: sonst hoerte der Orb wieder auf jeden - genau davor schuetzt
        #: die Stimmpruefung. Wer den Orb wegschickt ("das war's"),
        #: schaltet ihn in Ruhe: Dann gilt das Weckwort wieder, bis es
        #: einmal faellt.
        self._freie_ansprache = bool(config.get("voice.freie_ansprache", True))
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
        #: Ob im Nachfragefenster geprueft wird, ob der Orb gemeint ist.
        self._hintergrund_erkennen = bool(
            config.get("voice.hintergrund_erkennen", True)
        )
        #: Ob der Orb selbst zuletzt eine Rueckfrage gestellt hat. Nur dann
        #: zaehlt ein blosses "ja" als Antwort AN IHN und nicht als
        #: Zustimmung in einem Gespraech, das ihm nicht galt.
        self._wartet_auf_antwort = False
        self._acknowledge = bool(config.get("voice.acknowledge_wake", True))
        self._acknowledge_text = str(config.get("voice.acknowledge_text", "Ja?"))

        # Wörter, die das Sprechen abbrechen. Bewusst kurz und markant, damit
        # der Orb sie nicht in seiner eigenen Antwort versehentlich auslöst.
        self._stop_words = {
            str(word).strip().lower()
            for word in (config.get("voice.stop_words", ["stop", "stopp", "halt"]) or [])
        }

        #: Ob der Stop-Spaeher auch bei einer lokalen Stimme mithoert.
        #:
        #: Voreinstellung an. Der Grund steht ausfuehrlich bei
        #: :meth:`_stop_spaeher_fuer_ausgabe`: Ohne dies war das Stop-Wort
        #: bei der lokalen Stimme wirkungslos - und zwar vollstaendig, nicht
        #: nur unzuverlaessig.
        self._stop_waehrend_lokaler_stimme = bool(
            config.get("voice.stop_waehrend_lokaler_stimme", True)
        )
        #: Ob eine Taste als zusaetzlicher Unterbrechungsweg eingetragen ist.
        self._interrupt_taste = str(config.get("voice.interrupt_key", "") or "").strip()
        #: Ob die eingestellte Stimme im Rechner selbst erzeugt wird. Nur
        #: dann greift die Ruecksicht auf die CPU ueberhaupt.
        self._stimme_lokal = any(
            str(name).strip().lower() in {"supertonic", "pocket_tts", "piper"}
            for name in (config.get("voice.output.engines", []) or [])
        )

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

        #: Was der Stop-Späher während eines Satzes gehört hat.
        #:
        #: Das ist reine Nachvollziehbarkeit, und sie fehlte schmerzlich:
        #: Als am 19.08.2026 zu klären war, warum das Stop-Wort nicht mehr
        #: greift, stand im ganzen Protokoll keine einzige Zeile darüber,
        #: WAS der Späher in seinen Hörfenstern verstanden hatte. Ob das
        #: Wort nie ankam oder ankam und verworfen wurde, war nicht zu
        #: unterscheiden - und ohne diese Unterscheidung ist jede
        #: Verbesserung geraten. Am Ende jedes Satzes steht die Bilanz
        #: jetzt im Protokoll.
        self._spaeher_fenster = 0
        self._spaeher_gehoert: list[str] = []

        # --- Bestandteile ----------------------------------------------------------
        self._wake_word = WakeWordDetector(
            config.get("voice.wake_word.phrases", ["Hallo Synapse"]) or ["Hallo Synapse"],
            threshold=float(config.get("voice.wake_word.threshold", 0.78)),
            max_leading_words=int(config.get("voice.wake_word.max_leading_words", 3)),
        )

        #: Fehlersuche: so viele letzte Aufnahmen in logs/aufnahmen behalten.
        self._diagnose_aufnahmen = int(config.get("voice.input.diagnose_aufnahmen", 0) or 0)
        #: Der Vorgabetext der Erkennung - um sein Echo zu erkennen.
        self._vorgabetext = str(config.get("voice.input.initial_prompt", "") or "")
        self._transcriber = Transcriber(
            model_size=str(config.get("voice.input.model_size", "small")),
            language=str(config.get("voice.input.language", "de")),
            device=str(config.get("voice.input.device", "auto")),
            compute_type=str(config.get("voice.input.compute_type", "int8")),
            cpu_threads=int(config.get("voice.input.cpu_threads", 0)),
            beam_size=int(config.get("voice.input.beam_size", 1)),
            anfangshinweis=str(config.get("voice.input.initial_prompt", "")),
            cloud=config.get("voice.input.cloud", None) or None,
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
            # Bewusst WENIGE Kerne: Dieses Modell laeuft, waehrend das
            # grosse erkennt und der Orb spricht. Wuerden beide alle Kerne
            # nehmen, machten sie einander langsam - genau die Traegheit,
            # die hier verhindert werden soll. "base" ist mit zwei Kernen
            # fuer ein Drei-Sekunden-Fenster schnell genug.
            cpu_threads=2,
            beam_size=1,
            # Die beiden Schalter, die dieses Fenster billig halten.
            #
            # Ohne sie kostete ein 0,6-Sekunden-Fenster am 06.09. bis zu
            # 14,4 Sekunden Rechenzeit - fuer ein Ergebnis, das am Ende
            # leer war ("3 Hoerfenster, davon 0 mit Text"). Whisper fuellt
            # jede Aufnahme intern auf dreissig Sekunden auf und arbeitet
            # bei Stille die ganze Temperatur-Treppe ab, bevor es aufgibt.
            #
            # Hier wird kein Satz verstanden, sondern auf drei kurze Woerter
            # gehorcht. Ein Durchgang genuegt, und wo nichts gesprochen
            # wurde, ist auch nichts zu dekodieren.
            vad_filter=True,
            temperatur_treppe=False,
            # Ein EIGENER Anker, nicht der des grossen Modells.
            #
            # Hier stand bisher derselbe lange Hinweis: ein Absatz ueber
            # Historiografie, Quellenkritik, Voelkerrecht, Leitzins. Fuer
            # das grosse Modell ist das richtig - es transkribiert ganze
            # Saetze ueber diese Gebiete. Dieses Modell aber sieht nur
            # Fenster von unter einer Sekunde und hat genau zwei Fragen zu
            # beantworten: Fiel das Weckwort? Fiel ein Abbruchwort?
            #
            # Ein Anker lenkt die Erkennung auf das, was er nennt. Wer ihr
            # bei einem Achtelsekundenschnipsel "Historiografie" und
            # "Bruttoinlandsprodukt" vorlegt, lenkt sie von "Stopp" WEG -
            # und genau das war der Zustand, in dem das Stop-Wort seit dem
            # 15.08.2026 nur noch ein einziges Mal griff.
            #
            # UND OHNE die Abbruchwoerter. Sie hier zu nennen war ein
            # Eigentor: Der Anker ist fuer Whisper der Text unmittelbar
            # VOR dem Fenster, und es setzt fort, was dort steht. Auf
            # einem undeutlichen Schnipsel - und das ist jedes Fenster,
            # in dem der eigene Lautsprecher laeuft - schrieb es daraufhin
            # bereitwillig "Stopp." hin. Der Orb zerriss seine eigenen
            # Saetze. Ein falsch erkanntes Weckwort kostet ein unnoetiges
            # Aufwachen; ein falsches "Stopp" kostet jeden zweiten Satz.
            anfangshinweis=str(
                config.get("voice.stop_initial_prompt", "")
                or "Hallo Synapse. Hey Synapse."
            ),
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
        #: Ob gerade eine GASTSTIMME gesammelt wird statt der eigenen.
        #: Der Ablauf ist derselbe (Proben sammeln, sofort pruefen), nur
        #: das Ziel ein anderes: Die Proben landen als Gastprofil NEBEN
        #: dem Benutzerprofil, nicht an seiner Stelle.
        self._stimme_lernt_gast = False
        #: Das Urteil der Stimmpruefung zur gerade behandelten Aeusserung.
        #: Die Befehle rund um die Stimme brauchen es, um Rechte zu
        #: unterscheiden: Ein Gast darf sprechen, aber nicht bestimmen,
        #: auf wen der Orb hoert.
        self._letztes_urteil: Urteil | None = None
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

        self._human_speech = HumanSpeechPolicy(
            enabled=bool(config.get("voice.output.human_timing.enabled", True)),
            fillers_enabled=bool(config.get("voice.output.human_timing.fillers_enabled", False)),
            cooldown_seconds=float(config.get("voice.output.human_timing.filler_cooldown_seconds", 120)),
            minimum_words=int(config.get("voice.output.human_timing.minimum_words", 9)),
        )
        self._adapt_to_user_rhythm = bool(
            config.get("voice.output.human_timing.adapt_to_user_rhythm", True)
        )

        self._player = AudioPlayer(
            normalize_volume=bool(config.get("voice.output.normalize_volume", True)),
            target_rms=float(config.get("voice.output.target_rms", 0.10)),
            trim_boundary_silence=bool(
                config.get("voice.output.trim_boundary_silence", True)
            ),
            leading_silence_ms=float(
                config.get("voice.output.leading_silence_ms", 30)
            ),
            trailing_silence_ms=float(
                config.get("voice.output.trailing_silence_ms", 70)
            ),
            on_level=self._on_playback_level,
            on_started=self._on_playback_started,
            on_finished=self._on_playback_finished,
        )

        self._capture = AudioCapture(
            self._on_utterance,
            on_interruption=self._on_interruption,
            on_stop_window=self._on_stop_window,
            stop_window_ready=self._stop_window_aufnahmebereit,
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
        #: Ruhe: Der Benutzer hat den Orb ausdruecklich weggeschickt.
        #: Solange sie gilt, weckt auch die erkannte Stimme nicht - nur
        #: das Weckwort holt den Orb zurueck. Ohne dieses Zeichen waere
        #: "das war's" bei freier Ansprache wirkungslos: Der naechste
        #: eigene Satz weckte den Orb sofort wieder.
        self._ruhe = False

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
        #: Das eine gemerkte Fenster, das nach dem laufenden geprueft wird.
        #:
        #: Dieses Feld fehlte. Nicht der Wert war falsch - es gab das Feld
        #: nicht. ``_check_stop_window`` las es nach jeder Erkennung, und
        #: jedes einzelne Hoerfenster endete deshalb mit einem
        #: AttributeError: waehrend einer laengeren Antwort dutzendfach,
        #: mitsamt Rueckverfolgung im Protokoll. Die Verkettung "gleich das
        #: naechste Fenster pruefen" hat nie funktioniert, und niemand sah
        #: es, weil der Test der Stoppfenster das Feld auf seinem eigenen
        #: Doppel selbst setzt.
        self._pending_stop_window: Path | None = None
        #: Ob schon gemeldet wurde, dass das kleine Modell fehlt.
        self._stop_grossmodell_gemeldet = False
        #: Nach so vielen Sekunden ist ein Hoerfenster kein "stop" mehr.
        #:
        #: Ein Fenster, das in der Schlange alt geworden ist, beantwortet
        #: die Frage von vorgestern. Es zu erkennen kostet die Rechenzeit,
        #: die das aktuelle braucht.
        self._stop_fenster_verfall = max(
            0.5, float(config.get("voice.stop_window_verfall_s", 2.5))
        )
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
            0.0, float(config.get("voice.output.sentence_pause_ms", 60)) / 1000.0
        )
        # Satzstrom mit Vorproduktion: Das Modell darf weiterdenken, waehrend
        # der erste Satz laeuft. Der jeweils naechste Satz wird bereits in
        # eine WAV-Datei umgewandelt und wartet beim Wiedergabeende bereit.
        self._satzstrom_queue: asyncio.Queue[Any] | None = None
        self._satzstrom_worker: asyncio.Task[bool] | None = None
        self._satzstrom_synth_lock = asyncio.Lock()
        #: Fuer Cloud-Stimmen (OpenAI): mehrere Saetze GLEICHZEITIG erzeugen.
        #: Seriell wartete jeder Satz auf den vorigen Abruf (je ~1-2 s) - war
        #: ein Satz kuerzer gesprochen als der naechste erzeugt, entstand eine
        #: Luecke. Das klang abgehackt (07.11.2026). Lokale Stimmen bleiben
        #: seriell, sonst ueberlasten sie die CPU.
        self._satzstrom_cloud_slots = asyncio.Semaphore(
            max(1, int(config.get("voice.output.parallel_cloud_synthesis", 3) or 3))
        )
        self._satzstrom_failed = False
        self._apply_learned_speech_style()
        self._history: list[VoiceTurn] = []
        self._max_history = int(config.get("voice.max_history", 50))
        self._last_error = ""
        self._speaking_task: asyncio.Task[None] | None = None
        #: Läuft, solange das Mikrofon nicht zu öffnen war und im
        #: Hintergrund weiter versucht wird. Ohne diese Schleife blieb der
        #: Orb bis zum nächsten Neustart taub, sobald das Mikrofon beim
        #: Start klemmte - vierzehn Vorfälle an einem Nachmittag, weil
        #: jemand immer wieder von Hand neu starten musste.
        self._mikrofon_heilung: asyncio.Task[None] | None = None
        self._processing = False
        # The concrete trace is also kept on the pipeline because playback
        # callbacks arrive from the audio thread and do not inherit asyncio's
        # context variables.
        self._active_turn_trace: TurnTrace | None = None
        #: Reserviert einen Gespraechszug bereits nach der Transkription.
        # ``_processing`` wird erst in ``_respond`` gesetzt; zwischen beiden
        # Stellen liegen Ereignisse, an denen ein zweites Hoerfenster sonst
        # denselben freien Zug beanspruchen koennte.
        self._turn_claimed = False
        #: Die gerade laufende Antwort-Aufgabe - damit ein "Stop" sie auch
        #: WAEHREND des Denkens abbrechen kann, nicht erst beim Sprechen.
        self._antwort_task: asyncio.Task | None = None

        # --- Fortlaufende Vorlesung -------------------------------------------
        # Ein Sprachmodell kann nicht von selbst nach seiner Antwort wieder
        # aufgerufen werden. Frueher sagte es deshalb zwar "ich mache weiter,
        # wenn du nichts sagst", danach geschah aber nichts. Die Sitzung haelt
        # den fachlichen Stand; diese Pipeline setzt nach jedem Abschnitt den
        # wirklich auszufuehrenden Folgeauftrag.
        self._vorlesung = VorlesungsSession(
            max_abschnitte=int(config.get("voice.vorlesung.max_abschnitte", 24))
        )
        self._vorlesung_pause = max(
            0.5, float(config.get("voice.vorlesung.pause_sekunden", 2.5))
        )
        self._vorlesung_task: asyncio.Task[None] | None = None

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

    @property
    def is_busy(self) -> bool:
        """Ob gerade ein Benutzerzug verarbeitet oder ausgegeben wird.

        Die Laufzeit fragt diese Eigenschaft ab, bevor sie autonomes Lernen
        startet. Sie fehlte bisher vollständig; ``getattr(..., False)`` in
        der Laufzeit lieferte deshalb immer ``False`` und ein Hintergrund-
        auftrag konnte mitten in einer Antwort dasselbe Modell belegen.
        """

        antwort = self._antwort_task
        return bool(
            self._processing
            or self._turn_claimed
            or (antwort is not None and not antwort.done())
            or self._state in (VoiceState.THINKING, VoiceState.SPEAKING)
        )

    @property
    def background_idle(self) -> bool:
        """Ob rechenintensive Hintergrundarbeit den Dialog nicht stoert.

        ``LISTENING`` gilt absichtlich nicht als Leerlauf: In diesem Zustand
        wartet der Orb nach einer Antwort aktiv auf eine Fortsetzung. Erst im
        Schlafzustand (oder bei ausgeschalteter Sprache) darf ein autonomer
        Modelllauf beginnen.
        """

        return not self.is_busy and self._state in (VoiceState.OFF, VoiceState.SLEEPING)

    def set_offline_mode(self, enabled: bool) -> None:
        """Koppelt den Modellmodus an eine garantiert lokale Stimme."""

        self._tts.set_offline_mode(enabled)

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

        # In einem Thread, nicht in der Ereignisschleife: Das Öffnen
        # unternimmt inzwischen mehrere Anläufe mit kurzen Wartezeiten.
        if not await asyncio.to_thread(self._capture.start):
            self._last_error = (
                "Das Mikrofon ließ sich nicht öffnen. Prüfe unter "
                "Windows-Einstellungen → Datenschutz → Mikrofon, ob der Zugriff "
                "erlaubt ist. Ich versuche es im Hintergrund weiter."
            )
            self._mikrofon_weiter_versuchen()
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
            self._wake_word.phrases[0] if self._wake_word.phrases else "Hallo Synapse",
        )
        return True

    def _mikrofon_weiter_versuchen(self) -> None:
        """Versucht im Hintergrund weiter, an das Mikrofon zu kommen.

        Der Fehler, um den es geht, ist fast immer vorübergehend: Windows
        wechselt gerade das Gerät, eine Videokonferenz hält es fest, ein
        Kopfhörer wird umgesteckt. Wer da nur einmal beim Start fragt, ist
        für den Rest des Tages taub - und niemand merkt es, bis er den Orb
        anspricht und nichts geschieht.

        Deshalb: alle dreißig Sekunden ein Versuch, zwanzig Mal, dann ist
        gut. Öffnet sich das Mikrofon, geht der Orb in Bereitschaft, als
        wäre nichts gewesen; das Protokoll behält den Vorfall.
        """

        if self._mikrofon_heilung is not None and not self._mikrofon_heilung.done():
            return

        async def _schleife() -> None:
            for _ in range(20):
                await asyncio.sleep(30)
                if self._capture.is_running or not self._enabled:
                    return
                if not await asyncio.to_thread(self._capture.start):
                    continue
                self._last_error = ""
                await self._set_state(VoiceState.SLEEPING)
                self._security.record_action(
                    "voice", "microphone",
                    "Mikrofon nach Wartezeit geöffnet, wartet auf das Weckwort.",
                )
                asyncio.create_task(self._warm_up(), name="ai-orb-voice-warmup")
                logger.info("Das Mikrofon ist wieder da - die Sprachsteuerung läuft.")
                return
            logger.warning(
                "Das Mikrofon war auch nach zehn Minuten nicht zu öffnen - "
                "es wird nicht weiter versucht. MIKROFON-PRUEFEN.bat hilft "
                "bei der Suche."
            )

        self._mikrofon_heilung = asyncio.create_task(
            _schleife(), name="ai-orb-mikrofon-heilung"
        )

    async def stop(self) -> None:
        """Beendet die Sprachsteuerung und gibt das Mikrofon frei."""

        self._vorlesung_timer_abbrechen()
        self._vorlesung.pausieren()
        self._player.stop()
        if self._speaking_task is not None and not self._speaking_task.done():
            self._speaking_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._speaking_task
        self._speaking_task = None

        if self._mikrofon_heilung is not None and not self._mikrofon_heilung.done():
            self._mikrofon_heilung.cancel()
        self._mikrofon_heilung = None

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

        self._unterbrechungsweg_pruefen()

    def _unterbrechungsweg_pruefen(self) -> None:
        """Warnt, wenn der Orb gar nicht mehr zu unterbrechen ist.

        Es gibt genau drei Wege: das gesprochene Stop-Wort, das akustische
        Dazwischenreden (``voice.barge_in``) und eine Taste
        (``voice.interrupt_key``). Jeder einzelne laesst sich aus gutem
        Grund abschalten - alle drei zusammen nicht. Bis zum 26.08.2026
        waren sie es, ohne dass irgendwo etwas davon stand: barge_in aus
        wegen des Lautsprecherechos, keine Taste eingetragen, und der
        Stop-Spaeher stumm, weil die lokale Stimme ihn ausschaltete. Der
        Benutzer sass vor einem Orb, den er nicht mehr stoppen konnte, und
        das Protokoll meldete "Die Stop-Wort-Erkennung ist bereit".

        Diese Zeile ist deshalb keine Feinheit, sondern die Zusicherung,
        dass so ein Zustand nie wieder stillschweigend eintritt.
        """

        stopwort_moeglich = bool(self._stop_words) and (
            self._stop_waehrend_lokaler_stimme
            # Ohne den Schalter haengt es an der Stimme: Eine lokale
            # (rechenintensive) Engine schaltet den Spaeher ab.
            or not self._stimme_lokal
        )
        if stopwort_moeglich or self._barge_in or self._interrupt_taste:
            return
        logger.warning(
            "Der Orb ist derzeit NICHT zu unterbrechen: Das Stop-Wort ist "
            "wirkungslos (lokale Stimme und voice.stop_waehrend_lokaler_"
            "stimme steht auf false), voice.barge_in ist aus und "
            "voice.interrupt_key ist leer. Mindestens einer der drei Wege "
            "sollte offen sein."
        )


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

    def _stop_spaeher_fuer_ausgabe(self, result: Any) -> None:
        """Schaltet den Stop-Spaeher fuer die Wiedergabe dieses Satzes ein.

        Hier lag der Grund, warum das Stop-Wort ueberhaupt nicht mehr
        griff. Frueher stand hier sinngemaess: Ist die Stimme lokal, lass
        Whisper aus - sonst nimmt es der Erzeugung des naechsten Satzes die
        CPU weg. Die Begruendung stimmt, die Folgerung war zu breit.

        Denn die Stimme des Benutzers IST lokal: In ``config.yaml`` steht
        als einzige Engine ``supertonic``, und die traegt
        ``avoid_stop_transcription`` in jedem Ergebnis. Damit war die
        Bedingung immer wahr, der Spaeher wurde nie eingeschaltet, und im
        Protokoll stand ab dem 25.08.2026 kein einziges Hoerfenster mehr -
        nur noch "Die Stop-Wort-Erkennung ist bereit", ohne dass sie je
        etwas zu hoeren bekam.

        Der alte Trost im Text ("Dazwischenreden bleibt trotzdem moeglich")
        traf ebenfalls nicht zu: Er setzt ``voice.barge_in`` voraus, und das
        steht auf ``false``, weil der Lautsprecher sonst ins Mikrofon
        spricht. Mit leerem ``interrupt_key`` waren damit ALLE drei Wege
        zu, den Orb zu unterbrechen.

        Jetzt gilt die Sperre nur noch dort, wo sie hingehoert: waehrend
        des ERZEUGENS (das schaltet die Schleife selbst ab, unmittelbar vor
        ``await pending``) und bei einem echten PCM-Strom, dessen Datei
        noch geschrieben wird. Waehrend des ABSPIELENS horcht der Spaeher -
        auch bei einer lokalen Stimme. Wer das nicht will, setzt
        ``voice.stop_waehrend_lokaler_stimme: false``; dann bleibt es beim
        alten Verhalten, und der Orb sagt beim Start, dass er nicht mehr zu
        unterbrechen ist.
        """

        context = getattr(result, "context", {}) or {}
        # Ein laufender PCM-Strom bleibt ausgenommen: Dort entsteht die
        # Datei noch waehrend des Abspielens, das ist echte Gleichzeitigkeit.
        strom_laeuft = context.get("pcm_stream") is not None
        if strom_laeuft:
            self._capture.set_stop_spotting(False)
            return
        if not self._stop_waehrend_lokaler_stimme and (
            context.get("avoid_stop_transcription")
            # Cachetreffer tragen nur Engine und Dateipfad. Die Kennung
            # bewahrt deshalb dieselbe Regel bei wiederholten Saetzen.
            or getattr(result, "engine", "") in {"supertonic", "pocket_tts"}
        ):
            self._capture.set_stop_spotting(False)
            return
        self._capture.set_stop_spotting(True)

    def _stop_window_aufnahmebereit(self) -> bool:
        """Ob ein weiteres Hoerfenster ueberhaupt gebraucht wird.

        Der Spaeher schrieb bisher bedingungslos: bei einer Antwort von 45
        Sekunden rund 75 WAV-Dateien, ueberwiegend die eigene
        Lautsprecherstimme. Angesehen wurde davon immer nur eines - die
        Erkennung laeuft einzeln, und gemerkt wird hoechstens ein weiteres.
        Alle uebrigen wurden geschrieben und ungelesen wieder geloescht.

        Gefragt wird hier im Aufnahme-Thread, also aus einem anderen Thread
        als dem, der die Felder setzt. Gelesen werden nur einzelne einfache
        Werte, und ein Fehlgriff kostet hoechstens ein Fenster zu viel oder
        zu wenig - keine Sperre wert.
        """

        if not self._listening_for_stop:
            return False
        if self._stop_transcriber.load_failed:
            # Ohne das kleine Modell wird ohnehin nicht geprueft.
            return False
        return not (
            self._stop_check_busy
            and getattr(self, "_pending_stop_window", None) is not None
        )

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

        if self._stop_transcriber.load_failed:
            # Hier stand der Rueckfall auf das grosse Modell: "lieber
            # langsam hinhoeren als gar nicht". Der Gedanke war richtig,
            # die Rechnung nicht. Das grosse Modell teilt sich die
            # Warteschlange mit den Saetzen des Benutzers, und in eine
            # lange Antwort fallen dutzende Fenster. Genau so entstand der
            # Stau vom 17.08.: erkannt wurde die eigene Stimme, gewartet
            # hat der Benutzer. Ein spaetes "stop" ist nicht besser als
            # keines, wenn es die naechste Frage um Minuten verzoegert.
            #
            # Die Notbremse bleibt: Ein kurzes "Stop" als eigene Aeusserung
            # wird weiterhin geprueft (siehe _ist_kurzer_stop), und das
            # Dazwischenreden meldet der Pegel ohne jede Erkennung.
            if not getattr(self, "_stop_grossmodell_gemeldet", False):
                self._stop_grossmodell_gemeldet = True
                logger.warning(
                    "Das kleine Erkennungsmodell liess sich nicht laden - "
                    "das Stop-Wort wird waehrend des Sprechens nicht mehr "
                    "aus Hoerfenstern geprueft. Sprich den Orb an oder sag "
                    "'Stop', sobald er eine Pause macht."
                )
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
                    # Mit Verfallszeit: Ein Fenster, das waehrend der
                    # vorigen Erkennung alt geworden ist, wird verworfen
                    # statt erkannt. Es beantwortet die Frage von
                    # vorgestern und kostet die Zeit des aktuellen.
                    transcript = await self._stop_transcriber.transcribe(
                        aktuell,
                        verfallen_nach=getattr(self, "_stop_fenster_verfall", 2.5),
                    )
                    self._spaeher_merken(transcript.text)
                    # Schlecht erkannte Fenster zaehlen nicht.
                    #
                    # Dieselbe Regel gilt eine Handvoll Zeilen weiter unten
                    # schon fuer den Zwischenruf, und sie gilt hier aus
                    # demselben Grund: In einem unsicheren Fenster ERFINDET
                    # die Erkennung, und Erfundenes sah bisher aus wie ein
                    # Abbruchwort.
                    # getattr: Ein Ergebnis ohne Sicherheitsangabe laesst
                    # sich nicht als unsicher verwerfen - dann gilt es als
                    # verlaesslich, sonst risse die Notbremse an einem
                    # fehlenden Feld.
                    sicherheit = float(getattr(transcript, "confidence", 1.0) or 1.0)
                    schwelle = getattr(self, "_fremd_mindestsicherheit", 0.0)
                    treffer = (
                        self._stopwort_treffer(transcript.text)
                        if sicherheit >= schwelle
                        else None
                    )
                    if self._listening_for_stop and treffer:
                        logger.info(
                            "Stop-Wort %r erkannt (Fenster: %r) – "
                            "Sprachausgabe wird beendet.",
                            treffer,
                            transcript.text[:60],
                        )
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

        # Beginnt im kurzen Fenster zwischen zwei Vorlesungsabschnitten eine
        # Wortmeldung, hat sie Vorrang. Das geschieht vor der (mehrsekündigen)
        # Transkription; andernfalls könnte der Folgeabschnitt anlaufen,
        # während Whisper den Einwand noch liest.
        self._loop.call_soon_threadsafe(self._vorlesung_timer_abbrechen)

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
        trace, trace_token = start_turn_trace()
        turn = VoiceTurn(duration_seconds=duration)
        turn.trace_id = trace.turn_id
        self._active_turn_trace = trace
        claimed_turn = False

        try:
            # Spricht Marc gerade ueber Handy oder iPad mit Synapse, hoert
            # das PC-Mikrofon ihn meist mit. Bis 12.11.2026 antwortete der
            # PC dann zusaetzlich - auf halb Verstandenes, still in den Chat,
            # waehrend Marc gar nicht vor dem PC sass. Solange ein Geraet
            # aktiv ist, bleibt das PC-Mikrofon deshalb stumm.
            if time.monotonic() < float(getattr(self, "lokal_ruhig_bis", 0.0) or 0.0):
                logger.debug("PC-Mikrofon ruht - das Handy/iPad ist im Gespraech.")
                return

            # Solange der Orb spricht, gilt nur eine Frage: Fiel das
            # Stop-Wort? Alles andere wird überhört – auch die eigene
            # Stimme des Orb, die das Mikrofon mithört. Deshalb wird hier
            # trotz laufender Ausgabe transkribiert, aber nichts als Befehl
            # ausgeführt.
            #
            # Und zwar mit dem KLEINEN Modell und kurzer Verfallszeit. Am
            # 17.08. lief hier das grosse: Waehrend einer langen Antwort
            # wurde jeder mitgehoerte Schnipsel der eigenen Stimme voll
            # erkannt, die Schlange wuchs auf drei Minuten, und der echte
            # Satz des Benutzers kam nie an. Fuer die Frage "fiel das
            # Stop-Wort?" reicht das kleine Modell; ein Fenster, das
            # aelter als ein paar Sekunden ist, ist ohnehin kein Stop mehr.
            if self._listening_for_stop:
                erkenner = (
                    self._transcriber
                    if self._stop_transcriber.load_failed
                    else self._stop_transcriber
                )
                transcript = await erkenner.transcribe(path, verfallen_nach=6.0)
                if self._contains_stop_word(transcript.text):
                    logger.info("Stop-Wort erkannt – Sprachausgabe wird beendet.")
                    self.interrupt()
                return

            if self._processing or self._turn_claimed:
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
                # Mit Dauer: Daran laesst sich ablesen, ob die Aufnahme
                # fuer einen verlaesslichen Abdruck ueberhaupt lang genug
                # war - der haeufigste Grund, wenn die EIGENE Stimme
                # faelschlich durchfaellt. (Der Wortlaut kann hier nicht
                # stehen: Was als fremd gilt, wird bewusst nie erkannt
                # und nirgends aufgeschrieben.)
                logger.info(
                    "Fremde Stimme überhört (Ähnlichkeit %.2f, Schwelle %.2f, "
                    "Dauer %.1f s).",
                    urteil.aehnlichkeit,
                    urteil.schwelle,
                    duration,
                )
                await self._event_bus.publish("voice.speaker.rejected", urteil.to_dict())
                return

            if (
                self._adapt_to_user_rhythm
                and urteil.geprueft
                # Der Sprechrhythmus gehoert dem Benutzer. Eine zugelassene
                # Gaststimme darf sprechen, aber nicht den Tonfall des Orbs
                # zu sich hinueberziehen.
                and urteil.wer != "gast"
                and self._stimme.rhythmus_aktualisieren(path)
            ):
                self._apply_learned_speech_style()

            # Ab hier ist klar: Eine zugelassene Stimme hat gesprochen.
            # Was vorher unterbrochen wurde, ist damit abgeschlossen -
            # die naechste Rede darf wieder sprechen.
            self._neue_rede()
            self._letztes_urteil = urteil

            # Freie Ansprache: Die nachweislich erkannte Stimme braucht
            # kein Weckwort. NACHWEISLICH heisst geprueft - eine zu kurze
            # oder unlesbare Aufnahme kommt zwar durch (im Zweifel wird
            # zugehoert), weckt aber nicht: Sonst weckte jedes Husten den
            # Orb, sobald kein Profil da ist oder die Pruefung scheitert.
            # getattr statt Zugriff: Teil-Aufbauten (Tests, Werkzeuge)
            # haben die Felder nicht immer, und der Aeusserungsweg darf
            # daran nicht scheitern.
            if (
                getattr(self, "_freie_ansprache", False)
                and not getattr(self, "_ruhe", False)
                and urteil.geprueft
                and self._is_asleep()
            ):
                logger.info(
                    "Erkannte Stimme (%s, Aehnlichkeit %.2f) - der Orb ist "
                    "ohne Weckwort ansprechbar.",
                    urteil.wer or "benutzer",
                    urteil.aehnlichkeit,
                )
                self._wake()
                await self._set_state(VoiceState.LISTENING)

            # Im Schlaf hoert der Orb nur auf sein Weckwort - und dafuer
            # braucht es das grosse Modell nicht.
            #
            # Genau hier entstand die Traegheit der letzten Tage: Am 14.08.
            # wurden 600 von 646 Aeusserungen voll transkribiert und danach
            # weggeworfen - Zimmergeraeusche, Gespraechsfetzen, die eigene
            # Lautsprecherstimme. Jede kostete 5-8 Sekunden Rechenzeit, in
            # der die Saetze des Benutzers warteten. Deshalb sichtet im
            # Schlaf zuerst das KLEINE Modell (das ohnehin fuers Stop-Wort
            # laeuft, zwei Kerne, 3-4x schneller). Nur wenn es das Weckwort
            # findet, liest das grosse Modell die Aufnahme noch einmal
            # richtig - dann lohnt sich die Sorgfalt, denn im selben Satz
            # steht meist schon der Auftrag.
            #: Was die kleine Erkennung im Schlaf gehoert hat - falls sie das
            #: Weckwort SICHER erkannt hat. Siehe nach der grossen Erkennung.
            vorpruefung_mit_weckwort = None
            if self._is_asleep():
                # Ein Weckruf braucht Stimme: "Hallo Orb" dauert laenger als
                # eine Dreiviertelsekunde. Kuerzeres ist Knacken, Husten,
                # ein Wortfetzen - keine Erkennung wert.
                if duration < 0.75:
                    return
                if not self._stop_transcriber.load_failed:
                    vorpruefung = await self._stop_transcriber.transcribe(
                        path, verfallen_nach=15.0
                    )
                    # Die Sichtung ist absichtlich GROSSZUEGIG: Sie darf
                    # Muell durchlassen (das grosse Modell raeumt dann auf),
                    # aber nie einen echten Weckruf verschlucken. Deshalb
                    # geht neben dem erkannten Weckwort auch jeder Anklang
                    # davon zur grossen Erkennung weiter.
                    klein = vorpruefung.text.lower()
                    weckverdacht = (
                        self._wake_word.detect(vorpruefung.text).detected
                        # Anklaenge an "Synapse": die kleine Erkennung hoert
                        # daraus oft "Sinapse", "Sünapse" oder "Sie Napse".
                        or any(
                            anklang in klein
                            for anklang in (
                                "synap", "sinap", "zynap", "cynap", "sünap",
                                "sunap", "napse", "synab",
                            )
                        )
                        or "hallo" in klein
                        or "halo" in klein
                        or "hey" in klein
                    )
                    # Sichtbar machen, was die kleine Erkennung gehoert hat.
                    # Bisher endete dieser Weg ohne jede Zeile: Wurde ein
                    # Weckwort falsch verstanden, verschwand es lautlos, und
                    # im Protokoll liess sich nicht nachsehen, WARUM der Orb
                    # nicht reagierte.
                    sicherheit = getattr(vorpruefung, "confidence", 0.0) or 0.0
                    if not weckverdacht:
                        logger.info(
                            "Schlaf-Vorpruefung: kein Weckwort-Anklang (%.2f): %r",
                            sicherheit, vorpruefung.text[:70],
                        )
                        trace.mark("transcript_ready")
                        turn.transcript = vorpruefung.text
                        return
                    logger.info(
                        "Schlaf-Vorpruefung: Weckverdacht (%.2f): %r - die grosse "
                        "Erkennung liest die Aufnahme noch einmal.",
                        sicherheit, vorpruefung.text[:70],
                    )
                    if self._wake_word.detect(vorpruefung.text).detected:
                        vorpruefung_mit_weckwort = vorpruefung

            # Mit Verfallszeit: Eine Aufnahme, die eine halbe Minute auf die
            # Erkennung gewartet hat, ist keine Anweisung mehr - der
            # Benutzer hat laengst neu gesprochen oder aufgegeben. Sie doch
            # zu erkennen verzoegert nur die Aufnahme, die noch zaehlt.
            transcript = await self._transcriber.transcribe(path, verfallen_nach=25.0)

            # Die grosse Erkennung macht es nicht immer besser. Protokoll
            # 06.11.2026, 14:24: klein "Hey Synapse, wie geht das dir heute?",
            # gross "Ersteinabs, die Gette Stilhaeute." - das Weckwort war
            # weg, der Orb blieb stumm, obwohl er richtig gehoert hatte.
            # Hat die kleine das Weckwort sicher erkannt und die grosse
            # nicht, gilt die kleine.
            if (
                vorpruefung_mit_weckwort is not None
                and not self._wake_word.detect(transcript.text).detected
            ):
                logger.info(
                    "Die grosse Erkennung verlor das Weckwort (%r); es gilt die "
                    "kleine: %r",
                    transcript.text[:70],
                    vorpruefung_mit_weckwort.text[:70],
                )
                transcript = vorpruefung_mit_weckwort
            trace.mark("transcript_ready")
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

            # Die erste Pruefung auf ``_processing`` steht bewusst VOR der
            # Transkription, damit ein bereits laufender Auftrag keine neue,
            # teure Erkennung startet. Zwei Hoerfenster koennen diese Stelle
            # aber nahezu gleichzeitig passieren: Waehren beide noch
            # transkribieren, ist ``_processing`` bei beiden zunaechst False.
            # Ohne eine zweite Pruefung starteten danach zwei Modell- und
            # Werkzeuglaeufe parallel. Im Betriebsprotokoll war genau das im
            # Abstand von vier Sekunden zu sehen; der Orb wirkte danach
            # minutenlang blockiert und seine Zustaende sprangen.
            if self._processing or self._turn_claimed:
                if self._contains_stop_word(transcript.text):
                    logger.info(
                        "Stop-Wort nach paralleler Transkription erkannt - "
                        "der laufende Auftrag wird abgebrochen."
                    )
                    self.verarbeitung_abbrechen()
                else:
                    logger.info(
                        "Spaeteres Hoerfenster nicht parallel gestartet; "
                        "der laufende Auftrag bleibt eindeutig."
                    )
                return

            # Atomar fuer diese Ereignisschleife reservieren: Bis zum
            # naechsten ``await`` kann kein zweites Hoerfenster dazwischen.
            # Das schliesst das verbliebene Rennen zwischen der zweiten
            # Pruefung und dem spaeteren ``_respond``.
            self._turn_claimed = True
            claimed_turn = True

            # Kauderwelsch gar nicht erst weiterreichen.
            #
            # Whisper verhakt sich gelegentlich und wiederholt dasselbe
            # Wort ("ruhig ruhig ruhig ruhig ruhig") - ein bekanntes
            # Verhalten, das mit dem Gesagten nichts zu tun hat. Solche
            # Aeusserungen sind kein Befehl und auch keine Nachfrage wert.
            if _ist_geplapper(transcript.text):
                logger.info("Verworfen: Wortwiederholung ohne Inhalt.")
                return

            # Und die andere Sorte Artefakt: Whispers Standardsaetze.
            #
            # Auf Stille oder Rauschen gibt das Modell gern das aus, was in
            # seinen Trainingsdaten am Ende von Videos stand - "Untertitel
            # im Auftrag des ZDF" steht im Protokoll des Benutzers woertlich
            # (31.08.2026, 12:46, zweimal hintereinander). Das ist kein
            # Satz, den jemand gesagt hat; darauf zu antworten heisst, ins
            # Gespraech zu platzen, waehrend der Benutzer noch redet.
            if _ist_whisper_phantom(transcript.text):
                logger.info(
                    "Verworfen: Whisper-Standardsatz ohne Sprecher (%r).",
                    transcript.text[:60],
                )
                return

            # Und das Echo des eigenen Vorgabetexts. Whisper gibt auf Rauschen
            # gern woertlich den initial_prompt zurueck. Am 06.11.2026 stand
            # darin "Hey Synapse, lerne meine Stimme" - und der Orb startete
            # deshalb immer wieder das Einlernen und fragte nach drei Saetzen.
            vorgabe = getattr(self, "_vorgabetext", "")
            if _ist_vorgabe_echo(transcript.text, vorgabe):
                logger.info(
                    "Verworfen: Echo des Vorgabetexts der Erkennung (%r).",
                    transcript.text[:60],
                )
                return

            # Fremde Schrift: Auf Geraeusche antwortet die Cloud-Erkennung
            # gelegentlich in einer ganz anderen Sprache ("음, 그거." am
            # 07.11.2026, 07:2x). Marc spricht Deutsch - ein Satz, der
            # ueberwiegend nicht aus lateinischen Buchstaben besteht, ist
            # kein Auftrag. Der Orb hat darauf bisher trotzdem geantwortet.
            if _ueberwiegend_fremde_schrift(transcript.text):
                logger.info(
                    "Verworfen: Erkennung in fremder Schrift (%r).",
                    transcript.text[:60],
                )
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
            if claimed_turn:
                self._turn_claimed = False
            # Die Aufnahme wird nicht aufbewahrt. Vorgabe: Keine
            # Mikrofonaufnahmen werden dauerhaft gespeichert.
            #
            # Ausnahme nur auf ausdruecklichen Wunsch zur Fehlersuche
            # (voice.input.diagnose_aufnahmen: N): die letzten N Aufnahmen
            # bleiben in logs/aufnahmen liegen, aeltere werden geloescht.
            self._diagnose_aufnahme_behalten(path)
            with contextlib.suppress(OSError):
                path.unlink()
            turn.duration_seconds = time.perf_counter() - started
            outcome = (
                "interrupted" if turn.interrupted else "answered" if turn.answered else "ignored"
            )
            turn.timings = trace.finish(outcome=outcome)
            self._remember(turn)
            if self._active_turn_trace is trace:
                self._active_turn_trace = None
            reset_turn_trace(trace_token)
            # War es nur ein fremdes Geraeusch, bleibt die Vorlesung aktiv.
            # Der Timer wurde vorsorglich beim Beginn der Aufnahme gestoppt
            # und wird hier erneut gesetzt. Eine echte Wortmeldung hat die
            # Sitzung in _handle_while_awake dagegen pausiert.
            vorlesung = getattr(self, "_vorlesung", None)
            if vorlesung is not None and vorlesung.aktiv and not self.is_busy:
                self._vorlesung_fortsetzung_planen()

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
        self._stimme_lernt_gast = False
        self._stimme_rueckweisungen = 0
        anzahl = max(2, self._stimme_anzahl)
        return (
            f"Ich höre jetzt genau hin. Sag mir bitte {anzahl} ganze Sätze, "
            "einen nach dem anderen – der Inhalt ist gleichgültig, es geht "
            "nur um den Klang. Jeder sollte ein paar Sekunden dauern."
        )

    async def gaststimme_lernen_starten(self) -> str:
        """Lässt eine WEITERE Stimme zu – auf ausdrücklichen Wunsch.

        Der Benutzer sagt "hör auf diese Stimme" und spielt dem Orb danach
        die andere Stimme vor (eine Person im Raum oder eine Aufnahme).
        Die nächsten Aufnahmen gelten als Proben dieser Gaststimme. Sie
        wird NEBEN der Benutzerstimme zugelassen, nie an ihrer Stelle, und
        gilt, bis der Benutzer "hör nur auf mich" sagt.
        """

        if not self._stimme.gelernt:
            return (
                "Dafür muss ich zuerst deine eigene Stimme kennen, sonst "
                "kann ich Gast und Hausherr nicht auseinanderhalten. Sag "
                "erst: lerne meine Stimme."
            )
        self._stimme_lernt = []
        self._stimme_lernt_gast = True
        self._stimme_rueckweisungen = 0
        anzahl = max(2, self._stimme_anzahl)
        return (
            f"Gut. Spiel mir jetzt {anzahl} ganze Sätze der anderen Stimme "
            "vor, einen nach dem anderen – jeder ein paar Sekunden lang. "
            "Ich höre dann auch auf diese Stimme, bis du sagst: hör nur "
            "auf mich."
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

    def _apply_learned_speech_style(self) -> None:
        """Übernimmt nur Rhythmuswerte aus dem lokalen Stimmprofil."""

        if not getattr(self, "_adapt_to_user_rhythm", False):
            return
        style = self._stimme.sprechstil
        tempo = float(style.get("tempo", 1.0))
        pause_ms = int(style.get("pause_ms", 180))
        # Das konfigurierte Grundtempo bleibt die Mitte; das Benutzerprofil
        # verändert es höchstens um zwölf Prozent.
        self._tts.set_rhythm_speed(max(0.88, min(1.12, tempo)))
        # Die Stimme selbst bringt bereits Atempausen mit. Das Profil darf
        # sie nuancieren, aber keine zusaetzlichen halben Sekunden zwischen
        # getrennt erzeugten Dateien einfuegen.
        self._sentence_pause = max(0.04, min(0.16, pause_ms / 1000.0))

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
        war_gast = getattr(self, "_stimme_lernt_gast", False)
        if war_gast:
            geklappt, meldung = self._stimme.gast_lernen(proben)
        else:
            geklappt, meldung = self._stimme.lernen(proben)
            if geklappt:
                self._apply_learned_speech_style()
        self._stimme_aufraeumen()

        await self._event_bus.publish(
            "voice.speaker.guest_enrolled" if war_gast else "voice.speaker.enrolled",
            self._stimme.status(),
        )
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
        self._stimme_lernt_gast = False
        self._stimme_rueckweisungen = 0

    def _diagnose_aufnahme_behalten(self, path: Path) -> None:
        anzahl = int(getattr(self, "_diagnose_aufnahmen", 0) or 0)
        if anzahl <= 0:
            return
        try:
            import shutil

            from backend.utils.paths import get_logs_dir

            ziel = get_logs_dir() / "aufnahmen"
            ziel.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                shutil.copy2(path, ziel / f"{time.strftime('%Y%m%d-%H%M%S')}-{path.name}")
            alle = sorted(ziel.glob("*.wav"))
            for alt in alle[:-anzahl]:
                with contextlib.suppress(OSError):
                    alt.unlink()
        except Exception:  # noqa: BLE001 - Fehlersuche darf nie stoeren.
            logger.debug("Diagnose-Aufnahme nicht gesichert.", exc_info=True)

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

    #: Saetze, mit denen der Benutzer eine WEITERE Stimme zulaesst.
    #: In entumlauteter Schreibweise, weil vor dem Vergleich normalisiert
    #: wird - Whisper schreibt mal "hör", mal "hoer".
    _GAST_ZULASSEN = (
        "hoer auf diese stimme",
        "hoere auf diese stimme",
        "hoer auch auf diese stimme",
        "hoere auch auf diese stimme",
        "hoer auf die naechste stimme",
        "hoere auf die naechste stimme",
        "hoer auch auf die naechste stimme",
        "auf eine andere stimme hoeren",
        "lern diese stimme",
        "lerne diese stimme",
        "merk dir diese stimme",
        "merke dir diese stimme",
        "gaststimme zulassen",
        "gaststimme lernen",
        "lerne die gaststimme",
    )

    #: Saetze, die alle Gaststimmen widerrufen. Der Satz des Benutzers
    #: woertlich ("hoer nur auf mich") plus naheliegende Abwandlungen.
    _NUR_AUF_MICH = (
        "hoer nur auf mich",
        "hoere nur auf mich",
        "hoer nur noch auf mich",
        "hoere nur noch auf mich",
        "nur auf mich hoeren",
        "nur noch auf mich hoeren",
        "vergiss die gaststimme",
        "vergiss die gaststimmen",
        "gaststimme vergessen",
        "gaststimmen vergessen",
        "vergiss die andere stimme",
    )

    def _stimmrecht(self) -> bool:
        """Ob die gerade sprechende Stimme ueber Stimmen bestimmen darf.

        Nur der Benutzer verwaltet, auf wen der Orb hoert. Eine
        zugelassene Gaststimme darf sprechen und fragen - aber weder
        Profile loeschen noch weitere Gaeste zulassen, sonst koennte ein
        Gast den Hausherrn aussperren. Ohne hinterlegtes Profil gibt es
        nichts zu schuetzen, und ein ungeprueftes Urteil (zu kurze
        Aufnahme) sperrt niemanden aus - im Zweifel wird zugehoert.
        """

        if not self._stimme.aktiv:
            return True
        # getattr statt Zugriff: Teil-Aufbauten (Tests, Werkzeuge) haben
        # das Feld nicht immer, und die Rechtepruefung darf daran nicht
        # scheitern - im Zweifel wird nicht ausgesperrt.
        urteil = getattr(self, "_letztes_urteil", None)
        if urteil is None or not urteil.geprueft:
            return True
        return urteil.wer != "gast"

    def _freie_benutzeransprache_aktiv(self) -> bool:
        """Ob die verifizierte Benutzerstimme unmittelbar gemeint ist.

        ``freie_ansprache`` soll mehr leisten als den schlafenden Orb zu
        wecken: Wenn die hinterlegte Benutzerstimme sicher erkannt wurde,
        ist genau diese Identitaet bereits die Anrede. Ein zusaetzlicher
        Sprachfilter darf den Satz danach nicht erneut wegen eines fehlenden
        "Hallo Orb" verwerfen. Gaststimmen bleiben bewusst ausgenommen.
        """

        urteil = getattr(self, "_letztes_urteil", None)
        return bool(
            getattr(self, "_freie_ansprache", False)
            and not getattr(self, "_ruhe", False)
            and urteil is not None
            and urteil.akzeptiert
            and urteil.geprueft
            and urteil.wer == "benutzer"
        )

    async def _stimme_befehl(self, text: str) -> bool:
        """Behandelt die Saetze rund um die hinterlegte Stimme.

        Returns:
            Ob der Satz einer davon war und behandelt wurde.
        """

        klein = text.lower()
        # Fuer die Gast-Befehle entumlautet, damit "hör" und "hoer"
        # dasselbe sind - wie beim Ringmenue.
        normalisiert = (
            klein.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss")
        )

        gast_zulassen = any(satz in normalisiert for satz in self._GAST_ZULASSEN)
        nur_auf_mich = any(satz in normalisiert for satz in self._NUR_AUF_MICH)
        verwaltet = (
            gast_zulassen
            or nur_auf_mich
            or any(satz in klein for satz in self._STIMME_NEU)
            or any(satz in klein for satz in self._STIMME_LERNEN)
            or any(satz in klein for satz in self._STIMME_VERGESSEN)
        )
        if verwaltet and not self._stimmrecht():
            await self._say(
                "Das entscheidet nur mein Benutzer mit seiner eigenen "
                "Stimme - dich höre ich als Gast.",
                emotion="freundlich",
            )
            return True

        if nur_auf_mich:
            await self._say(self._stimme.gaeste_vergessen(), emotion="freundlich")
            return True

        if gast_zulassen:
            await self._say(await self.gaststimme_lernen_starten(), emotion="freundlich")
            return True

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
                gaeste = int(stand.get("gaeste", 0) or 0)
                zusatz = (
                    " Dazu ist eine Gaststimme zugelassen."
                    if gaeste == 1
                    else f" Dazu sind {gaeste} Gaststimmen zugelassen."
                    if gaeste
                    else " Ich höre nur auf dich."
                )
                await self._say(
                    f"Ja. Ich habe deine Stimme aus {stand['aufnahmen']} "
                    f"Aufnahmen hinterlegt.{zusatz}"
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

        # Eine Sprechpause beendet niemals einen Tagebucheintrag. Nur der
        # ausdrueckliche Schlusssatz tut das.
        if self._tagebuch_diktat_aktiv:
            return False
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

        # Auch der Weckruf wird geprueft, nicht nur das Nachfragefenster.
        #
        # Am 18.08.2026 um 11:22:08 stand am Ende von fuenfzig Woertern
        # fremder Rede ein "Hallo Orb!". Whisper haengt vertraute
        # Wendungen an, wenn der Ton zerfaellt - und keine Wendung ist
        # diesem Mikrofon vertrauter als diese. Ohne die Pruefung hier
        # weckt so etwas den Orb, und danach steht das Nachfragefenster
        # der fremden Stimme 45 Sekunden lang offen.
        if self._hintergrund_erkennen:
            from backend.voice.gespraechsrichtung import einschaetzen

            richtung = einschaetzen(
                transcript.text, sicherheit=transcript.confidence
            )
            if not richtung.antworten:
                logger.info(
                    "Weckwort im Hintergrundgespraech ueberhoert (%s): %r - %s",
                    richtung.art, transcript.text[:70], richtung.grund,
                )
                await self._event_bus.publish(
                    "voice.background.detected",
                    {"text": transcript.text[:200], "weckwort": True,
                     **richtung.to_dict()},
                )
                return

        turn.woke = True
        logger.info("Weckwort erkannt (%.0f %%): '%s'", match.score * 100, match.phrase)

        # Das Weckwort hebt die Ruhe auf - es ist das einzige, das das tut.
        self._ruhe = False
        self._wake()
        await self._event_bus.publish(
            "voice.wake_word.detected",
            {"phrase": match.phrase, "score": round(match.score, 3), "command": match.command},
        )

        if match.has_command:
            # „Hallo Orb, wie spät ist es?" – gleich weiterarbeiten, statt
            # nachzufragen.
            if await self._menue_befehl(match.command):
                return
            if await self._tagebuch_aufnahme(match.command, turn):
                return
            # Ein Vorlesungsstart kommt sehr oft zusammen mit dem Weckwort.
            # Dieser Weg umgeht den normalen Wachfenster-Handler und muss die
            # feste Sitzungssteuerung deshalb selbst anwenden.
            vorlesungsbefehl = self._vorlesung.befehl(match.command)
            if vorlesungsbefehl == "pausieren":
                self._vorlesung.pausieren()
                await self._say("Die Vorlesung ist pausiert.", emotion="freundlich")
                return
            if vorlesungsbefehl == "start":
                auftrag = self._vorlesung.starten(match.command)
                await self._respond(auftrag, turn, vorlesungszug=True)
                return
            if vorlesungsbefehl == "fortsetzen":
                auftrag = self._vorlesung.fortsetzen()
                if auftrag:
                    await self._respond(auftrag, turn, vorlesungszug=True)
                    return
            await self._respond(match.command, turn)
        elif self._acknowledge:
            await self._set_state(VoiceState.LISTENING)
            await self._say(self._acknowledge_text, emotion="aufmerksam")
            self._wake()
        else:
            await self._set_state(VoiceState.LISTENING)

    # --- Diktiermodus ------------------------------------------------------------

    _TAGEBUCH_ENDE = re.compile(
        r"(?:^|\s)(?:"
        r"tagebuch(?:eintrag|eitrag)\s+beendet|"
        r"ende\s+des\s+(?:tagebuch\s*)?eintrag(?:s|es)|"
        r"(?:tagebuch\s*)?eintrag\s+ende|"
        r"änderung\s+beendet|aenderung\s+beendet|"
        r"ende\s+der\s+änderung|ende\s+der\s+aenderung"
        r")[.!?]*\s*$",
        re.IGNORECASE,
    )

    async def _tagebuch_aufnahme(self, text: str, turn: VoiceTurn) -> bool:
        """Fuehrt ein Tagebuchdiktat bis zum ausdruecklichen Schlusssatz."""

        from backend.orchestrator.orchestrator import parse_tagebuch_befehl

        text = text.strip()
        if not self._tagebuch_diktat_aktiv:
            befehl = parse_tagebuch_befehl(text)
            if befehl is None:
                return False
            if befehl.werkzeug not in {
                "tagebuch_diktat_start", "tagebuch_aenderung_start",
            }:
                # Auch Oeffnen, Entfernen und direkte Aenderungen muessen vor
                # der Hintergrundgespraechspruefung ankommen. Sie laufen dank
                # Tagebuch-Schnellweg lokal und ohne Sprachmodell.
                self._wake()
                await self._respond(text, turn)
                return True
            self._tagebuch_diktat_aktiv = True
            self._tagebuch_diktat_teile = []
            self._tagebuch_diktat_art = (
                str(befehl.argumente.get("modus", "ersetzen_gesamt"))
                if befehl.werkzeug == "tagebuch_aenderung_start"
                else "neu"
            )
            self._tagebuch_diktat_position = str(
                befehl.argumente.get("position", "letzter")
            )
            self._wake()
            if self._tagebuch_diktat_art == "neu":
                aufforderung = (
                    "Beginne jetzt mit dem Diktieren. Beende mit dem Satz: "
                    "Ende des Eintrages."
                )
            elif self._tagebuch_diktat_art == "anhaengen":
                aufforderung = (
                    "Diktiere jetzt die Ergänzung. Beende mit dem Satz: "
                    "Änderung beendet."
                )
            else:
                aufforderung = (
                    "Diktiere jetzt die vollständige neue Fassung. Beende mit "
                    "dem Satz: Änderung beendet."
                )
            await self._say(aufforderung)
            self._wartet_auf_antwort = True
            return True

        ende = self._TAGEBUCH_ENDE.search(text)
        abschnitt = text[:ende.start()].strip() if ende else text
        if abschnitt:
            self._tagebuch_diktat_teile.append(abschnitt)
            logger.info(
                "Tagebuchdiktat: Abschnitt %d aufgenommen (%d Zeichen).",
                len(self._tagebuch_diktat_teile), len(abschnitt),
            )

        self._wake()
        self._wartet_auf_antwort = True
        if not ende:
            # Absichtlich schweigen: Eine Antwort zwischen zwei Abschnitten
            # wuerde die Aufnahme unterbrechen und koennte selbst wieder vom
            # Mikrofon erfasst werden.
            return True

        if not self._tagebuch_diktat_teile:
            await self._say(
                "Es wurde noch kein Text aufgenommen. Diktiere weiter und "
                "sage danach: Ende des Eintrages."
            )
            self._wartet_auf_antwort = True
            return True

        gesamtdiktat = " ".join(self._tagebuch_diktat_teile).strip()
        logger.info(
            "Tagebuchdiktat vollständig: %d Abschnitte, %d Zeichen.",
            len(self._tagebuch_diktat_teile), len(gesamtdiktat),
        )
        self._tagebuch_diktat_aktiv = False
        self._tagebuch_diktat_teile = []
        self._wartet_auf_antwort = False
        if self._tagebuch_diktat_art == "neu":
            auftrag = f"Orb, neuer Tagebucheintrag: {gesamtdiktat}"
        elif self._tagebuch_diktat_art == "anhaengen":
            auftrag = f"Orb, ergänze den letzten Tagebucheintrag um: {gesamtdiktat}"
        else:
            lage = "ersten" if self._tagebuch_diktat_position == "erster" else "letzten"
            auftrag = (
                f"Orb, ersetze den {lage} Tagebucheintrag vollständig durch: "
                f"{gesamtdiktat}"
            )
        self._tagebuch_diktat_art = "neu"
        self._tagebuch_diktat_position = "letzter"
        await self._respond(auftrag, turn)
        return True

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
        #
        # ABER: dass es dastand, muss gemerkt werden. Wer den Orb beim
        # Namen ruft, meint den Orb - und nach dem Abschneiden steht der
        # Name nicht mehr im Text. Am 19.08.2026 um 12:11 hat genau das
        # fuenf Auftraege hintereinander verschluckt::
        #
        #     12:11:23  "Hallo Orb, genau dieses Dokument sollst du
        #                einlesen, bitte."   -> "unklar", geschwiegen
        #     12:12:30  "Hallo Orb, die Aufgabe ist klar an dich
        #                gerichtet ..."      -> "unklar", geschwiegen
        #
        # Die Richtungspruefung sah nur noch den Rest ohne Anrede und
        # entschied im Zweifel auf Schweigen - richtig gedacht, am
        # falschen Text angewandt.
        weckwort_gefallen = self._wake_word.detect(transcript.text).detected
        text = self._wake_word.strip_wake_word(transcript.text).strip()

        # Das Ringmenue ist lokale Oberflaechensteuerung. Es funktioniert
        # deshalb ohne Sprachmodell, Internet oder Werkzeugwahl.
        if await self._menue_befehl(text):
            self._wake()
            return

        # Vor Richtungs-, Laengen- und Sicherheitsfiltern: Im aktiven Modus
        # ist jede erkannte Aeusserung Teil des Eintrags. So beendet weder
        # eine Pause noch ein kurzer Satz oder eine niedrige Konfidenz das
        # Diktat versehentlich.
        if await self._tagebuch_aufnahme(text, turn):
            return

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

        # Bin ich ueberhaupt gemeint?
        #
        # Im Nachfragefenster galt bisher JEDE Aeusserung mit der Stimme des
        # Benutzers als Anweisung. Im Protokoll vom 17.08.2026 stehen die
        # Folgen: "Vielen Dank.", "Die Kirchenweine und Schachtwaesche.",
        # "Ihr seid, wenn ihr sich etwas spuertzuschreifen ..." - ein
        # Gespraech im Raum, ein Fernseher, die eigene Lautsprecherstimme.
        # Alles verarbeitet, alles beantwortet.
        #
        # Bei einer Gaststimme oder einer nicht verifizierbaren Aufnahme ist
        # die Frage nicht "verstehe ich den Satz?", sondern "war er an MICH
        # gerichtet?". Die sicher erkannte Benutzerstimme ist bei aktivierter
        # freier Ansprache dagegen selbst die Anrede. Sie nochmals nach Name,
        # Frageform oder Imperativ zu filtern machte das Weckwort faktisch
        # weiterhin notwendig.
        erkannter_benutzer = self._freie_benutzeransprache_aktiv()
        if (
            self._hintergrund_erkennen
            and not weckwort_gefallen
            and not erkannter_benutzer
        ):
            from backend.voice.gespraechsrichtung import einschaetzen

            richtung = einschaetzen(
                text,
                sicherheit=transcript.confidence,
                wurde_gefragt=self._wartet_auf_antwort,
            )
            if not richtung.antworten:
                # Mit allen Messwerten in EINER Zeile, auf Wunsch des
                # Benutzers (20.08.): Satz, Erkennungssicherheit, Stimm-
                # aehnlichkeit samt Schwelle und ob eine Rueckfrage offen
                # stand. Nur so laesst sich spaeter im Protokoll sehen,
                # WORAN ein zu Unrecht verworfener Satz gescheitert ist.
                urteil = getattr(self, "_letztes_urteil", None)
                logger.info(
                    "Nicht an mich gerichtet (%s): %r - %s "
                    "[verstanden %.2f, stimme %.2f/schwelle %.2f, "
                    "rueckfrage offen: %s]",
                    richtung.art, text[:120], richtung.grund,
                    transcript.confidence,
                    getattr(urteil, "aehnlichkeit", 0.0) or 0.0,
                    getattr(urteil, "schwelle", 0.0) or 0.0,
                    "ja" if self._wartet_auf_antwort else "nein",
                )
                await self._event_bus.publish(
                    "voice.background.detected",
                    {"text": text[:200], **richtung.to_dict()},
                )
                # Wach bleiben, aber schweigen: Wer nebenher spricht, will
                # oft gleich darauf doch etwas vom Orb.
                self._wake()
                return
        elif erkannter_benutzer and not weckwort_gefallen:
            logger.info(
                "Verifizierte Benutzerstimme gilt ohne Weckwort als direkte "
                "Ansprache."
            )
        # Ab hier gilt die Aeusserung als an den Orb gerichtet - auch dann,
        # wenn sie den Namen trug und die Pruefung uebersprungen wurde.
        self._wartet_auf_antwort = False

        # Und ab hier darf man es auch hoeren.
        #
        # Gemessen am 19.08.2026 ueber 112 beantwortete Runden: 5,8 s bis
        # der Satz erkannt ist, weitere 6,4 s bis das Modell das erste Wort
        # liefert. Zwoelf Sekunden Stille - in denen der Benutzer nicht
        # weiss, ob der Orb ihn gehoert hat, ob er arbeitet oder ob er
        # haengt. Genau das war "keine fluessige Konversation".
        #
        # Der Denk-Klang haengt am Zustandswechsel und kam deshalb erst,
        # wenn die Antwortschleife anlief. Hier steht der frueheste
        # Zeitpunkt, zu dem die Auskunft ehrlich ist: Der Satz ist erkannt
        # UND er war an den Orb gerichtet. Alles davor waere geraten -
        # und ein Ton auf jedes Zimmergeraeusch waere schlimmer als Stille.
        await self._set_state(VoiceState.THINKING)

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
            self._wartet_auf_antwort = True
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

        # Fortlaufende Vorlesung: feste Steuerung statt eines unverbindlichen
        # Versprechens des Sprachmodells. Ein Start oder "Fahre fort" baut
        # einen Abschnittsauftrag; ein Stop pausiert und behaelt den Stand.
        vorlesungsbefehl = self._vorlesung.befehl(text)
        vorlesungszug = False
        if vorlesungsbefehl == "pausieren":
            self._vorlesung_timer_abbrechen()
            self._vorlesung.pausieren()
            await self._say(
                "Die Vorlesung ist pausiert. Sag: Fahre mit der Vorlesung fort, "
                "dann mache ich an derselben Stelle weiter.",
                emotion="freundlich",
            )
            self._wake()
            return
        if vorlesungsbefehl == "start":
            text = self._vorlesung.starten(text)
            vorlesungszug = True
        elif vorlesungsbefehl == "fortsetzen":
            text = self._vorlesung.fortsetzen()
            vorlesungszug = bool(text)
        elif self._vorlesung.aktiv:
            # Eine Frage oder Bemerkung stoppt die aktuelle Rede, aber nicht
            # die Sitzung. Nach der Antwort setzt der finally-Block des
            # Hoerfensters den Folgezeitgeber erneut. Nur ein ausdrueckliches
            # Stop/Pause oben beendet die automatische Fortsetzung.
            self._vorlesung.benutzer_unterbricht()

        if self._is_dismissal(text):
            # Ruhe ist mehr als Schlaf: Bei freier Ansprache wuerde die
            # naechste eigene Aeusserung den Orb sofort wieder wecken -
            # das Wegschicken waere wirkungslos. Die Ruhe haelt, bis das
            # Weckwort faellt.
            self._vorlesung_timer_abbrechen()
            if self._vorlesung.aktiv:
                self._vorlesung.pausieren()
            self._ruhe = True
            weckwort = (
                self._wake_word.phrases[0] if self._wake_word.phrases else "Hallo Synapse"
            )
            await self._say(
                f"Alles klar, ich ziehe mich zurück. Sag '{weckwort}', "
                "wenn du mich wieder brauchst.",
                emotion="freundlich",
            )
            await self._set_state(VoiceState.SLEEPING)
            self._awake_until = 0.0
            return

        await self._respond(text, turn, vorlesungszug=vorlesungszug)

    async def _menue_befehl(self, text: str) -> bool:
        """Oeffnet oder schliesst das Ringmenue direkt per Sprache."""

        normalisiert = " ".join(
            text.lower()
            .replace("ü", "ue")
            .replace("ö", "oe")
            .replace("ä", "ae")
            .replace("ß", "ss")
            .strip(" .,!?:;")
            .split()
        )
        chat_oeffnen = {
            "chat", "chat oeffnen", "oeffne den chat", "oeffne chat",
            "chat einblenden", "zeige den chat", "zeig mir den chat",
            "chatfenster oeffnen", "oeffne das chatfenster",
        }
        chat_schliessen = {
            "chat schliessen", "schliesse den chat", "chat ausblenden",
            "chatfenster schliessen", "schliesse das chatfenster",
        }
        orb_beenden = {
            "orb beenden", "beende den orb", "beende orb", "orb schliessen",
            "schliesse den orb", "ai orb beenden", "ai-orb beenden",
            "programm beenden", "anwendung beenden",
        }
        oeffnen = {
            "menue", "menu", "menue einblenden", "menu einblenden",
            "menue oeffnen", "menu oeffnen", "oeffne das menue",
            "oeffne menue", "zeig das menue", "zeige das menue",
            "zeig mir das menue", "blende das menue ein",
        }
        schliessen = {
            "menue schliessen", "menu schliessen", "schliesse das menue",
            "schliess das menue", "blende das menue aus", "menue ausblenden",
            "menu ausblenden",
        }
        if normalisiert in chat_oeffnen:
            await self._event_bus.publish(event_types.ORB_CHAT_REQUESTED, {"action": "open"})
            return True
        if normalisiert in chat_schliessen:
            await self._event_bus.publish(event_types.ORB_CHAT_REQUESTED, {"action": "close"})
            return True
        if normalisiert in orb_beenden:
            await self._event_bus.publish(event_types.ORB_QUIT_REQUESTED, {"source": "voice"})
            return True
        if normalisiert in oeffnen:
            await self._event_bus.publish(event_types.ORB_MENU_REQUESTED, {"action": "open"})
            return True
        if normalisiert in schliessen:
            await self._event_bus.publish(event_types.ORB_MENU_REQUESTED, {"action": "close"})
            return True
        return False

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

    async def _respond(
        self,
        text: str,
        turn: VoiceTurn,
        *,
        vorlesungszug: bool = False,
    ) -> None:
        """Holt eine Antwort und spricht sie."""

        self._processing = True
        response_completed = False
        answer = ""
        # Die eigene Aufgabe merken: Ein "Stop" waehrend des Denkens bricht
        # genau sie ab (siehe verarbeitung_abbrechen).
        self._antwort_task = asyncio.current_task()
        try:
            await self._set_state(VoiceState.THINKING)
            # Laufende Vorlesungsabschnitte duerfen niemals mit einem
            # kuenstlichen Denkfueller beginnen. Bei normalen Antworten gilt
            # weiterhin die ausdruecklich konfigurierbare Richtlinie.
            cue = "" if vorlesungszug else self._human_speech.thinking_cue(text)
            if cue:
                # Nicht in den Antworttext mischen: Der Denklaut ist eine
                # zeitliche Reaktion und bleibt dadurch auch bei Streaming
                # genau einmal und vor der eigentlichen Antwort.
                await self._say(cue, emotion="nachdenklich")
                await self._set_state(VoiceState.THINKING)

            # Der Fluss-Weg, wenn er bereitsteht: denken, sprechen,
            # weiterdenken, weitersprechen. Er kommt zuerst, weil er das
            # ist, was sich für den Benutzer am flüssigsten anfühlt.
            mark_stage("answer_dispatched")
            if self._stream_speech and self._answer_stream is not None:
                spoke = await self._respond_streaming(text, turn)
                if spoke:
                    response_completed = True
                    return

            # Der gewöhnliche Weg – aber nicht mehr stumm bis zum Schluss:
            # Jeder fertig gedachte Satz wird sofort gesprochen, während
            # der Rest noch entsteht. Der Denkweg bleibt dabei vollständig,
            # mit Absicht, Gedächtnis, Professor und Werkzeugen.
            gesprochen = False
            self._satzstrom_starten()
            try:
                answer, _ = await self._answer(text, on_speech=self._sprich_satz)
            except Exception:  # noqa: BLE001
                logger.exception("Die Antwort konnte nicht erzeugt werden.")
                answer = (
                    "Da ist bei mir etwas schiefgegangen. Die Einzelheiten "
                    "stehen im Protokoll."
                )
            finally:
                gesprochen = await self._satzstrom_beenden()

            turn.answered = True

            if gesprochen:
                # Schon im Fluss gesagt. Ein zweites Vorlesen wäre kein
                # Nachdruck, sondern ein Fehler.
                response_completed = True
                return

            if not answer.strip():
                answer = "Dazu fällt mir gerade nichts ein."

            mark_stage("answer_tts_requested")
            # Ein Werkzeug-Rueckfall kann interne Rohdaten zurueckgeben. In
            # normalen Gespraechen niemals minutenlang URLs oder Trefferlisten
            # vorlesen. Vorlesungen sind davon ausgenommen; sie besitzen ihren
            # eigenen abschnittsweisen Ablauf.
            gesprochenes_answer = (
                answer if vorlesungszug else _gesprochene_kurzfassung(answer)
            )
            response_completed = await self._say(gesprochenes_answer)
        finally:
            self._processing = False
            self._antwort_task = None
            self._wake()
            # Satzweises Sprechen erzeugt mehrere tts.finished-Ereignisse.
            # Keines davon ist das Ende der ganzen Antwort. Erst hier ist
            # sicher, dass wirklich alle Sätze gesprochen wurden. Dadurch
            # wechseln Augen und Farbe einmal sauber auf Erfolg/Fehler,
            # statt zwischen jedem Satz zu flackern oder zu früh auf Idle
            # zurückzuspringen.
            if turn.answered and not self._interrupted.is_set():
                await self._set_state(VoiceState.LISTENING)
                await self._event_bus.publish(
                    "voice.response.finished",
                    {"completed": response_completed},
                )
            if vorlesungszug:
                erfolgreich = bool(
                    turn.answered
                    and response_completed
                    and not self._interrupted.is_set()
                )
                self._vorlesung.abschnitt_beendet(answer, erfolgreich=erfolgreich)
                if self._vorlesung.aktiv:
                    self._vorlesung_fortsetzung_planen()

    def _vorlesung_timer_abbrechen(self) -> None:
        """Verwirft einen noch nicht gestarteten Folgeabschnitt."""

        task = getattr(self, "_vorlesung_task", None)
        if task is not None and not task.done():
            task.cancel()
        self._vorlesung_task = None

    def _vorlesung_fortsetzung_planen(self) -> None:
        """Plant genau einen Folgeabschnitt nach dem Unterbrechungsfenster."""

        if not self._vorlesung.aktiv or self._loop is None:
            return
        vorhanden = self._vorlesung_task
        if vorhanden is not None and not vorhanden.done():
            return

        async def _fortsetzen() -> None:
            try:
                await asyncio.sleep(self._vorlesung_pause)
                # Ein gleichzeitig verarbeitetes Hoerfenster darf die
                # Fortsetzung verzoegern, aber nicht verlieren. Die fruehere
                # Fassung kehrte bei ``is_busy`` einfach zurueck; danach gab es
                # keinen Zeitgeber mehr und der Orb wartete unbegrenzt.
                while self._vorlesung.aktiv and self.is_busy:
                    await asyncio.sleep(0.35)
                if not self._vorlesung.aktiv:
                    self._vorlesung_task = None
                    return
                # Das Feld vor _respond freigeben: Dessen Abschluss darf
                # bereits den darauffolgenden Abschnitt planen.
                self._vorlesung_task = None
                self._neue_rede()
                turn = VoiceTurn(transcript="automatische Vorlesungsfortsetzung")
                logger.info(
                    "Vorlesung wird automatisch mit Abschnitt %d fortgesetzt.",
                    self._vorlesung.stand.naechster_abschnitt,
                )
                await self._respond(
                    self._vorlesung.naechster_auftrag(),
                    turn,
                    vorlesungszug=True,
                )
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001 - ein Folgefehler darf die Stimme nicht reissen.
                logger.exception("Die Vorlesung konnte nicht automatisch fortgesetzt werden.")
                self._vorlesung.pausieren()

        self._vorlesung_task = asyncio.create_task(
            _fortsetzen(), name="ai-orb-vorlesung-fortsetzen"
        )
        logger.info(
            "Vorlesungsfortsetzung in %.1f Sekunden geplant (Abschnitt %d).",
            self._vorlesung_pause,
            self._vorlesung.stand.naechster_abschnitt,
        )

    async def _sprich_satz(self, satz: str) -> bool:
        """Spricht einen einzelnen, fertig gedachten Satz.

        Diese Fassung geht an die Denkschicht: Sie ruft sie auf, sobald ein
        Satz beisammen ist – und zwar bevor die Antwort fertig ist. Wurde
        unterbrochen, wird nichts mehr gesprochen; „stop" soll auch
        mitten in einer entstehenden Antwort greifen.
        """

        if self._interrupted.is_set():
            return False
        mark_stage("answer_tts_requested")
        queue = self._satzstrom_queue
        if queue is None:
            return await self._say(satz)
        if self._satzstrom_failed:
            return False

        # Nicht auf die Wiedergabe warten: Sonst stoppt der Providerstrom an
        # jedem Punkt, und der naechste Satz wird erst NACH der vorherigen
        # Audiodatei erzeugt. Die gemessene tote Luecke betrug 1,1 bis 1,9 s.
        async def _vorbereiten() -> Any:
            # Die TTS-Engine selbst bleibt seriell (wichtig fuer lokale
            # Modelle), laeuft aber parallel zur Wiedergabe des Vorgaengers.
            if self._stimme_ist_cloud():
                async with self._satzstrom_cloud_slots:
                    return await self._tts.speak(satz, state="speaking")
            async with self._satzstrom_synth_lock:
                return await self._tts.speak(satz, state="speaking")

        pending = asyncio.create_task(_vorbereiten())
        await queue.put((satz, pending))
        return True

    def _stimme_ist_cloud(self) -> bool:
        """Ob die gerade aktive Stimme in der Cloud erzeugt wird."""

        aktiv = getattr(self._tts, "_active", None)
        if aktiv is None:
            reihe = getattr(self._tts, "_engines", None) or []
            aktiv = reihe[0] if reihe else None
        name = str(getattr(aktiv, "name", "") or "")
        return name in {"openai_tts", "elevenlabs", "edge_neural", "remote_tts", "speechgen"}

    def _satzstrom_starten(self) -> None:
        """Startet eine geordnete, vorproduzierende Satzwiedergabe."""

        if self._satzstrom_worker is not None and not self._satzstrom_worker.done():
            return
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._satzstrom_failed = False
        self._satzstrom_queue = queue
        self._satzstrom_worker = asyncio.create_task(self._satzstrom_abspielen(queue))

    async def _satzstrom_beenden(self) -> bool:
        """Schliesst den Satzstrom und wartet auf die letzte Wiedergabe."""

        queue = self._satzstrom_queue
        worker = self._satzstrom_worker
        if queue is None or worker is None:
            return False
        await queue.put(None)
        try:
            return bool(await worker)
        finally:
            self._satzstrom_queue = None
            self._satzstrom_worker = None
            self._satzstrom_failed = False

    async def _satzstrom_abspielen(self, queue: asyncio.Queue[Any]) -> bool:
        """Spielt vorproduzierte Saetze lueckenarm und in richtiger Folge."""

        first = await queue.get()
        if first is None:
            return False

        completed = True
        interrupted = False
        played_anything = False
        last_text = ""

        async with self._speech_lock:
            await self._set_state(VoiceState.SPEAKING)
            await self._event_bus.publish(
                event_types.TTS_STARTED, {"text": first[0], "stream": True}
            )
            self._listening_for_stop = True
            self._capture.mute(True)
            # Noch wird nichts abgespielt. Stop-Whisper jetzt zu starten
            # wuerde nur mit der lokalen TTS um dieselben CPU-Kerne kaempfen.
            self._capture.set_stop_spotting(False)

            current = first
            try:
                while current is not None:
                    text, pending = current
                    last_text = str(text)
                    self._letzte_saetze.append(self._woerter(last_text))
                    self._gesprochene_woerter = set().union(*self._letzte_saetze)

                    if self._interrupted.is_set():
                        pending.cancel()
                        interrupted = True
                        completed = False
                        break

                    try:
                        self._capture.set_stop_spotting(False)
                        result = await pending
                    except asyncio.CancelledError:
                        interrupted = True
                        completed = False
                        break

                    active_trace = getattr(self, "_active_turn_trace", None)
                    if active_trace is not None and "answer_tts_requested" in active_trace.stages:
                        active_trace.mark("answer_audio_ready")

                    if not result.succeeded:
                        self._last_error = result.error
                        logger.error("Die Sprachausgabe ist fehlgeschlagen: %s", result.error)
                        self._satzstrom_failed = True
                        completed = False
                        break

                    self._stop_spaeher_fuer_ausgabe(result)

                    played = await asyncio.to_thread(
                        self._play_tts_result_blocking, result
                    )
                    if not played or self._interrupted.is_set():
                        interrupted = self._interrupted.is_set()
                        self._satzstrom_failed = not interrupted
                        completed = False
                        break
                    played_anything = True

                    # Keine zusaetzliche sleep-Pause: Die WAV behaelt einen
                    # kontrollierten Atemrand. Der naechste, parallel erzeugte
                    # Satz kann unmittelbar anschliessen.
                    current = await queue.get()
            finally:
                # Noch nicht abgespielte Synthesen abbrechen, beispielsweise
                # nach einem gesprochenen "Stop".
                while not queue.empty():
                    queued = queue.get_nowait()
                    if queued is not None:
                        queued[1].cancel()
                self._listening_for_stop = False
                self._capture.set_stop_spotting(False)
                self._capture.mute(False)
                self._spaeher_bilanz()
                await self._event_bus.publish(
                    event_types.TTS_FINISHED,
                    {
                        "completed": completed,
                        "interrupted": interrupted,
                        "final": not self._processing,
                    },
                )

        if played_anything:
            self._wartet_auf_antwort = (
                last_text.rstrip().rstrip("'\"").endswith("?")
                or (
                    "beginne" in last_text.lower()
                    and "diktieren" in last_text.lower()
                )
            )
        if interrupted:
            self._wake()
            await self._set_state(VoiceState.LISTENING)
        return completed and played_anything

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
        turn.answered = True
        self._satzstrom_starten()

        try:
            async for piece in self._answer_stream(text):
                buffer += piece
                # Alle fertigen Saetze sofort in den Vorproduktionsstrom
                # geben. Die Synthese des Nachfolgers laeuft damit bereits,
                # waehrend der Vorgaenger zu hoeren ist.
                saetze: list[str] = []
                sentence, buffer = _take_complete_sentence(buffer)
                while sentence:
                    saetze.append(sentence)
                    sentence, buffer = _take_complete_sentence(buffer)
                if saetze:
                    # Die direkte Schnellspur nutzt denselben Vorproduktions-
                    # strom wie der vollstaendige Denkweg. Dadurch kann auch
                    # hier das Modell weiterliefern, waehrend Audio laeuft.
                    for satz in saetze:
                        await self._sprich_satz(satz)
                    if self._interrupted.is_set():
                        break

            # Was nach dem letzten Satzzeichen übrig blieb, noch sprechen.
            rest = buffer.strip()
            if rest and not self._interrupted.is_set():
                await self._sprich_satz(rest)
        except Exception:  # noqa: BLE001 - Fluss gescheitert, dann eben normal.
            logger.exception("Der Streaming-Weg ist gescheitert; Rückfall auf den ganzen Text.")
        return await self._satzstrom_beenden()

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
            gesprochen = await self._say_locked(text, emotion=emotion)

        # Endet die eigene Rede mit einer Frage, wartet der Orb auf die
        # Antwort. Das stand bisher NUR nach der Verstehens-Rueckfrage -
        # und genau daran scheiterte am 20.08. um 04:35:36 das "Ja,
        # bitte, tu das" des Benutzers: Der Orb hatte in seiner Antwort
        # selbst gefragt, die Zustimmung darauf galt der Richtungs-
        # pruefung aber als Zustimmung in einem fremden Gespraech.
        # Endet die Rede OHNE Frage, ist auch keine offen - dann faellt
        # das Zeichen zurueck.
        if gesprochen:
            self._wartet_auf_antwort = (
                str(text).rstrip().rstrip("'\"").endswith("?")
                or (
                    "beginne" in str(text).lower()
                    and "diktieren" in str(text).lower()
                )
            )
        return gesprochen

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
        # Erst waehrend der Wiedergabe horchen. Vorher konkurrierte Whisper
        # beim Erzeugen jedes Satzes mit der lokalen TTS um die CPU.
        self._capture.set_stop_spotting(False)

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

                    self._capture.set_stop_spotting(False)
                    result = await pending

                    active_trace = getattr(self, "_active_turn_trace", None)
                    if active_trace is not None and "answer_tts_requested" in active_trace.stages:
                        active_trace.mark("answer_audio_ready")

                    if not result.succeeded:
                        self._last_error = result.error
                        logger.error("Die Sprachausgabe ist fehlgeschlagen: %s", result.error)
                        completed = False
                        break

                    self._stop_spaeher_fuer_ausgabe(result)

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
                        self._play_tts_result_blocking, result
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
            self._spaeher_bilanz()
            await self._event_bus.publish(
                event_types.TTS_FINISHED,
                {
                    "completed": completed,
                    "interrupted": interrupted,
                    # Während einer Antwort ist dies nur ein Satz/Abschnitt.
                    # Standalone-Meldungen (Begrüßung, Rückfrage) sind final.
                    "final": not self._processing,
                },
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

    def _play_tts_result_blocking(self, result: Any) -> bool:
        """Spielt neue Streams und bleibt mit einfachen Test-Playern kompatibel."""

        method = getattr(self._player, "play_result_blocking", None)
        if callable(method):
            return bool(method(result))
        return bool(self._player.play_blocking(result.audio_path))

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

    def _spaeher_merken(self, text: str) -> None:
        """Hält fest, was ein Hörfenster ergeben hat."""

        self._spaeher_fenster = getattr(self, "_spaeher_fenster", 0) + 1
        gehoert = getattr(self, "_spaeher_gehoert", None)
        if gehoert is None:
            gehoert = self._spaeher_gehoert = []
        knapp = " ".join(str(text or "").split())[:40]
        if knapp and len(gehoert) < 12:
            gehoert.append(knapp)

    def _spaeher_bilanz(self) -> None:
        """Schreibt am Satzende auf, was der Späher gehört hat.

        Eine Zeile je gesprochenem Satz, nicht eine je Hörfenster: Fenster
        kommen mehrmals in der Sekunde, und ein Protokoll, das man nicht
        lesen kann, ist so gut wie keines. Die Zeile beantwortet die eine
        Frage, die bei einem nicht greifenden Stop-Wort zu klären ist -
        kam da ueberhaupt etwas an?
        """

        if not getattr(self, "_spaeher_fenster", 0):
            return
        logger.info(
            "Stop-Späher: %d Hörfenster, davon %d mit Text%s",
            self._spaeher_fenster,
            len(self._spaeher_gehoert),
            (" – " + " | ".join(self._spaeher_gehoert))
            if self._spaeher_gehoert
            else " (nichts verstanden).",
        )
        self._spaeher_fenster = 0
        self._spaeher_gehoert = []

    def _contains_stop_word(self, text: str) -> bool:
        """Ob eine Äußerung ein Stop-Wort enthält.

        Geprüft wird auf ganze Wörter, nicht auf Teilzeichenketten: „halt"
        soll nicht in „Gehalt" oder „Haltung" anschlagen, sonst bräche der
        Orb mitten im eigenen Satz ab.
        """

        return self._stopwort_treffer(text) is not None

    def _stopwort_treffer(self, text: str) -> str | None:
        """Das gefundene Abbruchwort - oder ``None``.

        Zwei Prüfungen hintereinander, und erst zusammen ergeben sie die
        richtige Strenge:

        1. ``stopwort_finden`` fasst weit. Es kennt Beugungen und die
           typischen Verhoerer des kleinen Modells ("stobb", "stopt"),
           denn genau die liefert es auf einem Fenster, in dem der eigene
           Lautsprecher mitlaeuft.
        2. Danach die Gegenprobe: Kommt das gefundene Wort dem nahe, was
           der Orb GERADE SELBST sagt, ist es sein Echo und kein
           Zwischenruf. Diese zweite Pruefung ist der Grund, warum die
           erste weit fassen darf.
        """

        # Eine leere Liste in der Konfiguration heisst: abgeschaltet. Das
        # muss sie auch heissen, sonst waere die Einstellung eine Luege.
        if not text or not self._stop_words:
            return None
        treffer = stopwort_finden(text, frozenset(self._stop_words))
        if treffer is None:
            return None
        # Die Gegenprobe entfaellt, solange der Orb nichts sagt: Dann gibt
        # es kein Echo, gegen das zu pruefen waere.
        #
        # getattr statt Zugriff: Die Notbremse darf an einem fehlenden
        # Feld nicht scheitern. Im Betrieb ist es immer gesetzt; nur
        # Pruefgeruest ohne vollstaendige Pipeline kommt ohne es aus, und
        # dort ist "kein Echo bekannt" genau die richtige Annahme.
        if not getattr(self, "_gesprochene_woerter", None):
            return treffer
        # Bei einer Wendung ("hoer auf") zaehlt sie nur dann als Echo,
        # wenn ALLE ihre Woerter im eigenen Satz stehen. Ein einzelnes
        # "auf" reicht nicht - sonst waere jede Wendung entwertet.
        teile = treffer.split()
        if all(self._naehe_zum_eigenen(teil) >= AEHNLICH_GENUG for teil in teile):
            logger.debug(
                "Stop-Verdacht %r verworfen - er steht im eigenen Satz.",
                treffer,
            )
            return None
        return treffer

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
            # Auch hier eine Verfallszeit: Ein "Stop", das sechs Sekunden
            # in der Schlange stand, bremst nichts mehr.
            transcript = await erkennung.transcribe(path, verfallen_nach=6.0)
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
        trace = getattr(self, "_active_turn_trace", None)
        if trace is not None and "answer_tts_requested" in trace.stages:
            trace.mark("answer_audible")
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

    @property
    def transcriber(self) -> "Transcriber":
        """Die Spracherkennung.

        Nach aussen sichtbar, weil ein Gerät ohne eigenes Mikrofon am
        Rechner - ein iPad im selben Netz - seine Aufnahme hierher
        schickt. Die Erkennung ist dieselbe; nur der Weg des Tons ist
        ein anderer.
        """

        return self._transcriber

    @property
    def tts(self) -> "TtsManager":
        """Die Sprachausgabe.

        Wird von aussen gebraucht, um eine Antwort zu *erzeugen*, ohne sie
        hier abzuspielen: Wer auf dem iPad fragt, will die Antwort auf dem
        iPad hören und nicht aus den Lautsprechern eines Rechners, vor dem
        niemand sitzt.
        """

        return self._tts

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
            "freie_ansprache": self._freie_ansprache,
            "ruhe": self._ruhe,
            "barge_in": self._barge_in,
            "last_error": self._last_error,
            "capture": self._capture.status(),
            "transcriber": self._transcriber.status(),
            "tts": self._tts.status(),
            "player": self._player.status(),
            "vorlesung": self._vorlesung.status(),
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
            + (self._wake_word.phrases[0] if self._wake_word.phrases else "Hallo Synapse")
            + "'."
        )


#: Saetze, die Whisper aus dem Nichts erzeugt.
#:
#: Sie stammen aus Untertiteldateien in den Trainingsdaten und tauchen
#: auf, wenn das Modell Stille oder Rauschen bekommt. Wer sie kennt, sieht
#: sie sofort - der Orb sah sie bisher als Aeusserung an.
_PHANTOMSAETZE: tuple[str, ...] = (
    "untertitel im auftrag des zdf",
    "untertitelung im auftrag des zdf",
    "untertitelung des zdf",
    "untertitel der amara org community",
    "untertitel von stephanie geiges",
    "untertitel im auftrag des swr",
    "untertitel im auftrag des wdr",
    "mehr infos auf amara org",
    "vielen dank fuer das zuschauen",
    "vielen dank fuers zuschauen",
    "vielen dank fuer ihre aufmerksamkeit und auf wiedersehen",
    "abonniert diesen kanal",
    "copyright wdr",
)


def _ist_whisper_phantom(text: str) -> bool:
    """Ob eine Erkennung einer von Whispers Standardsaetzen ist.

    Geprueft wird streng: Der bereinigte Text muss im Kern AUS so einem
    Satz bestehen, nicht ihn bloss enthalten. Sonst verschluckte der Orb
    eine echte Frage, in der zufaellig "vielen Dank" vorkommt.
    """

    bereinigt = str(text or "").lower()
    for zeichen in ".,!?;:\u2026\"'()[]-\u2013\u2014":
        bereinigt = bereinigt.replace(zeichen, " ")
    bereinigt = (
        bereinigt.replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
        .replace("ß", "ss")
    )
    # Jahreszahlen haengt Whisper gern an ("Untertitel im Auftrag des ZDF, 2020").
    bereinigt = " ".join(
        wort for wort in bereinigt.split() if not wort.isdigit()
    )
    if not bereinigt:
        return False

    for satz in _PHANTOMSAETZE:
        if bereinigt == satz or bereinigt.startswith(satz):
            return True
        # Umgekehrt auch: "untertitel des zdf" ist eine Kurzform.
        if satz.startswith(bereinigt) and len(bereinigt) >= 20:
            return True
    return False


def _normalisiert(text: str) -> str:
    bereinigt = str(text or "").lower()
    for zeichen in ".,!?;:\u2026\"'()[]-\u2013\u2014":
        bereinigt = bereinigt.replace(zeichen, " ")
    bereinigt = (
        bereinigt.replace("ü", "ue").replace("ä", "ae").replace("ö", "oe")
        .replace("ß", "ss")
    )
    return " ".join(bereinigt.split())


def _ist_vorgabe_echo(text: str, vorgabe: str) -> bool:
    """Ob die Erkennung nur ein Stueck des eigenen Vorgabetexts ist.

    Kurze Erkennungen (unter fuenf Woertern) gelten nie als Echo - "Hallo
    Synapse" darf natuerlich weiterhin wecken, auch wenn es in der Vorgabe
    steht.
    """

    kern = _normalisiert(text)
    vorlage = _normalisiert(vorgabe)
    if not kern or not vorlage or len(kern.split()) < 5:
        return False
    return kern in vorlage


def _ueberwiegend_fremde_schrift(text: str) -> bool:
    """Ob die Buchstaben eines Textes ueberwiegend nicht lateinisch sind."""

    buchstaben = [z for z in str(text or "") if z.isalpha()]
    if not buchstaben:
        return False
    lateinisch = sum(1 for z in buchstaben if ord(z) < 0x250)
    return lateinisch / len(buchstaben) < 0.5


def _ist_geplapper(text: str) -> bool:
    """Ob eine Erkennung nur aus Wortwiederholungen besteht.

    Whisper verhakt sich gelegentlich und gibt dasselbe Wort ein Dutzend
    Mal aus. Im Protokoll des Benutzers steht so ein Fall woertlich:
    "Ja... ruhig ruhig ruhig ruhig ruhig ruhig ruhig...".

    Das ist keine Aeusserung, sondern ein Artefakt. Es weiterzureichen
    hiesse, das Sprachmodell ueber ein Wort nachdenken zu lassen, das
    niemand gesagt hat.
    """

    # Ganze Saetze in Schleife: "Es geht nicht um die Zeit. Es geht nicht um
    # die Zeit. Es geht nicht um die Zeit." (06.11.2026, 16:11) - derselbe
    # Satz dreimal ist ein Verhaken der Erkennung, keine Aeusserung.
    saetze = [
        " ".join(teil.lower().split())
        for teil in re.split(r"[.!?\u2026]+", str(text or ""))
        if teil.strip()
    ]
    if len(saetze) >= 3 and len(set(saetze)) == 1:
        return True

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
