"""Ein haengendes Sprachverfahren darf den Orb nicht stumm machen.

Der groesste Einzelbefund des Betriebsprotokolls vom 06.09.2026: Von 694
erzeugten Antworten wurden **281 nie gesprochen** - und nur vier davon kamen
ueberhaupt bis zum fertigen Ton. Der Abbruch lag also vor der Synthese.

Die Ursache: ``await asyncio.to_thread(engine.synthesize_blocking, ...)``
hatte keine Frist. Ein Verfahren, das FEHLSCHLAEGT, meldet sich und das
naechste uebernimmt. Ein Verfahren, das HAENGT, tat beides nicht - keine
Zeile im Protokoll, kein Stimmwechsel, kein Ton. Der Orb hielt sich
weiter fuer sprechend: am 06.09. ueber eine Minute lang, nachzuzaehlen an
202 Hoerfenstern des Stop-Spaehers.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from backend.tts.base_engine import SpeechRequest, SpeechResult
from backend.tts.tts_manager import TtsManager


class _Verfahren:
    """Ein Sprachverfahren-Doppel."""

    def __init__(self, name: str, *, haengt: float = 0.0, faellt_aus: bool = False) -> None:
        self.name = name
        self._haengt = haengt
        self._faellt_aus = faellt_aus
        self.aufrufe = 0
        self._ziel = Path(tempfile.gettempdir()) / f"orb-test-{name}.wav"

    def is_available(self) -> bool:
        return True

    def target_path(self, request: SpeechRequest) -> Path:
        return self._ziel

    def wav_duration(self, pfad: Path) -> float:
        return 1.0

    def synthesize_blocking(self, request: SpeechRequest, target: Path) -> SpeechResult:
        self.aufrufe += 1
        if self._haengt:
            time.sleep(self._haengt)
        if self._faellt_aus:
            return SpeechResult(error=f"{self.name}: geht gerade nicht")
        # ``succeeded`` verlangt eine wirklich vorhandene Datei.
        target.write_bytes(b"RIFF....WAVEfmt ")
        return SpeechResult(audio_path=target, engine=self.name, duration_seconds=1.0)


def _manager(*verfahren: _Verfahren, frist: float = 0.3) -> TtsManager:
    m = TtsManager.__new__(TtsManager)
    m._enabled = True
    m._cache_enabled = False
    m._offline_mode = False
    m._network_failed_until = 0.0
    m._engine_failed_until = {}
    m._engine_failure_reasons = {}
    m._failure_cooldown_seconds = 90.0
    m._allow_voice_fallback = True
    m._active = None
    m._synthese_frist = frist
    m._synthese_frist_je_100 = 0.0
    m._synthese_frist_hoechstens = 180.0
    m._eligible_engines = lambda: list(verfahren)  # type: ignore[method-assign]
    return m


def _auftrag(text: str = "Ein Satz.") -> SpeechRequest:
    return SpeechRequest(text=text)


# --- Die Frist -------------------------------------------------------------


async def test_ein_haengendes_verfahren_gibt_den_weg_frei():
    haenger = _Verfahren("haenger", haengt=1.5)
    ersatz = _Verfahren("ersatz")
    manager = _manager(haenger, ersatz, frist=0.3)

    begonnen = time.monotonic()
    ergebnis = await manager._synthesize_with_fallback(_auftrag())
    gedauert = time.monotonic() - begonnen

    assert ergebnis.succeeded, "der Ersatz haette sprechen muessen"
    assert ergebnis.engine == "ersatz"
    assert gedauert < 3.0, (
        f"es hat {gedauert:.1f} s gedauert - die Frist greift nicht, "
        "und genau daran hing der Orb"
    )
    assert ersatz.aufrufe == 1, "der naechste kam gar nicht erst dran"


async def test_der_haenger_wird_vermerkt_und_pausiert():
    haenger = _Verfahren("haenger", haengt=1.5)
    ersatz = _Verfahren("ersatz")
    manager = _manager(haenger, ersatz, frist=0.3)

    await manager._synthesize_with_fallback(_auftrag())

    assert manager._engine_failed_until["haenger"] > time.monotonic(), (
        "ein Verfahren, das haengt, muss genauso pausiert werden wie eines, "
        "das einen Fehler meldet - sonst haengt der naechste Satz wieder"
    )
    assert "nicht geliefert" in manager._engine_failure_reasons["haenger"]


async def test_wenn_alle_haengen_kommt_wenigstens_ein_grund():
    """Stille ohne Begruendung war der Zustand, den es zu beenden galt."""

    manager = _manager(
        _Verfahren("erster", haengt=1.5),
        _Verfahren("zweiter", haengt=1.5),
        frist=0.3,
    )

    ergebnis = await manager._synthesize_with_fallback(_auftrag())

    assert not ergebnis.succeeded
    assert "Kein Verfahren konnte sprechen" in ergebnis.error
    assert "erster" in ergebnis.error and "zweiter" in ergebnis.error


async def test_ein_schnelles_verfahren_wird_nicht_gestoert():
    schnell = _Verfahren("schnell")
    manager = _manager(schnell, frist=0.3)

    ergebnis = await manager._synthesize_with_fallback(_auftrag())

    assert ergebnis.succeeded
    assert ergebnis.engine == "schnell"
    assert manager._engine_failed_until == {}


async def test_der_gemeldete_fehlschlag_verhaelt_sich_wie_bisher():
    """Die Frist ersetzt den alten Weg nicht, sie ergaenzt ihn."""

    manager = _manager(_Verfahren("meldet", faellt_aus=True), _Verfahren("ersatz"))

    ergebnis = await manager._synthesize_with_fallback(_auftrag())

    assert ergebnis.engine == "ersatz"
    assert "geht gerade nicht" in manager._engine_failure_reasons["meldet"]


# --- Wie lang die Frist ist ------------------------------------------------


def test_ein_langer_satz_bekommt_mehr_zeit():
    manager = _manager(_Verfahren("egal"))
    manager._synthese_frist = 40.0
    manager._synthese_frist_je_100 = 8.0
    manager._synthese_frist_hoechstens = 180.0

    kurz = manager._frist_fuer(_auftrag("Ja."))
    lang = manager._frist_fuer(_auftrag("x" * 500))

    assert kurz == 40.0 + 3 / 100 * 8.0
    assert lang == 40.0 + 5 * 8.0
    assert lang > kurz


def test_die_frist_ist_nach_oben_gedeckelt():
    manager = _manager(_Verfahren("egal"))
    manager._synthese_frist = 40.0
    manager._synthese_frist_je_100 = 8.0
    manager._synthese_frist_hoechstens = 180.0

    assert manager._frist_fuer(_auftrag("x" * 100000)) == 180.0
