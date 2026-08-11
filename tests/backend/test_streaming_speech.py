"""Tests des fluessigen Sprechens.

Zwei Dinge werden geprueft: dass Modell-Stuecke korrekt zu ganzen Saetzen
gesammelt werden (nicht mitten im Wort gesprochen wird), und dass eine
Abkuerzung wie "z. B." den Satz nicht vorzeitig beendet.
"""

from __future__ import annotations

from backend.voice.voice_pipeline import _take_complete_sentence


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
    text = "und dann kamen die einen und die anderen " * 6  # > 160 Zeichen, kein Punkt
    satz, rest = _take_complete_sentence(text)
    assert satz, "Ein langer Fluss ohne Punkt sollte weich umgebrochen werden."
    assert len(satz) < len(text)


def test_fragezeichen_beendet_den_satz():
    saetze = _drain(["Warum ", "begann ", "sie? ", "Niemand ", "weiss ", "es."])
    assert saetze[0] == "Warum begann sie?"
