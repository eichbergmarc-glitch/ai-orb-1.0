"""Ein leeres Hoerfenster darf keine vierzehn Sekunden kosten.

Protokoll vom 06.09.2026, dieselbe Art Fenster, dasselbe Modell, jeweils
0,6 Sekunden Aufnahme:

    15:09:32   1,4 s gerechnet
    15:09:33   1,2 s gerechnet
    15:09:48  14,4 s gerechnet

In diesen fuenfzehn Sekunden steht im Protokoll keine einzige andere Zeile:
kein Anbieter, keine Sprachausgabe, kein Werkzeug. Es war also keine
Konkurrenz um die CPU, sondern der Erkenner selbst - Whisper fuellt jede
Aufnahme intern auf dreissig Sekunden auf und arbeitet bei Stille die
sechsstufige Temperatur-Treppe ab, bevor es aufgibt.

Das Ergebnis dieser Fenster war leer: "3 Hoerfenster, davon 0 mit Text".
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from backend.voice.voice_pipeline import VoicePipeline
from backend.whisper.transcriber import Transcriber


class _Modell:
    """Ein Whisper-Doppel, das nur mitschreibt, wie es gerufen wurde."""

    def __init__(self) -> None:
        self.aufrufe: list[dict[str, Any]] = []

    def transcribe(self, pfad: str, **kwargs: Any):
        self.aufrufe.append(kwargs)
        return [], object()


def _erkennen(tmp_path: Path, **einstellungen) -> dict[str, Any]:
    aufnahme = tmp_path / "fenster.wav"
    aufnahme.write_bytes(b"RIFF....WAVE")

    erkenner = Transcriber(model_size="base", **einstellungen)
    modell = _Modell()
    erkenner._load_model = lambda: modell  # type: ignore[method-assign]
    erkenner._transcribe_geordnet(aufnahme)

    assert modell.aufrufe, "das Modell wurde gar nicht gefragt"
    return modell.aufrufe[0]


# --- Die beiden Schalter ---------------------------------------------------


def test_ohne_treppe_gibt_es_genau_einen_durchgang(tmp_path: Path) -> None:
    aufruf = _erkennen(tmp_path, temperatur_treppe=False)

    assert aufruf["temperature"] == 0.0


def test_mit_treppe_bleibt_die_rettung_erhalten(tmp_path: Path) -> None:
    """Bei echter Sprache ist der zweite Anlauf eine gute Rettung."""

    aufruf = _erkennen(tmp_path, temperatur_treppe=True)

    assert aufruf["temperature"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_der_sprachfilter_laesst_sich_einschalten(tmp_path: Path) -> None:
    assert _erkennen(tmp_path, vad_filter=True)["vad_filter"] is True


def test_der_hauptweg_bleibt_wie_er_war(tmp_path: Path) -> None:
    """Vorgabe unveraendert: kein Filter, volle Treppe."""

    aufruf = _erkennen(tmp_path)

    assert aufruf["vad_filter"] is False
    assert aufruf["temperature"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]


# --- Und dass der Stop-Erkenner sie wirklich benutzt ------------------------


def test_der_stop_erkenner_wird_sparsam_gebaut() -> None:
    """Der volle Aufbau der Sprachschicht verlangt Mikrofon und Modelle.

    Deshalb hier derselbe Weg wie in ``test_stufe2_hoeren``: nachsehen, ob
    der ECHTE Aufbau es tut.
    """

    quelle = inspect.getsource(VoicePipeline.__init__)
    kopf, _, stop_teil = quelle.partition("self._stop_transcriber = Transcriber(")

    assert stop_teil, "der Stop-Erkenner wird nicht mehr hier gebaut"
    rumpf = stop_teil.split("self._transcriber", 1)[0]

    assert "vad_filter=True" in rumpf, (
        "ohne Sprachfilter dekodiert der Stop-Erkenner die Stille zwischen "
        "den Woertern - dreissig Sekunden aufgefuellt, fuer 0,6 Sekunden Ton"
    )
    assert "temperatur_treppe=False" in rumpf, (
        "die sechsstufige Treppe ist der Faktor zwoelf vom 15:09:48"
    )
    assert "vad_filter=True" not in kopf, (
        "der Hauptweg soll den Filter nicht bekommen - dort ist die "
        "Sprachaktivitaet schon vor der Aufnahme geprueft"
    )
