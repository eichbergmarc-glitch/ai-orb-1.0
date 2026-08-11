"""Tests des Stop-Spaehers - also der Hoerfenster, waehrend der Orb redet.

Das Stop-Wort wurde lange nicht erkannt, und der Grund lag nicht in der
Worterkennung (die wird in test_stop_word.py geprueft), sondern davor: Die
Hoerfenster lagen lueckenlos aneinander statt sich zu ueberlappen. Ein
kurzes "stop" fiel dann leicht genau auf die Naht - erste Haelfte im einen
Fenster, zweite im naechsten, in keinem davon als Wort erkennbar.

Geprueft wird deshalb die Eigenschaft, auf die es ankommt: Ein gesprochenes
Wort ist, egal wann es faellt, in mindestens einem Fenster VOLLSTAENDIG
enthalten. Und: Zwei Fenster duerfen sich nie dieselbe Datei teilen.
"""

from __future__ import annotations

import asyncio
import threading
import wave
from pathlib import Path

from backend.audio.audio_capture import BLOCK_DURATION_MS, BLOCK_SIZE, AudioCapture
from backend.voice.voice_pipeline import VoicePipeline


def _kamera(tmp: Path, **kw) -> AudioCapture:
    """Eine Aufnahme, die nie ein Mikrofon anfasst."""

    return AudioCapture(
        on_utterance=lambda pfad, dauer: None,
        on_stop_window=kw.pop("on_stop_window", lambda pfad: None),
        output_directory=tmp,
        **kw,
    )


def _block(kennung: int) -> bytes:
    """Ein Block, dem man ansieht, der wievielte er ist."""

    # 16-Bit-Samples, alle mit demselben Wert - so laesst sich spaeter
    # ablesen, welche Bloecke in einem Fenster gelandet sind.
    wert = (kennung % 30000).to_bytes(2, "little", signed=False)
    return wert * BLOCK_SIZE


def _kennung(rohdaten: bytes, versatz: int) -> int:
    return int.from_bytes(rohdaten[versatz * 2 : versatz * 2 + 2], "little")


def test_fenster_ueberlappen_sich(tmp_path: Path):
    """Jedes Fenster beginnt, bevor das vorige endet."""

    fenster: list[list[int]] = []
    kamera = _kamera(tmp_path, stop_window_ms=1200.0)
    kamera._emit_stop_window = lambda bloecke: fenster.append(  # type: ignore[method-assign]
        [_kennung(b, 0) for b in bloecke]
    )
    kamera.set_stop_spotting(True)

    for i in range(200):
        kamera._handle_block(_block(i))

    assert len(fenster) >= 3, "es kamen kaum Fenster an"
    for vorheriges, naechstes in zip(fenster, fenster[1:]):
        assert naechstes[0] <= vorheriges[-1], (
            "Fenster liegen lueckenlos aneinander statt sich zu ueberlappen: "
            f"{vorheriges[0]}-{vorheriges[-1]} dann {naechstes[0]}-{naechstes[-1]}"
        )


def test_jedes_wort_liegt_ganz_in_einem_fenster(tmp_path: Path):
    """Die Eigenschaft, um die es eigentlich geht.

    Ein "stop" dauert ungefaehr eine halbe Sekunde. Egal, wann es faellt -
    es muss in mindestens einem Fenster komplett enthalten sein, sonst kann
    die Erkennung es nicht als Wort lesen.
    """

    fenster: list[list[int]] = []
    kamera = _kamera(tmp_path, stop_window_ms=1200.0)
    kamera._emit_stop_window = lambda bloecke: fenster.append(  # type: ignore[method-assign]
        [_kennung(b, 0) for b in bloecke]
    )
    kamera.set_stop_spotting(True)

    for i in range(400):
        kamera._handle_block(_block(i))

    wortlaenge = max(1, int(500.0 / BLOCK_DURATION_MS))  # ~500 ms
    spannen = [(f[0], f[-1]) for f in fenster]

    # Erst ab dem Ende des ersten vollstaendigen Fensters kann ueberhaupt
    # ein Fenster vorliegen - vorher hat der Orb noch nichts gehoert.
    erster_start = spannen[0][0]
    for beginn in range(erster_start, 400 - wortlaenge):
        ende = beginn + wortlaenge - 1
        assert any(
            anfang <= beginn and ende <= schluss for anfang, schluss in spannen
        ), f"Ein Wort von Block {beginn} bis {ende} faellt durch alle Fenster"


def test_fenster_ueberschreiben_sich_nicht(tmp_path: Path):
    """Zwei dicht aufeinander folgende Fenster brauchen zwei Dateien.

    Die Fenster ueberlappen sich und folgen schnell aufeinander. Als der
    Dateiname nur aus der Millisekunde bestand, trafen sich zwei Fenster in
    derselben Millisekunde - das zweite ueberschrieb das erste, und die
    Erkennung lief auf eine Datei, die es so nicht mehr gab.
    """

    gesehen: list[Path] = []

    def merken(pfad: Path) -> None:
        assert pfad.exists(), f"{pfad.name} war beim Melden schon weg"
        gesehen.append(pfad)

    kamera = _kamera(tmp_path, stop_window_ms=1200.0, on_stop_window=merken)
    kamera.set_stop_spotting(True)

    for i in range(300):
        kamera._handle_block(_block(i))

    assert len(gesehen) >= 3
    assert len(set(gesehen)) == len(gesehen), "zwei Fenster teilten sich eine Datei"
    for pfad in gesehen:
        assert pfad.exists(), f"{pfad.name} wurde nachtraeglich ueberschrieben"
        with wave.open(str(pfad), "rb") as handle:
            assert handle.getnchannels() == 1
            assert handle.getsampwidth() == 2
            assert handle.getnframes() > 0


def test_spaehen_aus_raeumt_auf(tmp_path: Path):
    """Nach dem Sprechen ist der Puffer leer - sonst reden alte Bloecke mit."""

    kamera = _kamera(tmp_path)
    kamera.set_stop_spotting(True)
    for i in range(20):
        kamera._handle_block(_block(i))

    kamera.set_stop_spotting(False)
    assert kamera._spot_buffer == []
    assert kamera._spot_since_last == 0


# --- Die Warteschlange der Erkennung ----------------------------------------


class _Erkennung:
    """Eine langsame Spracherkennung, die den Dateiinhalt zurueckgibt."""

    def __init__(self, verzoegerung: float = 0.0, load_failed: bool = False):
        self.verzoegerung = verzoegerung
        self.gelesen: list[str] = []
        self.load_failed = load_failed

    async def transcribe(self, pfad: Path):
        # Genau das war der Fehler: Die Datei war schon geloescht, als die
        # Erkennung sie oeffnen wollte.
        text = pfad.read_text(encoding="utf-8")
        if self.verzoegerung:
            await asyncio.sleep(self.verzoegerung)
        self.gelesen.append(text)

        class _Ergebnis:
            pass

        ergebnis = _Ergebnis()
        ergebnis.text = text
        return ergebnis


class _KeineStimme:
    """Eine Stimmerkennung ohne hinterlegte Stimme."""

    aktiv = False

    def pruefen(self, pfad):  # pragma: no cover - wird nie gefragt
        raise AssertionError("ohne hinterlegte Stimme darf nicht geprueft werden")


class _MeineStimme:
    """Eine Stimmerkennung, die jede Aufnahme als die eigene erkennt."""

    aktiv = True

    def __init__(self, akzeptiert: bool = True):
        self.akzeptiert = akzeptiert
        self.gefragt = 0

    def pruefen(self, pfad):
        from backend.voice.speaker_id import Urteil

        self.gefragt += 1
        return Urteil(self.akzeptiert, 0.9 if self.akzeptiert else 0.1, 0.6, "", True)


class _Späher(VoicePipeline):
    """Nur der Stop-Spaeher, ohne Mikrofon, Modelle oder Kern."""

    def __init__(self, erkennung: _Erkennung, gross: _Erkennung | None = None):
        # Bewusst kein super().__init__ - der volle Aufbau braucht Geraete.
        self._stop_transcriber = erkennung
        self._transcriber = gross if gross is not None else erkennung
        self._stop_words = {"stop", "stopp", "halt"}
        self._listening_for_stop = True
        self._interrupted = threading.Event()
        self._stop_check_busy = False
        self._pending_stop_window = None
        self.unterbrochen = 0
        # Ohne hinterlegte Stimme bleibt es beim Stop-Wort.
        self._interrupt_on_speech = False
        self._stimme = _KeineStimme()

    def interrupt(self) -> None:
        self.unterbrochen += 1
        self._interrupted.set()


def _fenster(tmp: Path, name: str, inhalt: str) -> Path:
    pfad = tmp / name
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


def test_gestautes_fenster_wird_nicht_zu_frueh_geloescht(tmp_path: Path):
    """Das gemerkte Fenster muss die laufende Erkennung ueberleben.

    Vorher loeschte der finally-Block jedes Fenster sofort - auch das eben
    erst gemerkte. Die anschliessende Erkennung lief dann auf eine Datei,
    die es nicht mehr gab.
    """

    erkennung = _Erkennung(verzoegerung=0.02)
    späher = _Späher(erkennung)

    erstes = _fenster(tmp_path, "eins.txt", "und weiter im Text")
    zweites = _fenster(tmp_path, "zwei.txt", "stop")

    async def ablauf():
        laufend = asyncio.ensure_future(späher._check_stop_window(erstes))
        await asyncio.sleep(0.005)  # die Erkennung laeuft noch
        await späher._check_stop_window(zweites)  # wird gemerkt
        assert zweites.exists(), "das gemerkte Fenster wurde sofort geloescht"
        await laufend

    asyncio.run(ablauf())

    assert erkennung.gelesen == ["und weiter im Text", "stop"]
    assert späher.unterbrochen == 1, "das gestaute 'stop' wurde nicht gehoert"


def test_nur_das_neueste_fenster_wartet(tmp_path: Path):
    """Ein Stau alter Fenster wuerde die Erkennung zurueckfallen lassen."""

    erkennung = _Erkennung(verzoegerung=0.03)
    späher = _Späher(erkennung)

    laufendes = _fenster(tmp_path, "a.txt", "erstes")
    altes = _fenster(tmp_path, "b.txt", "veraltet")
    neues = _fenster(tmp_path, "c.txt", "neuestes")

    async def ablauf():
        laufend = asyncio.ensure_future(späher._check_stop_window(laufendes))
        await asyncio.sleep(0.005)
        await späher._check_stop_window(altes)
        await späher._check_stop_window(neues)
        assert not altes.exists(), "das ueberholte Fenster blieb als Datei liegen"
        await laufend

    asyncio.run(ablauf())

    assert erkennung.gelesen == ["erstes", "neuestes"]


def test_keine_dateien_bleiben_liegen(tmp_path: Path):
    """Nach dem Sprechen darf kein Hoerfenster mehr auf der Platte liegen."""

    erkennung = _Erkennung(verzoegerung=0.02)
    späher = _Späher(erkennung)

    a = _fenster(tmp_path, "a.txt", "harmlos")
    b = _fenster(tmp_path, "b.txt", "stop")
    c = _fenster(tmp_path, "c.txt", "kommt zu spaet")

    async def ablauf():
        laufend = asyncio.ensure_future(späher._check_stop_window(a))
        await asyncio.sleep(0.005)
        await späher._check_stop_window(b)
        await laufend
        # Nach dem Unterbrechen treffen noch Fenster ein - sie duerfen
        # weder etwas ausloesen noch liegen bleiben.
        await späher._check_stop_window(c)

    asyncio.run(ablauf())

    assert späher.unterbrochen == 1
    assert list(tmp_path.iterdir()) == [], "es blieben Hoerfenster liegen"


def test_ohne_kleines_modell_uebernimmt_das_grosse(tmp_path: Path):
    """Faellt das kleine Modell aus, darf das Stop-Wort nicht ausfallen.

    Lieber spaet hinhoeren als gar nicht: Dann uebernimmt die grosse
    Erkennung, auch wenn sie langsamer ist.
    """

    klein = _Erkennung(load_failed=True)
    gross = _Erkennung()
    späher = _Späher(klein, gross=gross)

    asyncio.run(späher._check_stop_window(_fenster(tmp_path, "a.txt", "stop")))

    assert klein.gelesen == [], "das ausgefallene Modell wurde trotzdem gefragt"
    assert gross.gelesen == ["stop"]
    assert späher.unterbrochen == 1


def test_dazwischenreden_beendet_die_ausgabe(tmp_path: Path):
    """Sprichst du, waehrend der Orb spricht, hoert er auf.

    Ganz gleich, was du sagst - dafuer wird gar nicht erst transkribiert.
    Moeglich wird das erst durch die Stimmerkennung: Ohne zu wissen, WESSEN
    Stimme im Hoerfenster liegt, haette jede Silbe seiner eigenen Antwort
    ihn unterbrochen.
    """

    erkennung = _Erkennung()
    späher = _Späher(erkennung)
    späher._interrupt_on_speech = True
    späher._stimme = _MeineStimme(akzeptiert=True)

    asyncio.run(späher._check_stop_window(_fenster(tmp_path, "a.txt", "irgendwas")))

    assert späher.unterbrochen == 1
    assert erkennung.gelesen == [], "es wurde unnoetig transkribiert"


def test_die_eigene_stimme_des_orb_unterbricht_nicht(tmp_path: Path):
    """Das Mikrofon hoert waehrend des Sprechens vor allem den Orb selbst."""

    erkennung = _Erkennung()
    späher = _Späher(erkennung)
    späher._interrupt_on_speech = True
    späher._stimme = _MeineStimme(akzeptiert=False)

    asyncio.run(späher._check_stop_window(_fenster(tmp_path, "a.txt", "harmlos")))

    assert späher.unterbrochen == 0
    assert erkennung.gelesen == ["harmlos"], "das Stop-Wort muss trotzdem greifen"


def test_ohne_hinterlegte_stimme_bleibt_es_beim_stop_wort(tmp_path: Path):
    erkennung = _Erkennung()
    späher = _Späher(erkennung)
    späher._interrupt_on_speech = True
    späher._stimme = _KeineStimme()

    asyncio.run(späher._check_stop_window(_fenster(tmp_path, "a.txt", "stop")))

    assert späher.unterbrochen == 1
    assert erkennung.gelesen == ["stop"]
