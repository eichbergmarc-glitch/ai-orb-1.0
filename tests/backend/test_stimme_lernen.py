"""Tests der Stimmerkennung an echten Wellenformen.

Der Orb konnte sich keine Stimme merken. Es lag nicht an den Aufnahmen,
sondern an einer Einheit.

Die Lautstaerke eines Rahmens kommt aus dem nullten MFCC-Koeffizienten -
der Summe der logarithmierten Mel-Werte, im natuerlichen Logarithmus. Ein
Punkt darin sind rund 0,167 Dezibel und nicht eines. Die Grenze "hoechstens
25 unter dem lautesten Rahmen" bedeutete deshalb in Wahrheit 4,2 dB. In
einem gesprochenen Satz liegen zwischen dem lautesten Vokal und einem
unbetonten Konsonanten aber leicht zwanzig Dezibel: Es blieben nur die
Gipfel uebrig, aus mehreren Saetzen wurde eine Drittelsekunde Sprache, und
der Orb meldete jedes Mal "die Aufnahmen waren zu kurz".

Das Toeckische daran: Jeder einzelne Test der Rechenschritte waere gruen
geblieben. Die Filterbank stimmt, die DCT stimmt, die Aehnlichkeit stimmt.
Falsch war nur, was eine Zahl BEDEUTET - und das faellt erst auf, wenn man
eine ganze Aufnahme durchschickt.

Deshalb bauen diese Tests kuenstliche, aber sprachaehnliche Wellenformen:
mit Grundton, Obertoenen, Pausen zwischen den Woertern und - das ist der
entscheidende Teil - mit ungleich lauten Woertern.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

from backend.voice.speaker_id import (
    ABSTAND_ZUM_GIPFEL_DB,
    HOP_MS,
    MEL_FILTERS,
    MIN_SPEECH_SECONDS,
    Stimmerkennung,
    abdruck,
    merkmale,
)

import numpy as np  # noqa: E402 - erst nach dem Modul, das ihn ohnehin braucht.


def _stimme(
    pfad: Path,
    lautstaerken: list[float],
    *,
    grundton: float = 110.0,
    saat: int = 11,
) -> Path:
    """Baut eine sprachaehnliche Aufnahme.

    Wichtig sind drei Eigenschaften, und alle drei kommen in echter Sprache
    vor: ein Grundton mit Obertoenen (daran haengt der Klang einer Stimme),
    Pausen zwischen den Woertern, und ungleich laute Woerter. Die letzte ist
    die, an der es scheiterte.
    """

    rate = 16000
    t = np.arange(int(rate * 3.2)) / rate
    signal = np.zeros_like(t)
    rng = np.random.default_rng(saat)

    for (start, dauer), staerke in zip(
        [(0.15, 0.45), (0.75, 0.50), (1.45, 0.40), (2.05, 0.60)], lautstaerken
    ):
        a = int(start * rate)
        b = int((start + dauer) * rate)
        tt = t[a:b] - t[a]
        # Ein leicht schwankender Grundton - eine feste Frequenz klaenge
        # wie ein Signalton und nicht wie eine Stimme.
        phase = 2 * np.pi * np.cumsum(grundton + 8 * np.sin(2 * np.pi * 3 * tt)) / rate
        welle = sum(
            c * np.sin(k * phase)
            for k, c in [(1, 1.0), (2, 0.6), (3, 0.45), (5, 0.3), (7, 0.22), (11, 0.15), (17, 0.08)]
        )
        signal[a:b] = welle * np.hanning(len(tt)) * staerke

    signal += rng.normal(0, 0.0015, signal.shape)

    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes())
    return pfad


# --- Die Einheit -----------------------------------------------------------------


def _rauschen(pfad: Path, amplitude: float, saat: int = 5) -> Path:
    """Baut gleichmaessiges Rauschen mit bekanntem Pegel.

    Fuer die Pruefung der EINHEIT ist Rauschen das richtige Signal und
    eine Stimme das falsche. Bei einer Stimme tragen die hohen Filter kaum
    Energie; halbiert man die Amplitude, sinken sie nicht mit, weil dort
    ohnehin nur der Rauschboden steht. Der Mittelwert ueber die Filter
    faellt dann um weniger als sechs Dezibel - nicht, weil die Einheit
    falsch waere, sondern weil das Signal nicht ueberall skaliert.

    Bei Rauschen tragen alle Filter, und die Rechnung ist sauber.
    """

    rate = 16000
    rng = np.random.default_rng(saat)
    signal = rng.normal(0, amplitude, int(rate * 1.5))

    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(rate)
        datei.writeframes((np.clip(signal, -1, 1) * 32767).astype("<i2").tobytes())
    return pfad


def test_die_lautstaerke_kommt_in_dezibel_heraus():
    """Der Fehler in einem Satz: Ein Punkt DCT-0 ist kein Dezibel.

    Geprueft wird an einem Signal, dessen Pegel bekannt ist: Wird die
    Amplitude halbiert, muss die gemessene Lautstaerke um genau 6,02 dB
    fallen. Faellt sie um einen anderen Betrag, stimmt die Einheit nicht -
    und dann bedeutet jede Grenze, die man in Dezibel notiert, etwas
    anderes als das, was dort steht. Vorher waeren es 36 Punkte gewesen,
    und wer die fuer Dezibel hielt, verrechnete sich um das Sechsfache.
    """

    _, laut = merkmale(_rauschen(Path("/tmp/pegel-laut.wav"), 0.20))
    _, leise = merkmale(_rauschen(Path("/tmp/pegel-leise.wav"), 0.10))

    gefallen = float(np.median(laut)) - float(np.median(leise))
    erwartet = 20.0 * math.log10(2.0)

    assert abs(gefallen - erwartet) < 0.3, (
        f"Halbe Amplitude ergibt {gefallen:.2f} statt {erwartet:.2f} dB - "
        "die Lautstaerke steht nicht in Dezibel"
    )


def test_die_alte_einheit_haette_der_test_gefangen():
    """Die Gegenprobe: In der alten Einheit waere derselbe Abfall 36 Punkte.

    Das ist der Kern des Fehlers als Zahl. Wer 'hoechstens 25 unter dem
    Gipfel' schrieb und Dezibel meinte, liess in Wahrheit nur 4,2 dB zu -
    und aus einem gesprochenen Satz blieben die Vokalgipfel uebrig.
    """

    faktor = 10.0 / math.log(10.0) / MEL_FILTERS
    assert abs(faktor - 0.167) < 0.005, "die Umrechnung stimmt nicht mehr"
    # Was frueher '25' hiess, waren in Wahrheit gut vier Dezibel.
    assert abs(25.0 * faktor - 4.2) < 0.2


def test_die_grenze_laesst_einen_ganzen_satz_durch():
    """Zwanzig Dezibel Spanne innerhalb eines Satzes sind normal."""

    assert ABSTAND_ZUM_GIPFEL_DB >= 20.0, "die Grenze schneidet die leisen Woerter weg"
    assert ABSTAND_ZUM_GIPFEL_DB <= 45.0, "die Grenze laesst die Pausen mit durch"


# --- Und was daran haengt ---------------------------------------------------------


def test_ungleich_laute_woerter_ergeben_trotzdem_einen_abdruck():
    """Der Test, der gefehlt hat.

    Vier Woerter mit rund vierzehn Dezibel Unterschied - also eine ganz
    gewoehnliche Aeusserung. Vorher blieben davon 0,34 Sekunden uebrig und
    der Abdruck war None.
    """

    pfad = _stimme(Path("/tmp/ungleich.wav"), [0.40, 0.09, 0.22, 0.06])

    _, energie = merkmale(pfad)
    untergrenze = max(
        float(np.percentile(energie, 40.0)),
        float(np.max(energie)) - ABSTAND_ZUM_GIPFEL_DB,
    )
    sekunden = int((energie >= untergrenze).sum()) * HOP_MS / 1000.0

    assert sekunden >= MIN_SPEECH_SECONDS, (
        f"nur {sekunden:.2f} s Sprache erkannt, noetig sind {MIN_SPEECH_SECONDS}"
    )
    assert abdruck(pfad) is not None, "kein Abdruck aus einer gewoehnlichen Aeusserung"


def test_die_pausen_fallen_trotzdem_weg():
    """Sonst haette man das Gegenteil erreicht: In den Pausen steht der
    Klang des Raumes, nicht der der Person."""

    pfad = _stimme(Path("/tmp/pausen.wav"), [0.40, 0.30, 0.35, 0.30])
    _, energie = merkmale(pfad)

    untergrenze = max(
        float(np.percentile(energie, 40.0)),
        float(np.max(energie)) - ABSTAND_ZUM_GIPFEL_DB,
    )
    anteil = float((energie >= untergrenze).mean())

    assert anteil < 0.85, "es wird gar nichts mehr weggeworfen"


def test_eine_stimme_laesst_sich_wirklich_lernen(tmp_path: Path):
    """Der ganze Weg, von der Wellenform bis zum gespeicherten Profil."""

    proben = [
        _stimme(tmp_path / "a.wav", [0.40, 0.09, 0.22, 0.06], saat=1),
        _stimme(tmp_path / "b.wav", [0.30, 0.12, 0.18, 0.08], saat=2),
        _stimme(tmp_path / "c.wav", [0.35, 0.10, 0.25, 0.07], saat=3),
    ]

    erkennung = Stimmerkennung(profil_pfad=tmp_path / "stimme.json")
    geklappt, meldung = erkennung.lernen(proben)

    assert geklappt, meldung
    assert erkennung.aktiv
    assert (tmp_path / "stimme.json").is_file(), "das Profil wurde nicht gespeichert"


def test_die_eigene_stimme_wird_wiedererkannt(tmp_path: Path):
    """Gelernt zu haben und niemanden zu erkennen waere dasselbe Uebel."""

    erkennung = Stimmerkennung(profil_pfad=tmp_path / "stimme.json")
    geklappt, meldung = erkennung.lernen(
        [
            _stimme(tmp_path / "a.wav", [0.40, 0.09, 0.22, 0.06], saat=1),
            _stimme(tmp_path / "b.wav", [0.30, 0.12, 0.18, 0.08], saat=2),
            _stimme(tmp_path / "c.wav", [0.35, 0.10, 0.25, 0.07], saat=3),
        ]
    )
    assert geklappt, meldung

    weitere = _stimme(tmp_path / "d.wav", [0.33, 0.11, 0.20, 0.07], saat=4)
    urteil = erkennung.pruefen(weitere)

    assert urteil.geprueft, "die Pruefung kam gar nicht zustande"
    assert urteil.akzeptiert, (
        f"die eigene Stimme wurde abgewiesen (Aehnlichkeit {urteil.aehnlichkeit:.3f}, "
        f"Schwelle {urteil.schwelle:.3f})"
    )


def test_eine_deutlich_andere_stimme_wird_abgewiesen(tmp_path: Path):
    """Sonst waere die Erkennung eine Zusage ohne Deckung."""

    erkennung = Stimmerkennung(profil_pfad=tmp_path / "stimme.json")
    geklappt, _ = erkennung.lernen(
        [
            _stimme(tmp_path / "a.wav", [0.40, 0.09, 0.22, 0.06], saat=1, grundton=110.0),
            _stimme(tmp_path / "b.wav", [0.30, 0.12, 0.18, 0.08], saat=2, grundton=112.0),
            _stimme(tmp_path / "c.wav", [0.35, 0.10, 0.25, 0.07], saat=3, grundton=108.0),
        ]
    )
    assert geklappt

    # Eine deutlich hoehere Stimme mit anderem Klang.
    fremd = _stimme(tmp_path / "f.wav", [0.35, 0.11, 0.21, 0.07], saat=9, grundton=235.0)
    urteil = erkennung.pruefen(fremd)

    assert not urteil.akzeptiert, (
        f"eine fremde Stimme kam durch (Aehnlichkeit {urteil.aehnlichkeit:.3f}, "
        f"Schwelle {urteil.schwelle:.3f})"
    )


def test_stille_ergibt_keinen_abdruck():
    """Und keinen Absturz."""

    pfad = Path("/tmp/stille.wav")
    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(16000)
        datei.writeframes(b"\x00\x00" * 16000 * 2)

    assert abdruck(pfad) is None
