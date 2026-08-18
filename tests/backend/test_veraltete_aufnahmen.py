"""Der Riegel gegen die Erkennungs-Schlange vom 17.08.2026.

Was passiert war, Minute für Minute im Protokoll: Um 13:39 bat der Benutzer
um die Nachrichten des Tages. Während der Orb die lange Antwort sprach,
hörte das Mikrofon ihn selbst mit, und jeder dieser Schnipsel stellte sich
zur vollen Spracherkennung an. Die Wartezeit wuchs: 18 s, 30 s, 72 s, 110 s,
zuletzt 194 s. Als der Benutzer um 13:48:33 klar und deutlich fragte
"Kannst du mich jetzt verstehen?" (Sicherheit 0,94), wartete sein Satz drei
Minuten in der Schlange - und wurde dann verworfen. Aus Sicht des Benutzers:
"Der Orb versteht mich nicht und antwortet nicht."

Zwei Riegel dagegen, beide hier geprüft:

* Eine Aufnahme, die zu lange auf die Erkennung gewartet hat, wird
  verworfen statt erkannt - sie ist keine Anweisung mehr, und sie zu
  erkennen verzögert nur die, die noch eine ist.
* Es erkennt immer nur eine Aufnahme zugleich. Vorher liefen mehrere
  gleichzeitig auf demselben Modell und nahmen sich gegenseitig die
  Rechenkerne weg.

Die Prüfungen kommen ohne faster-whisper aus: Der Verfall wird VOR dem
Laden des Modells geprüft - mit Absicht, denn genau dann hat die veraltete
Aufnahme noch nichts gekostet.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from backend.whisper.transcriber import Transcriber


def _transcriber() -> Transcriber:
    return Transcriber(model_size="base", language="de")


def test_eine_veraltete_aufnahme_wird_verworfen_statt_erkannt(tmp_path):
    t = _transcriber()
    ergebnis = t._transcribe_blocking(
        tmp_path / "alt.wav",
        abgegeben=time.monotonic() - 60.0,
        verfallen_nach=25.0,
    )
    assert ergebnis.is_empty, "eine Minute alte Aufnahme ist keine Anweisung mehr"


def test_eine_frische_aufnahme_verfaellt_nicht(tmp_path, monkeypatch):
    # Frisch heisst: Der Verfall greift nicht, die Erkennung laeuft an.
    # Das Modell selbst wird abgefangen - hier zaehlt nur die Weiche.
    t = _transcriber()
    gerufen = []
    monkeypatch.setattr(t, "_load_model", lambda: gerufen.append(1) or None)

    ergebnis = t._transcribe_blocking(
        tmp_path / "frisch.wav",
        abgegeben=time.monotonic(),
        verfallen_nach=25.0,
    )
    assert gerufen, "die frische Aufnahme muss zur Erkennung durchkommen"
    assert ergebnis.is_empty  # weil das Modell hier absichtlich fehlt


def test_ohne_verfallszeit_bleibt_alles_beim_alten(tmp_path, monkeypatch):
    t = _transcriber()
    gerufen = []
    monkeypatch.setattr(t, "_load_model", lambda: gerufen.append(1) or None)
    t._transcribe_blocking(tmp_path / "x.wav")
    assert gerufen, "ohne Verfallszeit wird nie verworfen"


def test_der_verfall_wird_ab_abgabe_gemessen_nicht_ab_pruefung(tmp_path):
    # transcribe() stempelt beim Aufruf. Wartet die Aufnahme danach in der
    # Schlange, zaehlt diese Wartezeit - genau sie war das Problem.
    t = _transcriber()

    async def _lauf():
        # Die Sperre besetzen, damit die Aufnahme warten muss.
        def _blockieren():
            with t._reihen_sperre:
                time.sleep(0.8)

        blockierer = asyncio.create_task(asyncio.to_thread(_blockieren))
        await asyncio.sleep(0.1)
        ergebnis = await t.transcribe(tmp_path / "y.wav", verfallen_nach=0.5)
        await blockierer
        return ergebnis

    ergebnis = asyncio.run(_lauf())
    assert ergebnis.is_empty, (
        "die Wartezeit in der Schlange muss zum Alter der Aufnahme zaehlen"
    )


def test_es_erkennt_nur_eine_aufnahme_zugleich(tmp_path, monkeypatch):
    # Vorher liefen mehrere Erkennungen gleichzeitig auf demselben Modell
    # und machten einander langsam. Jetzt stehen sie an.
    t = _transcriber()
    gleichzeitig = []
    hoechststand = []

    def _langsames_modell():
        gleichzeitig.append(1)
        hoechststand.append(len(gleichzeitig))
        time.sleep(0.15)
        gleichzeitig.pop()
        return None

    monkeypatch.setattr(t, "_load_model", _langsames_modell)

    async def _lauf():
        await asyncio.gather(*(t.transcribe(tmp_path / f"{i}.wav") for i in range(4)))

    asyncio.run(_lauf())
    assert max(hoechststand) == 1, f"es liefen {max(hoechststand)} Erkennungen zugleich"


def test_waehrend_der_ausgabe_prueft_das_kleine_modell_mit_kurzem_verfall():
    # Am 17.08. lief hier das grosse Modell und baute die Schlange auf.
    # Der Quelltext muss das kleine benutzen und ein kurzes Verfallsfenster
    # setzen - ein Stop-Wort von vor zehn Sekunden ist keines mehr.
    from pathlib import Path as _P

    quelle = _P("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("if self._listening_for_stop:")
    ausschnitt = quelle[anfang:anfang + 600]
    assert "_stop_transcriber" in ausschnitt
    assert "verfallen_nach" in ausschnitt


# ---------------------------------------------------------------------------
#  Stufe 1: Das Ohr entlasten (17.08.2026, Bestandsaufnahme S1)
# ---------------------------------------------------------------------------
#
# Die Zahlen: Am 14.08. wurden 600 von 646 Aeusserungen voll transkribiert
# und danach weggeworfen - Zimmergeraeusche, Fernseher, die eigene
# Lautsprecherstimme. Im Schlaf braucht der Orb aber nur eine Auskunft:
# Fiel das Weckwort? Dafuer sichtet jetzt das kleine Modell vor, und das
# grosse arbeitet nur noch, wenn sich die Sorgfalt lohnt.


def _schlafende_pipeline(monkeypatch, klein_text: str):
    """Baut eine schlafende Pipeline mit gezaehlten Erkennern."""

    import asyncio as _a

    from backend.voice.voice_pipeline import VoicePipeline, VoiceState

    p = VoicePipeline.__new__(VoicePipeline)
    rufe = {"klein": 0, "gross": 0}

    class _Erkenner:
        def __init__(self, name, text):
            self._name, self._text = name, text
            self.load_failed = False

        async def transcribe(self, path, *, verfallen_nach=None):
            rufe[self._name] += 1
            from backend.whisper.transcriber import Transcript
            return Transcript(text=self._text, confidence=0.9)

    class _Weckwort:
        def detect(self, text):
            class _T:
                detected = "orb" in (text or "").lower()
                score = 1.0 if detected else 0.0
                phrase = "Hallo Orb"
                command = ""
                has_command = False
            return _T()

    p._stop_transcriber = _Erkenner("klein", klein_text)
    p._transcriber = _Erkenner("gross", klein_text)
    p._wake_word = _Weckwort()
    p._listening_for_stop = False
    p._processing = False
    p._turn_claimed = False
    p._stimme_lernt = None

    class _Stimme:
        def pruefen(self, path):
            class _U:
                akzeptiert = True
                geprueft = False
                aehnlichkeit = 0.9
                schwelle = 0.55
                def to_dict(self): return {}
            return _U()
        def rhythmus_aktualisieren(self, path): return False

    p._stimme = _Stimme()
    p._adapt_to_user_rhythm = False
    p._is_asleep = lambda: True
    p._neue_rede = lambda: None

    class _Bus:
        async def publish(self, *a, **k): return None

    p._event_bus = _Bus()
    # Nebensaechliches ausklammern - geprueft wird die Erkennungsweiche,
    # nicht der Verlaufsspeicher.
    p._remember = lambda turn: None
    p._active_turn_trace = None
    return p, rufe


def test_im_schlaf_sichtet_das_kleine_modell_vor(tmp_path, monkeypatch):
    import asyncio

    p, rufe = _schlafende_pipeline(monkeypatch, "irgendein Fernsehsatz ohne Bedeutung")
    wav = tmp_path / "geraeusch.wav"
    wav.write_bytes(b"x")

    asyncio.run(p._handle_utterance(wav, 2.0))

    assert rufe["klein"] == 1, "das kleine Modell muss sichten"
    assert rufe["gross"] == 0, (
        "ohne Weckverdacht darf das grosse Modell nicht rechnen - genau "
        "diese Rechnerei hat die Schlange der letzten Tage gebaut"
    )


def test_ein_weckverdacht_geht_zur_grossen_erkennung(tmp_path, monkeypatch):
    import asyncio

    p, rufe = _schlafende_pipeline(monkeypatch, "hallo orb wie spaet ist es")
    # Ab hier laeuft der normale Weg weiter - der bricht in diesem
    # Rumpfaufbau spaeter kontrolliert ab; gezaehlt wird nur die Erkennung.
    wav = tmp_path / "weckruf.wav"
    wav.write_bytes(b"x")
    try:
        asyncio.run(p._handle_utterance(wav, 2.0))
    except Exception:  # noqa: BLE001 - der Rumpf hat keinen ganzen Orb.
        pass
    assert rufe["gross"] == 1, "beim Weckverdacht muss das grosse Modell lesen"


def test_zu_kurze_schnipsel_kosten_im_schlaf_gar_nichts(tmp_path, monkeypatch):
    import asyncio

    p, rufe = _schlafende_pipeline(monkeypatch, "knack")
    wav = tmp_path / "knacken.wav"
    wav.write_bytes(b"x")
    asyncio.run(p._handle_utterance(wav, 0.4))
    assert rufe == {"klein": 0, "gross": 0}, (
        "ein Weckruf dauert laenger als eine Dreiviertelsekunde - Kuerzeres "
        "ist keine Erkennung wert"
    )
