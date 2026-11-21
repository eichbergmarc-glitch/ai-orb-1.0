"""Prosodie-Markup und Begruessung (17.11.2026)."""

from __future__ import annotations

import random
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.tts import prosodie
from backend.tts.prosodie import Einstellungen, Fortsetzung, Segment, entfernen, zerlegen


def test_entfernen_laesst_nie_markup_stehen() -> None:
    text = "Das ist <emphasis>wirklich</emphasis> wichtig.<pause 0.5> Und <slow>jetzt langsam</slow>. <breath/>Ende <pau"
    klar = entfernen(text)
    assert "<" not in klar and ">" not in klar
    assert klar == "Das ist wirklich wichtig. Und jetzt langsam. Ende"


def test_entfernen_aendert_text_ohne_markup_nicht() -> None:
    assert entfernen("Preis : 5  Franken") == "Preis : 5  Franken"


def test_zerlegen_baut_segmente() -> None:
    segmente = zerlegen("Zuerst normal. <pause 0,6> <slow>Dann ganz in Ruhe erklaert</slow>, und weiter.")
    assert segmente == [
        Segment("Zuerst normal."),
        Segment(pause=0.6),
        Segment("Dann ganz in Ruhe erklaert,", langsam=True),
        Segment("und weiter."),
    ]


def test_satzzeichen_werden_nie_allein_gesprochen() -> None:
    segmente = zerlegen("Das ist <emphasis>der eigentliche Punkt hier</emphasis>.")
    assert [s.text for s in segmente] == ["Das ist", "der eigentliche Punkt hier."]


def test_kurze_betonung_wird_nicht_abgetrennt() -> None:
    segmente = zerlegen("Das ist <emphasis>entscheidend</emphasis> fuer dich.")
    assert len(segmente) == 1
    assert segmente[0].text == "Das ist entscheidend fuer dich."
    assert segmente[0].hervorheben == ("entscheidend",)
    assert not prosodie.braucht_segmente(segmente)
    assert "entscheidend" in prosodie.regie_fuer(segmente[0])


def test_lange_betonung_ist_eigenes_segment() -> None:
    segmente = zerlegen("Merk dir: <emphasis>das gilt fuer jeden Fall</emphasis>.")
    assert any(s.betont for s in segmente)
    assert prosodie.braucht_segmente(segmente)


def test_randpausen_und_pausengrenze() -> None:
    segmente = zerlegen("<breath>Hallo<pause 9> du<pause 1>")
    assert segmente[0].text == "Hallo"
    assert segmente[1].pause == 1.5  # gedeckelt
    assert segmente[-1].text == "du"


def test_unsauberes_markup_stuerzt_nicht() -> None:
    assert zerlegen("</slow>Text <slow>offen bis zum Ende") == [
        Segment("Text"), Segment("offen bis zum Ende", langsam=True)
    ]


def test_satzzeichen_nach_aussen() -> None:
    assert prosodie.satzzeichen_nach_aussen("<slow>Wichtig.</slow> Weiter") == "<slow>Wichtig</slow>. Weiter"


def test_fortsetzung_traegt_hoechstens_zwei_saetze() -> None:
    f = Fortsetzung()
    assert f.weiter("<slow>Eins.") == "<slow>Eins."
    assert f.weiter("Zwei.") == "<slow>Zwei."
    assert f.weiter("Drei.") == "<slow>Drei."
    assert f.weiter("Vier.") == "Vier."


def test_fortsetzung_endet_mit_schliessendem_tag() -> None:
    f = Fortsetzung()
    f.weiter("<slow>Eins.")
    assert f.weiter("Zwei</slow>.") == "<slow>Zwei</slow>."
    assert f.weiter("Drei.") == "Drei."


def test_streuung_bleibt_in_grenzen() -> None:
    z = random.Random(1)
    werte = {prosodie.tempo_streuen(1.0, 0.03, z) for _ in range(200)}
    assert min(werte) >= 0.97 and max(werte) <= 1.03 and len(werte) > 3
    pausen = [prosodie.pause_streuen(0.3, 0.15, z) for _ in range(200)]
    assert 0.255 <= min(pausen) and max(pausen) <= 0.345
    assert prosodie.tempo_streuen(1.0, 0.0) == 1.0


def _ton(pfad: Path, sekunden: float, rate: int = 24000, pegel: float = 0.3) -> Path:
    t = np.arange(int(rate * sekunden)) / rate
    daten = np.concatenate([np.zeros(int(rate * 0.2)), pegel * np.sin(2 * np.pi * 220 * t), np.zeros(int(rate * 0.2))])
    with wave.open(str(pfad), "wb") as h:
        h.setnchannels(1); h.setsampwidth(2); h.setframerate(rate)
        h.writeframes((daten * 32767).astype("<i2").tobytes())
    return pfad


def test_wavs_verbinden_mit_pause_ohne_klick(tmp_path: Path) -> None:
    a = _ton(tmp_path / "a.wav", 0.5)
    b = _ton(tmp_path / "b.wav", 0.5, rate=22050)  # anderer Takt wird umgerechnet
    ziel = tmp_path / "ziel.wav"
    dauer = prosodie.wavs_verbinden([(a, 0.0, 1.0), (None, 0.4, 1.0), (b, 0.0, 1.12)], ziel)
    # 2 x (0.5 s Ton + 2 x 25 ms Rand) + 0.4 s Pause
    assert abs(dauer - 1.5) < 0.02
    with wave.open(str(ziel), "rb") as h:
        assert h.getframerate() == 24000
        daten = np.frombuffer(h.readframes(h.getnframes()), dtype="<i2").astype(float) / 32768
    # Keine harten Spruenge an den Naehten
    assert np.max(np.abs(np.diff(daten))) < 0.05
    # Betontes Segment ist lauter
    erste, zweite = daten[: len(daten) // 3], daten[-len(daten) // 3 :]
    assert np.abs(zweite).max() > np.abs(erste).max() * 1.08


def test_einstellungen_werden_begrenzt() -> None:
    e = Einstellungen.aus_config({"tempo_langsam": 0.2, "pausen_streuung": 5, "enabled": False})
    assert e.tempo_langsam == 0.75 and e.pausen_streuung == 0.4 and not e.eingeschaltet


# --- Begruessung ---------------------------------------------------------------------


def test_begruessung_wiederholt_sich_nicht(tmp_path: Path) -> None:
    from backend.presence.begruessung import GEDAECHTNIS, erzeugen

    ablage = tmp_path / "b.json"
    z = random.Random(7)
    gruesse = [erzeugen(name="Marc", zufall=z, speicher=ablage) for _ in range(GEDAECHTNIS)]
    assert len(set(gruesse)) == GEDAECHTNIS


def test_begruessung_passt_sich_ab_und_zu_der_tageszeit_an() -> None:
    from backend.presence.begruessung import erzeugen

    z = random.Random(3)
    nachts = [erzeugen(jetzt=datetime(2026, 11, 17, 2, 30), zufall=z, speicher=None) for _ in range(60)]
    morgens = [erzeugen(jetzt=datetime(2026, 11, 17, 7, 0), zufall=z, speicher=None) for _ in range(60)]
    assert any("Noch wach" in g or "Nachteule" in g for g in nachts)
    assert not any("Guten Morgen" in g for g in nachts)
    assert any("Morgen" in g for g in morgens)
    # Nicht jede Begruessung nennt die Tageszeit
    assert any("Morgen" not in g and "Kaffee" not in g for g in morgens)


def test_begruessung_nennt_einschraenkungen() -> None:
    from backend.presence.begruessung import erzeugen

    assert "eingeschränkt" in erzeugen(einschraenkungen=True, speicher=None)


def test_antwortstrom_trennt_saetze_trotz_markup() -> None:
    from backend.orchestrator.speech_stream import SpeechStream

    strom = SpeechStream()
    saetze: list[str] = []
    for stueck in ("Das ist <slow>wirk", "lich wichtig.</slow> Und dann", "? Mit <emphasis>Dr. Meier</emphasis>. Ende"):
        saetze += strom.feed(stueck)
    saetze += strom.finish()
    assert saetze == [
        "Das ist <slow>wirklich wichtig.</slow>",
        "Und dann?",
        "Mit <emphasis>Dr. Meier</emphasis>.",
        "Ende",
    ]


# --- Laute fuer die Colab-Stimme -------------------------------------------------------


def test_laute_bleiben_nur_auf_wunsch_stehen() -> None:
    text = "Das ist <lachen> wirklich lustig. <slow>Ruhig</slow>."
    assert entfernen(text) == "Das ist wirklich lustig. Ruhig."
    assert entfernen(text, laute_behalten=True) == "Das ist <lachen> wirklich lustig. Ruhig."
    assert prosodie.laute_entfernen("<hmm> Gute Frage.") == "Gute Frage."
    assert prosodie.hat_laute("x <Schmunzeln/> y")


def test_laute_ueberstehen_das_zerlegen() -> None:
    segmente = zerlegen("Ha <schmunzeln> das ist <emphasis>wirklich ganz witzig hier</emphasis>.")
    assert segmente[0].text == "Ha <schmunzeln> das ist"


def test_kartoffel_server_uebersetzt_laute() -> None:
    import re
    from pathlib import Path

    quelle = (Path(__file__).resolve().parents[2] / "server" / "kartoffel_tts_server.py").read_text(encoding="utf-8")
    teil = quelle[quelle.index("#: Laute des Orb"):quelle.index('print("[stimme] Lade')]
    namen: dict = {"re": re}
    exec(teil, namen)  # noqa: S102 - nur die Tabellen, kein Modell
    exec(quelle[quelle.index("def text_vorbereiten"):quelle.index("def sprechen")], namen)  # noqa: S102
    vorbereiten = namen["text_vorbereiten"]
    assert vorbereiten("Das ist <lachen> komisch.") == "Das ist <haha> komisch."
    assert vorbereiten("<slow>Ruhig</slow> <pause 0.4> weiter.") == "Ruhig weiter."
    # Jeder Laut des Orb hat eine Entsprechung im Server.
    assert set(prosodie.LAUT_NAMEN) <= set(namen["LAUTE"])


def test_regie_fuer_satz_statt_schnitt() -> None:
    segmente = zerlegen("Das ist <emphasis>der eigentliche Punkt hier</emphasis>.<pause 0.6> <slow>Dann ganz ruhig weiter</slow>.")
    regie = prosodie.regie_fuer_satz(segmente)
    assert "mit Nachdruck" in regie and "langsamer" in regie and "0.6 Sekunden" in regie
    assert "in einem Bogen" in regie
    assert prosodie.regie_fuer_satz(zerlegen("Ganz normal.")) == ""
