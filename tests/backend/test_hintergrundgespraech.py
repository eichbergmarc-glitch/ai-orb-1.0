"""Bin ich gemeint? - Anrede gegen Hintergrundgespräch.

Der Anlass steht im Protokoll vom 17.08.2026. Nach einer Antwort hört der
Orb 45 Sekunden weiter zu, ohne dass man ihn erneut weckt - und in diesem
Fenster galt bisher ALLES als Anweisung::

    13:40:12  "Ihr seid, wenn ihr sich etwas spürtzuschreifen ..."
    13:40:51  "Vielen Dank."
    13:41:12  "Die Kirchenweine und Schachtwäsche."
    13:42:07  "Ja, und in Spannung von dem Ding, was wir haben, was wir
               haben, was wir haben ..."

Nichts davon war an den Orb gerichtet: ein Gespräch im Raum, ein
Fernseher, seine eigene Lautsprecherstimme. Diese Tests halten fest, dass
er so etwas erkennt und schweigt - und dass er umgekehrt keinen echten
Auftrag verschluckt. Die Sätze unten sind echte Protokollzeilen, keine
erfundenen Beispiele.
"""

from __future__ import annotations

import pytest

from backend.voice.gespraechsrichtung import einschaetzen


# --- Was NICHT an den Orb gerichtet war (echte Protokollzeilen) -------------


@pytest.mark.parametrize(
    "satz, sicherheit",
    [
        ("Vielen Dank.", 0.77),
        ("Die Kirchenweine und Schachtwäsche.", 0.82),
        ("Ihr seid, wenn ihr sich etwas spürtzuschreifen wie Spurgegenteil", 0.80),
        ("Das heißt, wir machen das, was wir tun, was wir tun, was wir tun, "
         "was wir tun.", 0.81),
        ("Ja, und in Spannung von dem Ding, was wir haben, ist eine Weine. "
         "Und dann war es nicht so, was wir haben. Und dann war es nicht so, "
         "was wir haben.", 0.82),
        ("Sollte.", 0.79),
        ("Ja genau", 0.9),
        ("Ach so", 0.88),
    ],
)
def test_hintergrundgespraech_wird_erkannt(satz, sicherheit):
    urteil = einschaetzen(satz, sicherheit=sicherheit)
    assert not urteil.antworten, f"haette schweigen muessen: {urteil.grund}"


# --- Was sehr wohl an den Orb gerichtet war --------------------------------


@pytest.mark.parametrize(
    "satz",
    [
        "Hallo Orb, gib mir die News des Tages zusammengefasst",
        "Was machst du gerade?",
        "Wie geht es dir gerade?",
        "Kannst du mich jetzt verstehen?",
        "Suche einmal nach dem Philosophen Markus Gabriel",
        "Trag mir morgen um 14 Uhr den Zahnarzt ein",
        "Erklär mir bitte die Julikrise",
        "Eigne dir das Wissen über Emmy Noether an",
        "Lies mir die Nachrichten vor",
        "Stopp",
        "Weiter",
        "Was steht heute an?",
    ],
)
def test_eine_echte_anrede_kommt_durch(satz):
    urteil = einschaetzen(satz, sicherheit=0.9)
    assert urteil.antworten, f"haette antworten muessen: {urteil.grund}"


def test_der_eigene_name_schlaegt_alles():
    # Auch bei maessiger Erkennung und mitten im Satz: Wer "Orb" sagt,
    # meint den Orb.
    urteil = einschaetzen("also Orb das mit dem Ding da", sicherheit=0.55)
    assert urteil.antworten
    assert "Name" in urteil.grund


# --- Der Anschluss an eine eigene Rückfrage --------------------------------


def test_ein_ja_zaehlt_nur_nach_einer_rueckfrage():
    # "Ja" nach einer eigenen Rueckfrage des Orb ist die Antwort darauf.
    an_mich = einschaetzen("Ja, mach das", sicherheit=0.9, wurde_gefragt=True)
    assert an_mich.antworten

    # Dasselbe "Ja" ohne offene Rueckfrage ist Gespraech im Raum.
    im_raum = einschaetzen("Ja, mach das", sicherheit=0.9, wurde_gefragt=False)
    assert not im_raum.antworten
    assert "Rückfrage" in im_raum.grund


def test_andere_adressaten_schliessen_den_orb_aus():
    for satz in ("Ihr habt das doch gesehen", "Wir müssen dann los",
                 "Schatz, kommst du?"):
        urteil = einschaetzen(satz, sicherheit=0.95)
        assert not urteil.antworten, satz
        assert not urteil.antworten


# --- Die Grenzfälle --------------------------------------------------------


def test_wortschleifen_sind_nie_eine_anrede():
    from backend.voice.gespraechsrichtung import _ist_geplapper

    assert _ist_geplapper("das ist das, das ist das, das ist das, das ist das")
    assert not _ist_geplapper("Erklär mir bitte die Grundzüge der Quantenmechanik")


def test_im_zweifel_wird_geschwiegen_nicht_geraten():
    # Klar verstanden, aber ohne Anrede, Frage oder Auftrag: 'unklar' -
    # und 'unklar' heisst schweigen. Ein uebersehener Auftrag kostet eine
    # Wiederholung, eine Antwort auf ein fremdes Gespraech kostet
    # Vertrauen.
    urteil = einschaetzen("Der Zug fährt um zehn nach drei", sicherheit=0.95)
    assert urteil.art == "unklar"
    assert not urteil.antworten


def test_jedes_urteil_nennt_seinen_grund():
    # Der Grund steht im Protokoll. Ohne ihn waere spaeter nicht
    # nachvollziehbar, warum der Orb geschwiegen hat - und genau das
    # muesste man dann wieder muehsam suchen.
    for satz in ("Vielen Dank.", "Was machst du?", "Der Zug faehrt gleich"):
        urteil = einschaetzen(satz, sicherheit=0.9)
        assert urteil.grund and len(urteil.grund) > 8
        assert urteil.art in ("an_mich", "hintergrund", "unklar")


def test_die_pipeline_fragt_wirklich_nach_der_richtung():
    # Das Urteil nuetzt nichts, wenn es niemand einholt - genau so ist
    # frueher schon eine fertige Maschinerie unerreichbar geblieben.
    from pathlib import Path

    quelle = Path("backend/voice/voice_pipeline.py").read_text(encoding="utf-8")
    anfang = quelle.index("async def _handle_while_awake")
    ausschnitt = quelle[anfang:anfang + 4000]
    assert "gespraechsrichtung" in ausschnitt
    assert "richtung.antworten" in ausschnitt
    assert "_wartet_auf_antwort" in ausschnitt
