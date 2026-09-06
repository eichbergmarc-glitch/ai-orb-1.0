"""Tests des fluessigen Sprechens.

Zwei Dinge werden geprueft: dass Modell-Stuecke korrekt zu ganzen Saetzen
gesammelt werden (nicht mitten im Wort gesprochen wird), und dass eine
Abkuerzung wie "z. B." den Satz nicht vorzeitig beendet.
"""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from types import SimpleNamespace
import threading
import time

from backend.voice.voice_pipeline import VoicePipeline, VoiceState, _take_complete_sentence


def _drain(stuecke):
    """Speist Stuecke ein und sammelt die fertigen Saetze."""
    buffer = ""
    saetze = []
    for stueck in stuecke:
        buffer += stueck
        satz, buffer = _take_complete_sentence(buffer)
        while satz:
            saetze.append(satz)
            satz, buffer = _take_complete_sentence(buffer)
    if buffer.strip():
        saetze.append(buffer.strip())
    return saetze


def test_ganze_saetze_aus_stuecken():
    # So, wie ein Sprachmodell streamt: silbenweise.
    stuecke = ["Die ", "Fran", "zoesische ", "Revolution ", "begann ", "1789. ",
               "Sie ", "veraenderte ", "Europa."]
    saetze = _drain(stuecke)
    assert saetze == [
        "Die Franzoesische Revolution begann 1789.",
        "Sie veraenderte Europa.",
    ]


def test_kein_abbruch_mitten_im_wort():
    # Bevor der Punkt kommt, darf kein Satz herausfallen.
    satz, rest = _take_complete_sentence("Die Revolu")
    assert satz == ""
    assert rest == "Die Revolu"


def test_abkuerzung_beendet_den_satz_nicht_vorzeitig():
    # "z. B." hat einen Punkt, ist aber kein Satzende - danach kommt nur ein
    # Leerzeichen und ein Kleinbuchstabe. Der einfache Schutz: sehr kurze
    # Stuecke vor dem Punkt zaehlen nicht als Satz.
    satz, rest = _take_complete_sentence("Dr. Meyer kam spaeter.")
    # "Dr." darf nicht als eigener Satz herausfallen.
    assert satz == "Dr. Meyer kam spaeter." or satz.startswith("Dr. Meyer")


def test_langer_fluss_ohne_punkt_wird_weich_umgebrochen():
    # Ein Komma ist erst bei einem AUSSERGEWOEHNLICH langen Satz eine
    # Notloesung. Kurze Komma-Schnitte klangen wie unsicheres Zoegern.
    text = "und dann kamen die einen, und die anderen auch " * 10  # > 400 Zeichen
    satz, rest = _take_complete_sentence(text)
    assert satz, "Ein langer Fluss ohne Punkt sollte weich umgebrochen werden."
    assert len(satz) < len(text)
    assert satz.endswith(","), "der Umbruch soll auf das Komma fallen"


def test_fragezeichen_beendet_den_satz():
    saetze = _drain(["Warum ", "begann ", "sie? ", "Niemand ", "weiss ", "es."])
    assert saetze[0] == "Warum begann sie?"


def test_pcm_stream_startet_keine_parallele_stop_transkription():
    """Lokale Streaming-TTS darf nicht von Whisper ausgebremst werden."""

    werte: list[bool] = []
    pipeline = VoicePipeline.__new__(VoicePipeline)
    pipeline._capture = SimpleNamespace(set_stop_spotting=werte.append)
    # Der Schalter stand hier nie - das Feld gibt es nur nach dem vollen
    # Aufbau, und der Test baut absichtlich keinen. Gesetzt wird es jetzt
    # ausdruecklich, und zwar in BEIDEN Stellungen: Frueher stand die
    # Voreinstellung auf "aus", inzwischen auf "an", und der Test prueft
    # seither eine Stellung, die es so nicht mehr gibt.
    pipeline._stop_waehrend_lokaler_stimme = False

    pipeline._stop_spaeher_fuer_ausgabe(
        SimpleNamespace(context={"pcm_stream": object()})
    )
    pipeline._stop_spaeher_fuer_ausgabe(
        SimpleNamespace(context={}, engine="supertonic")
    )
    pipeline._stop_spaeher_fuer_ausgabe(SimpleNamespace(context={}))

    assert werte == [False, False, True]

    # Voreinstellung: Auch bei der lokalen Stimme wird weiter gespaeht,
    # sonst waere das Stop-Wort dort wirkungslos. Der laufende PCM-Strom
    # bleibt die einzige Ausnahme.
    weitere: list[bool] = []
    pipeline._capture = SimpleNamespace(set_stop_spotting=weitere.append)
    pipeline._stop_waehrend_lokaler_stimme = True

    pipeline._stop_spaeher_fuer_ausgabe(
        SimpleNamespace(context={"pcm_stream": object()})
    )
    pipeline._stop_spaeher_fuer_ausgabe(
        SimpleNamespace(context={}, engine="supertonic")
    )

    assert weitere == [False, True]


def test_naechster_satz_wird_synthetisiert_waehrend_der_vorgaenger_laeuft():
    """Die Cloud-Berechnung darf keine tote Luecke zwischen Saetzen bilden."""

    ereignisse: list[tuple[str, str, float]] = []

    class _Tts:
        async def speak(self, text, **kwargs):  # noqa: ANN001, ARG002
            ereignisse.append(("synth_start", text, time.perf_counter()))
            await asyncio.sleep(0.01)
            ereignisse.append(("synth_end", text, time.perf_counter()))
            return SimpleNamespace(
                succeeded=True, audio_path=Path(text + ".wav"), error=""
            )

    class _Player:
        def play_blocking(self, path):  # noqa: ANN001
            ereignisse.append(("play_start", path.stem, time.perf_counter()))
            time.sleep(0.09)
            ereignisse.append(("play_end", path.stem, time.perf_counter()))
            return True

    class _Capture:
        def mute(self, value):  # noqa: ANN001, ARG002
            return None

        def set_stop_spotting(self, value):  # noqa: ANN001, ARG002
            return None

    class _Events:
        async def publish(self, *args, **kwargs):  # noqa: ANN002, ANN003, ARG002
            return None

    async def ablauf():
        pipeline = VoicePipeline.__new__(VoicePipeline)
        pipeline._stop_waehrend_lokaler_stimme = True
        pipeline._tts = _Tts()
        pipeline._player = _Player()
        pipeline._capture = _Capture()
        pipeline._event_bus = _Events()
        pipeline._interrupted = threading.Event()
        pipeline._speech_lock = asyncio.Lock()
        pipeline._satzstrom_synth_lock = asyncio.Lock()
        pipeline._satzstrom_queue = None
        pipeline._satzstrom_worker = None
        pipeline._satzstrom_failed = False
        pipeline._letzte_saetze = deque(maxlen=5)
        pipeline._gesprochene_woerter = set()
        pipeline._state = VoiceState.THINKING
        pipeline._processing = True
        pipeline._listening_for_stop = False
        pipeline._active_turn_trace = None
        pipeline._last_error = ""
        pipeline._wartet_auf_antwort = False
        pipeline._fremd_folge = 0
        pipeline._spaeher_geprueft = 0
        pipeline._spaeher_verworfen = 0
        pipeline._spaeher_abgebrochen = 0

        pipeline._satzstrom_starten()
        await pipeline._sprich_satz("Satz eins")
        # Der Provider liefert weiter, waehrend Satz eins vorbereitet/laeuft.
        await asyncio.sleep(0.025)
        await pipeline._sprich_satz("Satz zwei")
        assert await pipeline._satzstrom_beenden()

    asyncio.run(ablauf())

    erster_play_start = next(t for art, text, t in ereignisse if art == "play_start" and text == "Satz eins")
    erster_play_end = next(t for art, text, t in ereignisse if art == "play_end" and text == "Satz eins")
    zweiter_synth_start = next(t for art, text, t in ereignisse if art == "synth_start" and text == "Satz zwei")
    zweiter_synth_end = next(t for art, text, t in ereignisse if art == "synth_end" and text == "Satz zwei")

    assert erster_play_start < zweiter_synth_start < zweiter_synth_end < erster_play_end
