"""Tests der Stimmerkennung - auf wen der Orb hoert und auf wen nicht.

Das Mikrofon hoert alles: den Fernseher, ein Gespraech nebenan, eine
Videokonferenz. Ohne Pruefung ist dem Orb jede Stimme gleich viel wert.

Geprueft wird mit kuenstlichen Stimmen: ein Impulston, durch Resonanzen
gefiltert, wie es der Vokaltrakt tut. Zwei "Sprecher" unterscheiden sich
darin genau so, wie sich Menschen unterscheiden - in den Formanten, also
in der Klangfarbe, nicht in der Lautstaerke oder im Text.

Was hier NICHT geprueft werden kann, ist die Trefferquote bei echten
Stimmen; dafuer braeuchte es echte Aufnahmen. Geprueft wird die Mechanik:
dass gleiche Stimmen zusammenfinden, verschiedene auseinander, und dass im
Zweifel zugehoert wird statt ausgesperrt.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

from backend.voice.speaker_id import (
    SAMPLE_RATE,
    Stimmerkennung,
    abdruck,
    aehnlichkeit,
    merkmale,
)

# Zwei Vokaltrakte: Formant, Bandbreite, Gewicht.
SPRECHER_A = [(730.0, 80.0, 1.0), (1090.0, 90.0, 0.6), (2440.0, 120.0, 0.3)]
SPRECHER_B = [(390.0, 60.0, 1.0), (1990.0, 100.0, 0.5), (2550.0, 120.0, 0.35)]


def _stimme(
    pfad: Path,
    formanten: list[tuple[float, float, float]],
    *,
    grundton: float = 120.0,
    sekunden: float = 2.0,
    versatz: int = 0,
    lautstaerke: float = 0.7,
) -> Path:
    """Erzeugt eine kuenstliche Stimme als WAV-Datei.

    Quelle-Filter-Modell: eine Impulsfolge (die Stimmlippen) laeuft durch
    Resonanzen (den Vokaltrakt). Das ist grob, aber es traegt genau das
    Merkmal, um das es geht.
    """

    import numpy as np

    rng = np.random.default_rng(versatz)
    anzahl = int(SAMPLE_RATE * sekunden)
    zeit = np.arange(anzahl) / SAMPLE_RATE

    anregung = np.zeros(anzahl)
    periode = int(SAMPLE_RATE / grundton)
    stelle = 0
    while stelle < anzahl:
        anregung[stelle] = 1.0
        stelle += periode + int(rng.integers(-2, 3))

    ausgabe = np.zeros(anzahl)
    for frequenz, bandbreite, gewicht in formanten:
        r = math.exp(-math.pi * bandbreite / SAMPLE_RATE)
        theta = 2 * math.pi * frequenz / SAMPLE_RATE
        a1 = -2 * r * math.cos(theta)
        a2 = r * r
        gefiltert = np.zeros(anzahl)
        for i in range(2, anzahl):
            gefiltert[i] = anregung[i] - a1 * gefiltert[i - 1] - a2 * gefiltert[i - 2]
        ausgabe += gewicht * gefiltert

    # Silbenrhythmus, damit es lautere und leisere Stellen gibt.
    ausgabe *= 0.6 + 0.4 * np.sin(2 * math.pi * 3.0 * zeit)
    ausgabe /= np.max(np.abs(ausgabe)) + 1e-9
    ausgabe *= lautstaerke

    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(SAMPLE_RATE)
        datei.writeframes((ausgabe * 32767).astype("<i2").tobytes())
    return pfad


def _stille(pfad: Path, sekunden: float = 2.0) -> Path:
    with wave.open(str(pfad), "wb") as datei:
        datei.setnchannels(1)
        datei.setsampwidth(2)
        datei.setframerate(SAMPLE_RATE)
        datei.writeframes(b"\x00\x00" * int(SAMPLE_RATE * sekunden))
    return pfad


# --- Die Merkmale ---------------------------------------------------------------


def test_merkmale_entstehen(tmp_path: Path):
    pfad = _stimme(tmp_path / "a.wav", SPRECHER_A)
    koeffizienten, energie = merkmale(pfad)

    assert koeffizienten.shape[1] == 12, "es sollen zwoelf Koeffizienten sein"
    assert koeffizienten.shape[0] > 100, "zwei Sekunden ergeben viele Rahmen"
    assert energie.shape[0] == koeffizienten.shape[0]


def test_lautstaerke_aendert_den_abdruck_kaum(tmp_path: Path):
    """Wie laut jemand spricht, hat mit seiner Identitaet nichts zu tun.

    Genau deshalb wird der nullte Koeffizient weggelassen - er misst im
    Wesentlichen die Lautstaerke.
    """

    laut = abdruck(_stimme(tmp_path / "laut.wav", SPRECHER_A, lautstaerke=0.9))
    leise = abdruck(_stimme(tmp_path / "leise.wav", SPRECHER_A, lautstaerke=0.2))

    assert laut is not None and leise is not None
    assert aehnlichkeit(laut, leise) > 0.95, "dieselbe Stimme, nur leiser"


def test_verschiedene_stimmen_liegen_auseinander(tmp_path: Path):
    eins = abdruck(_stimme(tmp_path / "a.wav", SPRECHER_A))
    zwei = abdruck(_stimme(tmp_path / "b.wav", SPRECHER_B, grundton=200.0))

    assert eins is not None and zwei is not None
    naehe = aehnlichkeit(eins, zwei)
    assert naehe < 0.5, f"zwei Vokaltrakte, aber Aehnlichkeit {naehe:.2f}"


def test_stille_ergibt_keinen_abdruck(tmp_path: Path):
    """Aus Stille laesst sich keine Stimme lesen - und das muss auffallen,
    statt in einen Zufallsvektor zu muenden."""

    assert abdruck(_stille(tmp_path / "still.wav")) is None


def test_zu_kurze_aufnahme_ergibt_keinen_abdruck(tmp_path: Path):
    kurz = _stimme(tmp_path / "kurz.wav", SPRECHER_A, sekunden=0.3)
    assert abdruck(kurz) is None


# --- Lernen und Pruefen ---------------------------------------------------------


def _erkennung(tmp_path: Path, **kw) -> Stimmerkennung:
    return Stimmerkennung(profil_pfad=tmp_path / "profil.json", **kw)


def _lernproben(tmp_path: Path) -> list[Path]:
    return [
        _stimme(tmp_path / f"lern{i}.wav", SPRECHER_A, grundton=118.0 + i * 3, versatz=i)
        for i in range(3)
    ]


def test_ohne_profil_wird_jeder_gehoert(tmp_path: Path):
    """Wirksam wird die Pruefung erst, wenn eine Stimme hinterlegt ist."""

    erkennung = _erkennung(tmp_path)
    urteil = erkennung.pruefen(_stimme(tmp_path / "wer.wav", SPRECHER_B))

    assert urteil.akzeptiert is True
    assert urteil.geprueft is False
    assert erkennung.aktiv is False


def test_die_eigene_stimme_wird_wiedererkannt(tmp_path: Path):
    erkennung = _erkennung(tmp_path)
    geklappt, meldung = erkennung.lernen(_lernproben(tmp_path))

    assert geklappt, meldung
    assert erkennung.aktiv is True

    spaeter = _stimme(tmp_path / "spaeter.wav", SPRECHER_A, grundton=124.0, versatz=77)
    urteil = erkennung.pruefen(spaeter)

    assert urteil.akzeptiert is True, f"eigene Stimme abgewiesen ({urteil.aehnlichkeit:.2f})"
    assert urteil.geprueft is True


def test_eine_fremde_stimme_wird_ueberhoert(tmp_path: Path):
    """Der Punkt der ganzen Uebung."""

    erkennung = _erkennung(tmp_path)
    erkennung.lernen(_lernproben(tmp_path))

    fremd = _stimme(tmp_path / "fremd.wav", SPRECHER_B, grundton=205.0, versatz=9)
    urteil = erkennung.pruefen(fremd)

    assert urteil.akzeptiert is False
    assert urteil.geprueft is True
    assert urteil.aehnlichkeit < urteil.schwelle


def test_eine_einzige_probe_genuegt_nicht(tmp_path: Path):
    """Aus einer Aufnahme laesst sich die Schwankung nicht abschaetzen."""

    erkennung = _erkennung(tmp_path)
    geklappt, meldung = erkennung.lernen([_stimme(tmp_path / "eine.wav", SPRECHER_A)])

    assert geklappt is False
    assert "zwei bis drei" in meldung
    assert erkennung.gelernt is False


def test_zu_kurze_proben_werden_erklaert(tmp_path: Path):
    erkennung = _erkennung(tmp_path)
    kurze = [
        _stimme(tmp_path / f"k{i}.wav", SPRECHER_A, sekunden=0.25, versatz=i)
        for i in range(3)
    ]

    geklappt, meldung = erkennung.lernen(kurze)

    assert geklappt is False
    assert "zu kurz" in meldung


def test_im_zweifel_wird_zugehoert(tmp_path: Path):
    """Ein falsches Nein wiegt schwerer als ein falsches Ja.

    Wer faelschlich ausgesperrt wird, kann dem Orb nicht einmal mehr sagen,
    dass etwas nicht stimmt.
    """

    erkennung = _erkennung(tmp_path)
    erkennung.lernen(_lernproben(tmp_path))

    # Zu kurz, um verlaesslich zu urteilen.
    urteil = erkennung.pruefen(_stimme(tmp_path / "hm.wav", SPRECHER_B, sekunden=0.3))

    assert urteil.akzeptiert is True
    assert urteil.geprueft is False


def test_kaputte_datei_sperrt_niemanden_aus(tmp_path: Path):
    erkennung = _erkennung(tmp_path)
    erkennung.lernen(_lernproben(tmp_path))

    kaputt = tmp_path / "kaputt.wav"
    kaputt.write_bytes(b"das ist kein WAV")

    urteil = erkennung.pruefen(kaputt)
    assert urteil.akzeptiert is True
    assert urteil.geprueft is False


def test_die_schwelle_bleibt_unter_der_decke(tmp_path: Path):
    """Sonst scheitert spaeter die eigene Stimme, sobald sie muede klingt."""

    erkennung = _erkennung(tmp_path, hoechstschwelle=0.7)
    erkennung.lernen(_lernproben(tmp_path))

    assert erkennung.status()["schwelle"] <= 0.7


def test_die_schwelle_bleibt_ueber_dem_boden(tmp_path: Path):
    """Sonst kaeme jede Stimme durch."""

    erkennung = _erkennung(tmp_path, mindestaehnlichkeit=0.6, sicherheitsabstand=0.9)
    erkennung.lernen(_lernproben(tmp_path))

    assert erkennung.status()["schwelle"] >= 0.6


def test_profil_ueberlebt_den_neustart(tmp_path: Path):
    erste = _erkennung(tmp_path)
    erste.lernen(_lernproben(tmp_path))

    zweite = _erkennung(tmp_path)
    assert zweite.gelernt is True
    assert zweite.status()["aufnahmen"] == 3

    spaeter = _stimme(tmp_path / "spaeter.wav", SPRECHER_A, grundton=122.0, versatz=31)
    assert zweite.pruefen(spaeter).akzeptiert is True


def test_vergessen_oeffnet_wieder_fuer_alle(tmp_path: Path):
    erkennung = _erkennung(tmp_path)
    erkennung.lernen(_lernproben(tmp_path))
    assert erkennung.aktiv is True

    meldung = erkennung.vergessen()

    assert "vergessen" in meldung
    assert erkennung.gelernt is False
    fremd = _stimme(tmp_path / "fremd.wav", SPRECHER_B, grundton=205.0)
    assert erkennung.pruefen(fremd).akzeptiert is True


def test_abgeschaltet_wird_nicht_geprueft(tmp_path: Path):
    erkennung = _erkennung(tmp_path, aktiv=False)
    erkennung.lernen(_lernproben(tmp_path))

    fremd = _stimme(tmp_path / "fremd.wav", SPRECHER_B, grundton=205.0)
    assert erkennung.pruefen(fremd).akzeptiert is True
    assert erkennung.aktiv is False


def test_gesenkte_decke_gilt_auch_fuer_ein_gespeichertes_profil(tmp_path: Path):
    """Der Fehler aus dem Protokoll: Der Orb wies die EIGENE Stimme ab
    ("Fremde Stimme ueberhoert", 0.62-0.79 gegen Schwelle 0.80). Die zu
    strenge Schwelle stak im GESPEICHERTEN Profil - sie beim Lernen zu
    senken half dem, der schon ein Profil hatte, gar nichts. Nach der
    Behebung greift die gesenkte Decke sofort, ohne neues Lernen.
    """

    # Ein Profil mit kuenstlich hoher Decke lernen und ablegen.
    streng = _erkennung(tmp_path, hoechstschwelle=0.95, sicherheitsabstand=0.0)
    streng.lernen(_lernproben(tmp_path))
    assert streng.status()["schwelle"] > 0.8, "Testaufbau: Schwelle soll hoch sein."

    spaeter = _stimme(tmp_path / "spaeter.wav", SPRECHER_A, grundton=132.0, versatz=51)

    # Dasselbe Profil, aber mit gesenkter Decke geladen.
    mild = _erkennung(tmp_path, hoechstschwelle=0.55)
    urteil = mild.pruefen(spaeter)

    assert urteil.geprueft is True
    assert urteil.schwelle <= 0.55, "Die gesenkte Decke greift nicht am alten Profil."
    assert urteil.akzeptiert is True, (
        f"Eigene Stimme trotz gesenkter Decke abgewiesen "
        f"(Aehnlichkeit {urteil.aehnlichkeit:.2f}, Schwelle {urteil.schwelle:.2f})."
    )
