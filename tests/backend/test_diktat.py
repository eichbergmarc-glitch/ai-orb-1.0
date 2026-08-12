"""Tests der Diktat-Kernlogik (Tempo messen, Abschnitte bilden)."""

from __future__ import annotations

from backend.diktat.diktat import KALIBRIERSATZ, Diktierer


def _volltext(n=60):
    # Ein gleichmaessiger Text, an dem sich Abschnittsgroessen gut messen lassen.
    return " ".join(f"Wort{i}." for i in range(n))


def test_abschnitte_decken_den_ganzen_text_ohne_verlust():
    d = Diktierer()
    d.beginnen(_volltext(50))
    d.kalibrieren(len(KALIBRIERSATZ), 10.0)
    gesammelt = []
    schutz = 0
    while not d.fertig and schutz < 1000:
        st = d.naechster_abschnitt()
        assert st, "Ein Abschnitt darf nicht leer sein, solange Text da ist."
        gesammelt.append(st)
        schutz += 1
    # Nach dem Ende gibt es nichts mehr.
    assert d.naechster_abschnitt() is None
    # Zusammengesetzt ergibt sich der Originaltext (Wort fuer Wort).
    assert " ".join(gesammelt).split() == _volltext(50).split()


def test_schnelleres_schreiben_ergibt_groessere_abschnitte():
    langsam = Diktierer()
    langsam.beginnen(_volltext(80))
    langsam.kalibrieren(len(KALIBRIERSATZ), 30.0)   # lange gebraucht -> langsam

    schnell = Diktierer()
    schnell.beginnen(_volltext(80))
    schnell.kalibrieren(len(KALIBRIERSATZ), 3.0)     # schnell geschrieben

    assert len(schnell.naechster_abschnitt()) > len(langsam.naechster_abschnitt())


def test_langsamer_macht_abschnitte_kuerzer_schneller_laenger():
    d = Diktierer()
    d.beginnen(_volltext(120))
    d.kalibrieren(len(KALIBRIERSATZ), 8.0)
    normal = len(d.naechster_abschnitt())

    d.langsamer()
    kurz = len(d.wiederholen())
    assert kurz < normal

    d.schneller(); d.schneller()
    lang = len(d.wiederholen())
    assert lang > kurz


def test_wiederholen_gibt_denselben_abschnitt():
    d = Diktierer()
    d.beginnen(_volltext(40))
    d.kalibrieren(len(KALIBRIERSATZ), 8.0)
    erst = d.naechster_abschnitt()
    nochmal = d.wiederholen()
    assert erst == nochmal
    # Danach geht es normal weiter (kein Steckenbleiben).
    weiter = d.naechster_abschnitt()
    assert weiter and weiter != erst


def test_kalibrierung_wird_geklammert():
    d = Diktierer()
    # Absurd schnell (0 Sekunden) darf nicht in Unendlich muenden.
    cps = d.kalibrieren(len(KALIBRIERSATZ), 0.0)
    assert 0.4 <= cps <= 8.0
    assert d.kalibriert is True


def test_leerer_text_ist_sofort_fertig():
    d = Diktierer()
    d.beginnen("")
    assert d.fertig is True
    assert d.naechster_abschnitt() is None
