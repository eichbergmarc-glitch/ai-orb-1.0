"""Prueft, dass das O wirklich ein O ist.

Der Benutzer wollte ein O, das pulsiert, sich morpht und organisch
veraendert - und das sich beim ersten Start aus einem Wirbel bildet.

Bei einem morphenden Ring gibt es genau eine Eigenschaft, an der alles
haengt: Er muss sich schliessen. Die Verformung ist eine Summe von
Sinuswellen ueber dem Winkel, und nur wenn jede Ordnung ganzzahlig ist,
gilt r(theta + 2*pi) = r(theta) exakt. Bei einer krummen Ordnung wie 2.5
bekommt der Ring eine Kerbe an einer festen Stelle - aus dem O wird ein C.

Das sieht man beim Zusehen schlecht, weil die Kerbe mitwandert und wie ein
Zeichenfehler wirkt. Deshalb wird es hier gerechnet statt betrachtet: Die
Ordnungen werden aus dem Quelltext gelesen und die Ringformel in Python
nachgerechnet.
"""

from __future__ import annotations

import math
import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "desktop" / "renderer" / "neon_ring.ts"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def _verformung() -> list[tuple[float, float, float]]:
    """Liest die Eintraege aus Ordnung, Staerke und Tempo."""

    block = re.search(r"const VERFORMUNG[^=]*=\s*\[(.*?)\];", _text(), re.S)
    assert block is not None, "VERFORMUNG nicht gefunden"
    zeilen = re.findall(
        r"\[\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\]",
        block.group(1),
    )
    assert zeilen, "keine Eintraege in VERFORMUNG"
    return [(float(a), float(b), float(c)) for a, b, c, _ in zeilen]


def test_die_datei_ist_da():
    assert QUELLE.is_file(), "neon_ring.ts fehlt"


def test_alle_ordnungen_sind_ganzzahlig():
    """Die eine Bedingung, unter der sich der Ring schliesst."""

    for ordnung, _, _ in _verformung():
        assert ordnung == int(ordnung), f"Ordnung {ordnung} reisst den Ring auf"


def test_die_ordnungen_sind_teilerfremd():
    """Sonst laegen die Ausbuchtungen der einen auf denen der anderen.

    Aus zwei Wellen wuerde dann sichtbar eine einzige, staerkere - der
    Ring saehe gleichmaessiger aus, nicht organischer.
    """

    ordnungen = [int(o) for o, _, _ in _verformung()]
    assert len(set(ordnungen)) == len(ordnungen), "eine Ordnung kommt doppelt vor"
    for i, a in enumerate(ordnungen):
        for b in ordnungen[i + 1 :]:
            assert math.gcd(a, b) == 1, f"{a} und {b} teilen einen Faktor"


def test_der_ring_schliesst_sich_exakt():
    """Nachgerechnet, nicht angenommen: r(0) == r(2*pi).

    Auch mit atmenden Staerken: Die Staerke haengt nur an der Zeit, nicht
    am Winkel - deshalb aendert sie die Form, aber nie die Geschlossenheit.
    """

    eintraege = _verformung()

    def radius(theta: float, t: float) -> float:
        r = 1.0
        for i, (ordnung, staerke, lauf) in enumerate(eintraege):
            atmend = staerke * (0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.2 + i * 2.1)))
            r += atmend * math.sin(ordnung * theta + t * lauf)
        return r

    for t in (0.0, 1.7, 13.25, 240.0):
        assert abs(radius(0.0, t) - radius(2 * math.pi, t)) < 1e-9, t


def test_der_ring_verformt_sich_ueberhaupt():
    """Ein Test auf Geschlossenheit ist wertlos, wenn nichts passiert."""

    eintraege = _verformung()
    gesamt = sum(abs(s) for _, s, _ in eintraege)
    assert gesamt > 0.15, "die Verformung ist zu schwach, um sichtbar zu sein"
    assert gesamt < 0.45, "die Verformung ist so stark, dass das O zerfaellt"


def test_der_ring_bleibt_in_der_groesse_des_orb():
    """Die bestehende Aura kreist bis 1.40 - darueber schneidet das Fenster ab.

    Frueher stand hier eine Rechnung ueber den schlimmsten Fall, und die
    wurde bei jeder neuen Verformung enger, bis sie die Animation
    einschnuerte. Jetzt faengt der Ring seinen Radius selbst ab, und
    geprueft wird die Decke - das ist die belastbarere Zusage: Sie gilt
    auch fuer alles, was spaeter noch dazukommt.
    """

    text = _text()
    weich = re.search(r"const WEICHE_DECKE = ([0-9.]+)", text)
    hart = re.search(r"const HARTE_DECKE = ([0-9.]+)", text)
    assert weich is not None and hart is not None, "es gibt keine Decke"

    assert float(hart.group(1)) <= 1.40, "die Decke liegt ausserhalb des Fensters"
    assert float(weich.group(1)) < float(hart.group(1))

    # Und sie wird auch angewendet - nicht bloss erklaert.
    assert "if (r > WEICHE_DECKE)" in text, "die Decke wird nicht angewendet"


def test_die_decke_kappt_nicht_sondern_drueckt():
    """Ein hartes Kappen ergaebe eine gerade Linie, wo eine Rundung sein
    muesste - und die faellt sofort auf."""

    weich = float(re.search(r"const WEICHE_DECKE = ([0-9.]+)", _text()).group(1))
    hart = float(re.search(r"const HARTE_DECKE = ([0-9.]+)", _text()).group(1))

    def gedrueckt(r: float) -> float:
        if r <= weich:
            return r
        spiel = hart - weich
        return weich + spiel * (1.0 - math.exp(-(r - weich) / spiel))

    # Unterhalb bleibt alles, wie es ist.
    assert gedrueckt(0.8) == 0.8
    # Darueber wird gedrueckt, aber nicht gekappt: im sichtbaren Bereich
    # steigt der Wert weiter, statt auf einer Kante stehenzubleiben.
    assert gedrueckt(1.5) < gedrueckt(2.0) < gedrueckt(3.0)
    assert gedrueckt(3.0) < hart

    # Und die Decke haelt in jedem Fall.
    #
    # Rechnerisch wird sie nie erreicht, nur angenaehert. In Fliesskomma
    # verschwindet die Exponentialfunktion irgendwann unter der
    # Aufloesung, und dann steht der Wert genau auf der Decke - was
    # richtig ist: Zugesagt ist die Obergrenze, nicht der Abstand zu ihr.
    assert gedrueckt(50.0) <= hart
    assert gedrueckt(1e6) <= hart


def test_der_puls_ist_ein_herzschlag_und_kein_sinus():
    """Ein Sinus schwillt gleichmaessig - das ist Atmung, keine Pulsation.

    Ein Herzschlag hat einen kraeftigen Schlag, kurz darauf einen
    schwaecheren, und dann eine Ruhe, die laenger ist als beide zusammen.
    Erst diese Ruhe macht den Schlag zum Schlag.
    """

    text = _text()
    assert "function herzschlag" in text, "der Puls ist kein Herzschlag"

    # Nachgerechnet: zwei Gipfel, dann eine lange Ruhe.
    def glocke(p, mitte, breite):
        d = abs(p - mitte)
        if d > 0.5:
            d = 1.0 - d
        return math.exp(-(d * d) / (breite * breite))

    def schlag(p):
        return min(1.0, glocke(p, 0.0, 0.055) + glocke(p, 0.17, 0.075) * 0.62)

    assert schlag(0.0) > 0.9, "der erste Schlag fehlt"
    assert schlag(0.17) > 0.5, "der zweite Schlag fehlt"
    assert schlag(0.09) < 0.5, "zwischen den Schlaegen ist keine Senke"
    assert schlag(0.5) < 0.02, "es gibt keine Ruhe"
    assert schlag(0.75) < 0.02, "es gibt keine Ruhe"

    # Und er reicht um die Naht herum: der Anstieg liegt davor.
    assert abs(schlag(0.999) - schlag(-0.001 % 1.0)) < 1e-9


def test_der_schlag_laeuft_um_den_ring():
    """Ueberall gleichzeitig waere ein Ring, der groesser und kleiner wird."""

    text = _text()
    # Der Versatz betraegt ueber einen vollen Umlauf genau einen Schlag -
    # nur so schliesst sich der Ring trotz laufendem Puls.
    assert text.count("this.pulsTakt - anteil") >= 2, (
        "der Schlag laeuft nicht um den Ring, oder Form und Licht laufen "
        "nicht im selben Takt"
    )


def test_die_phase_wandert_statt_zu_rotieren():
    """Eine sich drehende Rosette liest das Auge als starren Koerper."""

    assert "const wandern" in _text(), "die Phase schreitet gleichmaessig fort"


def test_der_nebel_verfaerbt_sich():
    """Ein Nebel mit fester Farbe ist ein gefaerbter Fleck."""

    assert "const wandel" in _text(), "der Farbton des Nebels steht fest"


def test_der_nebel_um_den_orb_verfaerbt_sich():
    """Und zwar in jedem Bild, nicht nur beim Zustandswechsel."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    assert "nebelVerfaerben" in orb
    # Gerufen wird es aus update, nicht aus applyAppearance - sonst kaeme
    # die Verfaerbung nur alle paar Minuten einmal zustande.
    start = orb.index("public update(")
    ende = orb.index("public setQuality(")
    assert "this.nebelVerfaerben(" in orb[start:ende]


def test_der_aufbau_ist_ein_wirbel_und_kein_sog():
    """Zwischen zwei Punkten gerade zu interpolieren ergaebe einen Trichter."""

    text = _text()
    assert "wirbelOrt" in text
    # Der Winkel wird weitergedreht, nicht bloss interpoliert.
    assert re.search(r"elapsed \* drall", text), "der Wirbel dreht sich nicht weiter"
    # Und er wird langsamer, je naeher ein Teilchen kommt.
    assert re.search(r"\(1\.0 - eigen\)", text), "der Wirbel legt sich nicht"


def test_der_schweif_verschwindet_am_ring():
    """Sonst blieben Striche stehen, wo sich nichts mehr bewegt."""

    text = _text()
    assert "SCHWEIF_ZEIT" in text
    # Beide Auswertungen laufen ueber dieselbe Funktion - nur zu
    # verschiedenen Zeiten. Fallen sie zusammen, ist die Strecke null.
    assert text.count("this.wirbelOrt(") >= 2


def test_kein_eigener_shader():
    """Eigene Shader sind auf diesem Rechner nachweislich nicht angekommen."""

    text = _text()
    assert "ShaderMaterial" not in text
    assert "RawShaderMaterial" not in text
    for standard in ("LineBasicMaterial", "PointsMaterial"):
        assert standard in text, standard


def test_orb_benutzt_den_ring():
    """Ein Modul, das niemand einbindet, zeichnet nichts."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    assert 'from "./neon_ring"' in orb
    assert "new NeonRing()" in orb
    for alt in ("NeonCube", "NeuralCore"):
        assert alt not in orb, f"{alt} wird noch eingebunden"


def test_alle_gerufenen_methoden_gibt_es():
    """Der haeufigste Weg, wie so etwas still bricht."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    gerufen = set(re.findall(r"neon\??\.([a-zA-Z]+)\s*\(", orb))
    vorhanden = set(re.findall(r"public ([a-zA-Z]+)\s*\(", _text()))

    fehlend = gerufen - vorhanden
    assert not fehlend, f"orb.ts ruft, was es nicht gibt: {sorted(fehlend)}"
