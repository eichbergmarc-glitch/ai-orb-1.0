"""Die Stop-Notbremse: „Stop" wirkt in JEDEM Zustand.

Der Befund aus dem Protokoll des Benutzers: „Stop" blieb wirkungslos, weil
es in zwei Löcher fiel. Während der Orb DACHTE, wurde jede Äußerung
kommentarlos verworfen („Äußerung übergangen"); und am Stimm-Tor scheiterte
der kurze Ausruf an der Sprecherprüfung („Fremde Stimme überhört,
Ähnlichkeit 0.3-0.5, Schwelle 0.55") - ein „Stop!" ist zu kurz für einen
verlässlichen Stimmabdruck.

Diese Tests sichern: Ein kurzes Stop-Wort bricht den laufenden Auftrag ab,
auch wenn die Stimme nicht erkannt wird - und normale Äußerungen behalten
ihr bisheriges Verhalten.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.voice.voice_pipeline import VoicePipeline, VoiceState


class _Transcript:
    def __init__(self, text: str):
        self.text = text
        self.confidence = 0.9
        self.is_empty = not text


class _Transcriber:
    load_failed = False

    def __init__(self, text: str):
        self._text = text

    async def transcribe(self, path):
        return _Transcript(self._text)


class _Urteil:
    def __init__(self, akzeptiert: bool):
        self.akzeptiert = akzeptiert
        self.aehnlichkeit = 0.4
        self.schwelle = 0.55
        self.geprueft = True

    def to_dict(self):
        return {}


class _Stimme:
    def __init__(self, akzeptiert: bool):
        self._akzeptiert = akzeptiert
        self.aktiv = True

    def pruefen(self, path):
        return _Urteil(self._akzeptiert)


class _Player:
    is_playing = False

    def stop(self):
        self.gestoppt = True


class _Capture:
    def mute(self, value):
        pass


class _Bus:
    async def publish(self, *a, **k):
        return None


def _pipeline(gehoert: str, *, stimme_akzeptiert: bool) -> VoicePipeline:
    p = VoicePipeline.__new__(VoicePipeline)
    p._stop_words = {"stop", "stopp", "halt"}
    p._stop_transcriber = _Transcriber(gehoert)
    p._transcriber = _Transcriber(gehoert)
    p._stimme = _Stimme(stimme_akzeptiert)
    p._stimme_lernt = None
    p._listening_for_stop = False
    p._processing = False
    p._turn_claimed = False
    p._antwort_task = None
    p._interrupted = asyncio.Event()
    p._player = _Player()
    p._capture = _Capture()
    p._event_bus = _Bus()
    return p


# --- Baustein: die Kurzprüfung ---------------------------------------------


def test_kurzer_stop_wird_erkannt():
    p = _pipeline("Stop!", stimme_akzeptiert=True)
    assert asyncio.run(p._ist_kurzer_stop(Path("/tmp/x.wav"), 1.2))


def test_lange_aeusserung_ist_kein_stop():
    # Länge zuerst: lange Sätze werden gar nicht erst geprüft.
    p = _pipeline("Stop!", stimme_akzeptiert=True)
    assert not asyncio.run(p._ist_kurzer_stop(Path("/tmp/x.wav"), 5.0))


def test_normale_worte_sind_kein_stop():
    p = _pipeline("wie spät ist es", stimme_akzeptiert=True)
    assert not asyncio.run(p._ist_kurzer_stop(Path("/tmp/x.wav"), 1.2))


def test_gehalt_ist_kein_halt():
    p = _pipeline("mein Gehalt bitte", stimme_akzeptiert=True)
    assert not asyncio.run(p._ist_kurzer_stop(Path("/tmp/x.wav"), 1.5))


# --- Die Notbremse bricht die laufende Antwort ab ---------------------------


def test_verarbeitung_abbrechen_bricht_die_antwort_aufgabe_ab():
    p = _pipeline("Stop", stimme_akzeptiert=True)

    async def _lauf():
        laeuft = asyncio.Event()

        async def _lange_antwort():
            laeuft.set()
            await asyncio.sleep(30)

        task = asyncio.create_task(_lange_antwort())
        p._antwort_task = task
        await laeuft.wait()

        p.verarbeitung_abbrechen()
        try:
            await task
        except asyncio.CancelledError:
            return True
        return task.cancelled()

    assert asyncio.run(_lauf())
    assert p._interrupted.is_set()


def test_stop_waehrend_der_verarbeitung_greift(tmp_path):
    p = _pipeline("Stopp.", stimme_akzeptiert=True)
    p._processing = True
    wav = tmp_path / "stop.wav"
    wav.write_bytes(b"x")

    async def _lauf():
        laeuft = asyncio.Event()

        async def _denkt():
            laeuft.set()
            await asyncio.sleep(30)

        task = asyncio.create_task(_denkt())
        p._antwort_task = task
        await laeuft.wait()

        await p._handle_utterance(wav, 1.0)
        await asyncio.sleep(0)
        return task.cancelled() or task.done()

    assert asyncio.run(_lauf()), "der laufende Auftrag wurde nicht abgebrochen"


def test_stop_trotz_nicht_erkannter_stimme(tmp_path):
    # Die Sprecherprüfung lehnt ab - das Stop-Wort greift trotzdem.
    p = _pipeline("Stop!", stimme_akzeptiert=False)
    wav = tmp_path / "stop.wav"
    wav.write_bytes(b"x")

    asyncio.run(p._handle_utterance(wav, 1.0))
    assert p._interrupted.is_set(), "die Notbremse hat nicht gegriffen"


def test_fremde_stimme_ohne_stop_bleibt_ueberhoert(tmp_path):
    # Kein Freibrief: Wer nicht erkannt wird und KEIN Stop-Wort sagt,
    # wird weiterhin überhört.
    p = _pipeline("erzähl mir etwas", stimme_akzeptiert=False)
    wav = tmp_path / "rede.wav"
    wav.write_bytes(b"x")

    asyncio.run(p._handle_utterance(wav, 1.5))
    assert not p._interrupted.is_set()


def test_zwei_parallel_transkribierte_saetze_starten_nicht_zwei_auftraege(tmp_path):
    """Zwei Hoerfenster duerfen die Vorpruefung nicht gemeinsam passieren.

    Die Transkription ist asynchron. Deshalb kann ein zweites Fenster die
    erste ``_processing``-Pruefung passieren, solange das erste noch erkannt
    wird. Die zweite Pruefung nach der Transkription muss es dann stoppen.
    """

    p = _pipeline("eine normale frage", stimme_akzeptiert=True)
    p._adapt_to_user_rhythm = False
    p._min_characters = 1
    p._rueckfrage_unter = 0.0
    p._min_confidence = 0.0
    p._barge_in = False
    p._history = []
    p._max_history = 10
    p._last_error = ""
    p._state = VoiceState.LISTENING

    begonnen = asyncio.Event()
    freigabe = asyncio.Event()

    class _GleichzeitigerTranscriber(_Transcriber):
        async def transcribe(self, path):
            begonnen.set()
            await freigabe.wait()
            return _Transcript("eine normale frage")

    p._transcriber = _GleichzeitigerTranscriber("")
    p._neue_rede = lambda: None
    p._is_asleep = lambda: False
    auftraege = 0

    async def _antwort(transcript, turn):
        nonlocal auftraege
        auftraege += 1
        p._processing = True

    p._handle_while_awake = _antwort
    p._remember = lambda turn: None

    eins = tmp_path / "eins.wav"
    zwei = tmp_path / "zwei.wav"
    eins.write_bytes(b"x")
    zwei.write_bytes(b"x")

    async def _lauf():
        erster = asyncio.create_task(p._handle_utterance(eins, 1.0))
        await begonnen.wait()
        zweiter = asyncio.create_task(p._handle_utterance(zwei, 1.0))
        await asyncio.sleep(0)
        freigabe.set()
        await asyncio.gather(erster, zweiter)

    asyncio.run(_lauf())
    assert auftraege == 1
