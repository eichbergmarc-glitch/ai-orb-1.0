"""Regressionstests der Stufe 2: das Hoeren.

Drei schwere Befunde und ein vierter, der beim Nachsehen auffiel und alle
anderen ueberholt: ``_pending_stop_window`` wurde im ganzen Quelltext
gelesen, aber nirgends angelegt. Jedes Hoerfenster endete deshalb mit einem
AttributeError - waehrend einer laengeren Antwort dutzendfach. Gesehen hat
das niemand, weil der Test der Stoppfenster das Feld auf seinem eigenen
Testdoppel selbst setzt. Genau dagegen steht der erste Test hier.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from backend.audio.audio_capture import BLOCK_SIZE, AudioCapture
from backend.tts.piper_engine import PiperEngine
from backend.voice.voice_pipeline import VoicePipeline


# --- 1. Das Feld, das es nicht gab ------------------------------------------


def test_das_gemerkte_hoerfenster_wird_im_aufbau_angelegt() -> None:
    """Ein Blick in den Aufbau - mehr braucht es nicht.

    Der volle Aufbau der Sprachschicht verlangt Mikrofon und Modelle und
    laesst sich im Test nicht herstellen. Genau deshalb ist dieser Fehler
    so lange unbemerkt geblieben: Jedes Testdoppel legt das Feld selbst an.
    Hier wird nachgesehen, ob es der ECHTE Aufbau tut.
    """

    quelle = inspect.getsource(VoicePipeline.__init__)

    assert "self._pending_stop_window" in quelle, (
        "_pending_stop_window wird in _check_stop_window gelesen, aber im "
        "Aufbau nicht angelegt - jedes Hoerfenster endet mit einem "
        "AttributeError"
    )
    assert "self._stop_fenster_verfall" in quelle
    assert "self._stop_grossmodell_gemeldet" in quelle


# --- 2. Der Spaeher schreibt nur, wenn jemand hinsieht ----------------------


class _StummerSpaeher(VoicePipeline):
    """Nur die Rueckfrage des Spaehers, ohne Mikrofon und Modelle."""

    def __init__(self, *, load_failed: bool = False) -> None:
        # Bewusst kein super().__init__ - der volle Aufbau braucht Geraete.
        self._listening_for_stop = True
        self._stop_transcriber = type("_E", (), {"load_failed": load_failed})()
        self._stop_check_busy = False
        self._pending_stop_window: Path | None = None


def test_ohne_gemerktes_fenster_wird_weiter_gespaeht() -> None:
    späher = _StummerSpaeher()
    späher._stop_check_busy = True

    assert späher._stop_window_aufnahmebereit() is True


def test_mit_gemerktem_fenster_wird_nichts_mehr_geschrieben() -> None:
    """Ein drittes Fenster waere veraltet, bevor es an die Reihe kaeme."""

    späher = _StummerSpaeher()
    späher._stop_check_busy = True
    späher._pending_stop_window = Path("egal.wav")

    assert späher._stop_window_aufnahmebereit() is False


def test_ohne_kleines_modell_wird_gar_nicht_erst_aufgenommen() -> None:
    assert _StummerSpaeher(load_failed=True)._stop_window_aufnahmebereit() is False


def test_ausserhalb_des_sprechens_wird_nicht_gespaeht() -> None:
    späher = _StummerSpaeher()
    späher._listening_for_stop = False

    assert späher._stop_window_aufnahmebereit() is False


# --- 3. Die Aufnahme fragt, bevor sie schreibt ------------------------------


def _kamera(tmp: Path, bereit: Any, geschrieben: list[Path]) -> AudioCapture:
    return AudioCapture(
        on_utterance=lambda pfad, dauer: None,
        on_stop_window=geschrieben.append,
        stop_window_ready=bereit,
        stop_window_ms=300.0,
        output_directory=tmp,
    )


def _block(wert: int) -> bytes:
    return (wert % 30000).to_bytes(2, "little", signed=False) * BLOCK_SIZE


def test_ein_nein_der_erkennung_spart_die_datei(tmp_path: Path) -> None:
    """Der Kern der Ersparnis: keine Rueckfrage, keine Datei."""

    geschrieben: list[Path] = []
    kamera = _kamera(tmp_path, lambda: False, geschrieben)
    kamera.set_stop_spotting(True)

    for i in range(200):
        kamera._handle_block(_block(i))

    assert geschrieben == []
    assert list(tmp_path.iterdir()) == [], "es wurden Dateien geschrieben"


def test_ohne_rueckfrage_bleibt_alles_wie_bisher(tmp_path: Path) -> None:
    """Wer nicht fragt, bekommt weiter jedes Fenster - im Zweifel schreiben."""

    geschrieben: list[Path] = []
    kamera = _kamera(tmp_path, None, geschrieben)
    kamera.set_stop_spotting(True)

    for i in range(200):
        kamera._handle_block(_block(i))

    assert len(geschrieben) >= 3


def test_eine_kaputte_rueckfrage_haelt_die_aufnahme_nicht_an(tmp_path: Path) -> None:
    """Die Aufnahme darf an nichts scheitern, was ausserhalb passiert."""

    def _wirft() -> bool:
        raise RuntimeError("kaputt")

    geschrieben: list[Path] = []
    kamera = _kamera(tmp_path, _wirft, geschrieben)
    kamera.set_stop_spotting(True)

    for i in range(200):
        kamera._handle_block(_block(i))

    assert len(geschrieben) >= 3, "im Zweifel wird geschrieben"


# --- 4. Piper laesst den Orb nicht mehr minutenlang schweigen ---------------


def test_ohne_netz_wird_kein_download_versucht(tmp_path: Path, monkeypatch) -> None:
    """Vier Minuten Stille beim ersten Sprechversuch - das war der Befund.

    Zwei Downloads, jeder mit 120 Sekunden Zeitlimit, ausgefuehrt im
    Sprech-Thread. Jetzt wird vorher kurz an die Tuer geklopft.
    """

    engine = PiperEngine(output_directory=tmp_path, options={"voice": "de_DE-thorsten-medium"})
    # models_directory ist eine Eigenschaft der Klasse, kein Feld.
    monkeypatch.setattr(PiperEngine, "models_directory", property(lambda _self: tmp_path))
    monkeypatch.setattr(engine, "_netz_erreichbar", lambda: False)

    def _nie(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("ohne Netz darf kein Download beginnen")

    monkeypatch.setattr("urllib.request.urlopen", _nie)

    assert engine._download("de_DE-thorsten-medium") is None


def test_die_klinkenprobe_haengt_nicht(tmp_path: Path, monkeypatch) -> None:
    """Die Probe selbst muss kurz sein, sonst verschiebt sie nur das Problem."""

    gemerkt: dict[str, Any] = {}

    def _verbindung(adresse: tuple[str, int], timeout: float | None = None) -> Any:
        gemerkt["adresse"] = adresse
        gemerkt["timeout"] = timeout
        raise OSError("kein Netz")

    monkeypatch.setattr("socket.create_connection", _verbindung)
    engine = PiperEngine(output_directory=tmp_path)

    assert engine._netz_erreichbar() is False
    assert gemerkt["adresse"] == ("huggingface.co", 443)
    assert gemerkt["timeout"] <= 5.0, "die Probe darf nicht selbst zur Wartezeit werden"
