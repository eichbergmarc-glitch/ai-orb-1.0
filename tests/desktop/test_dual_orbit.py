"""Tests der zwei Kugeln.

Der Benutzer wollte zwei Kugeln, die einander umkreisen - "aber nicht
immer in der gleichen Reihenfolge, sondern immer unterschiedlich".

Die Falle dabei ist der Zufall. Er ist das Naheliegende und das Falsche:
Er sieht nicht nach Unvorhersehbarkeit aus, sondern nach Zittern. Jedes
Bild springt die Bahn ein Stueck, es entsteht kein Zusammenhang, und was
man sieht, ist Rauschen.

Gefuehrt wird die Bewegung deshalb von einem Lorenz-System - vollkommen
deterministisch, und trotzdem kehrt es nie in denselben Zustand zurueck.
Die Tests rechnen das nach: dass es nicht davonlaeuft (sonst waere die
Animation nach einer Minute weg), dass es sich nicht wiederholt (sonst
waere der ganze Aufwand umsonst), und dass ein Ruckler die Bahn nicht
kippen laesst.
"""

from __future__ import annotations

import math
import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "desktop" / "renderer" / "dual_orbit.ts"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def _zahl(name: str) -> float:
    treffer = re.search(rf"const {name} = ([0-9.]+)", _text())
    assert treffer is not None, f"{name} nicht gefunden"
    return float(treffer.group(1))


def _lorenz(schritte: int, h: float = 0.004):
    """Rechnet das System nach - mit denselben Werten wie im Modul."""

    sigma, rho, beta = _zahl("SIGMA"), _zahl("RHO"), 8.0 / 3.0
    x, y, z = 0.9, 1.2, 22.0
    bahn = []
    for _ in range(schritte):
        dx = sigma * (y - x)
        dy = x * (rho - z) - y
        dz = x * y - beta * z
        x += dx * h
        y += dy * h
        z += dz * h
        bahn.append((x, y, z))
    return bahn


# --- Das System, das die Bahn fuehrt ------------------------------------------------


def test_die_datei_ist_da():
    assert QUELLE.is_file()


def test_die_bahn_laeuft_nicht_davon():
    """Sonst waere die Animation nach einer Minute aus dem Bild."""

    bahn = _lorenz(20000)
    for x, y, z in bahn[-500:]:
        assert abs(x) < 60 and abs(y) < 80 and 0 < z < 90, (x, y, z)


def test_die_bahn_wiederholt_sich_nicht():
    """Der ganze Grund, warum es ein Lorenz-System ist und kein Kreis.

    Der erste Versuch dieses Tests prueft die falsche Eigenschaft. Er
    verlangte, dass die Bahn dem Ausgangspunkt nie wieder nahe kommt - und
    das tut sie sehr wohl. Der Attraktor ist dicht; Beinahe-Wiederkehr ist
    normal und kein Mangel.

    Entscheidend ist, was DANACH geschieht. Bei einem Kreis liefe die Bahn
    von einem nahen Punkt aus wieder denselben Weg. Hier laufen zwei
    beliebig nahe Startpunkte auseinander, bis sie nichts mehr miteinander
    zu tun haben - das ist die empfindliche Abhaengigkeit von den
    Anfangsbedingungen, und sie ist der Grund, warum sich die Animation
    nie wiederholt.

    Geprueft wird also: Ein Unterschied von einem Millionstel waechst auf
    die Groesse des ganzen Attraktors.
    """

    sigma, rho, beta = _zahl("SIGMA"), _zahl("RHO"), 8.0 / 3.0
    h = 0.004

    def lauf(start, schritte):
        x, y, z = start
        for _ in range(schritte):
            dx = sigma * (y - x)
            dy = x * (rho - z) - y
            dz = x * y - beta * z
            x += dx * h
            y += dy * h
            z += dz * h
        return (x, y, z)

    a = (0.9, 1.2, 22.0)
    b = (0.9 + 1e-6, 1.2, 22.0)

    anfangs = math.dist(a, b)
    assert anfangs < 1e-5

    spaeter = math.dist(lauf(a, 8000), lauf(b, 8000))
    assert spaeter > 1.0, (
        f"zwei fast gleiche Startpunkte bleiben zusammen (Abstand "
        f"{spaeter:.4f}) - die Bahn ist nicht chaotisch, sondern periodisch"
    )


def test_das_system_wechselt_seine_fluegel():
    """Die Spruenge sind das, was man als 'jetzt macht es etwas anderes' sieht."""

    bahn = _lorenz(20000)
    wechsel = 0
    vorzeichen = 1 if bahn[0][0] > 0 else -1
    for x, _, _ in bahn:
        neu = 1 if x > 0 else -1
        if neu != vorzeichen and abs(x) > 2:
            wechsel += 1
            vorzeichen = neu
    assert wechsel >= 3, f"nur {wechsel} Fluegelwechsel - die Bahn ist zu brav"


def test_der_zeitschritt_ist_nach_oben_begrenzt():
    """Bei einem chaotischen System heisst ein grober Schritt nicht 'etwas
    ungenau', sondern 'etwas voellig anderes' - und bei einem sehr grossen
    laeuft die Bahn davon."""

    text = _text()
    assert "Math.min(Math.abs(dt), 0.05)" in text, "ein Ruckler kippt die Bahn"
    assert "schritte = 8" in text, "es wird nicht in Teilschritten gerechnet"


def test_es_wird_kein_zufall_im_lauf_benutzt():
    """Zufall sieht aus wie Zittern, nicht wie Unvorhersehbarkeit."""

    text = _text()
    assert "Math.random" not in text, "im Modul wird gewuerfelt"
    # Der eigene Wuerfel ist nur fuer den Aufbau da.
    lauf = text[text.index("public update("):]
    assert "wuerfel(" not in lauf, "im Lauf wird gewuerfelt"


# --- Was man sieht -------------------------------------------------------------------


def test_es_sind_zwei_kugeln_aus_punkten_und_keine_flaechen():
    """Eine Flaeche waere ein Ball; eine Wolke lebt."""

    text = _text()
    assert _zahl("JE_KUGEL") >= 100
    assert "PointsMaterial" in text
    assert "SphereGeometry" not in text


def test_die_schweife_zeigen_die_bahn_und_nicht_nur_die_bewegung():
    """Der Benutzer wollte sie laenger sehen.

    Ein Glied je Bild: Bei 60 Bildern in der Sekunde sind 120 Glieder zwei
    Sekunden Bahn. Mit einer halben Sekunde sieht man, DASS sich etwas
    bewegt; erst mit zwei sieht man, WIE.
    """

    assert _zahl("SCHWEIF") >= 90, "die Schweife sind zu kurz fuer eine Bahn"


def test_der_schweif_verglimmt_nicht_geradlinig():
    """Linear verteilt liegt in der Mitte noch die halbe Helligkeit, und
    das Ganze wird zu einem Band, das die Kugel verdeckt."""

    text = _text()
    assert "u0 * u0" in text and "u1 * u1" in text, "der Schweif verglimmt linear"


def test_es_gibt_einen_nebel_ringsum():
    assert _zahl("NEBEL") >= 200
    assert "nebelSetzen" in _text()


def test_der_nebel_hat_keine_kante():
    """Ein Nebel mit einem sichtbaren Rand ist eine Scheibe."""

    assert "dichte = Math.exp(" in _text(), "der Nebel verblasst nicht nach aussen"


def test_der_nebel_ist_einfarbig():
    """Vorher mischte jeder Fleck zwischen den Farben der beiden Kugeln.

    Das ergab einen bunten Schleier, in dem die Kugeln untergingen: Traegt
    die Umgebung dieselben Farben wie das, was darin leuchten soll, hebt
    sich nichts mehr ab.
    """

    text = _text()
    # Der Ton wird EINMAL je Bild gesetzt, nicht je Fleck.
    nebel = text[text.index("private nebelSetzen("):]
    nebel = nebel[: nebel.index("public setQuality(")]
    assert nebel.count("setHSL") == 1, "der Nebel bekommt mehr als eine Farbe"


def test_der_nebel_liegt_auch_dort_wo_die_kugeln_sind():
    """Sonst staenden sie VOR einer Wolke statt darin."""

    text = _text()
    assert "Math.sqrt(wuerfel()) * 1.05" in text, (
        "der Nebel bildet einen Ring statt ein Volumen"
    )


def test_die_kugeln_schimmern():
    """Eine Kugel, deren Punkte alle gleich hell sind, ist eine Flaeche."""

    assert "const flimmern" in _text(), "die Kugeln flimmern nicht"


def test_die_bewegung_hat_traegheit():
    """Der Lorenz-Zustand springt schnell.

    Nimmt man ihn unmittelbar als Achse, klappt die Bahnebene in wenigen
    Bildern um - das sieht aus wie ein Schnitt, nicht wie eine Bewegung.
    Mit Traegheit dazwischen bleibt die Unvorhersehbarkeit, aber sie
    erreicht das Bild als Schwung.
    """

    text = _text()
    assert "zielAchse" in text, "die Achse folgt der Bahn ohne Traegheit"
    assert "Math.exp(-delta *" in text, (
        "die Annaeherung haengt nicht an delta - auf einem schnellen "
        "Rechner bewegte sich alles anders als auf einem langsamen"
    )


def test_die_farben_wandern_und_gehen_ineinander_ueber():
    """Der Moment, auf den man wartet: wenn die beiden sich naehern."""

    text = _text()
    assert "const naehe = Math.exp(" in text
    assert "naehe * 0.28" in text, "die Farben mischen sich beim Naehern nicht"


# --- Groesse und Vertraeglichkeit -----------------------------------------------------


def test_alles_bleibt_in_der_groesse_des_orb():
    """Die bestehende Aura kreist bis 1.40."""

    assert _zahl("HARTE_DECKE") <= 1.40
    # Und die Decke wird auf beides angewendet, Kugeln wie Nebel.
    assert _text().count("HARTE_DECKE") >= 3


def test_kein_eigener_shader():
    """Eigene Shader sind auf diesem Rechner nachweislich nicht angekommen."""

    text = _text()
    assert "ShaderMaterial" not in text
    for standard in ("PointsMaterial", "LineBasicMaterial"):
        assert standard in text, standard


def test_die_kugeln_liegen_nur_noch_bereit():
    """Zurzeit zeichnet das Nervengeflecht - die Kugeln stehen daneben.

    Geloescht sind sie nicht, und das mit Absicht: Der Benutzer hat sich
    durch mehrere Darstellungen gearbeitet (Ring, Wirbel, Wuerfel, Kugeln,
    Geflecht) und mehrfach eine frueher verworfene wieder gewollt. Ein
    geloeschtes Modul muesste dafuer neu geschrieben werden; ein
    daneben liegendes ist ein Import weit entfernt.

    Was dieser Test sichert, ist nur: Es darf immer NUR EINES eingebunden
    sein. Zwei Animationen im selben Fenster ergeben Matsch, und weil
    beide additiv zeichnen, sieht man nicht, dass es zwei sind - man sieht
    nur, dass es haesslich ist.
    """

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    eingebunden = [
        name
        for name in ("DualOrbit", "NeonCube", "NeuralCore", "NeonRing",
                     "EnergyVortex", "NeuralFluid", "ZweiPunkte")
        if f"new {name}(" in orb
    ]
    assert eingebunden == ["ZweiPunkte"], (
        f"Eingebunden ist: {eingebunden or 'nichts'} - erwartet genau "
        "['ZweiPunkte']."
    )


def test_alle_gerufenen_methoden_gibt_es():
    """Der haeufigste Weg, wie so etwas still bricht.

    Geprueft wird gegen das Modul, das der Orb WIRKLICH benutzt - sonst
    sichert der Test eine Schnittstelle ab, die niemand mehr aufruft.
    """

    verzeichnis = get_project_root() / "desktop" / "renderer"
    orb = (verzeichnis / "orb.ts").read_text(encoding="utf-8")
    aktiv = (verzeichnis / "zwei_punkte.ts").read_text(encoding="utf-8")
    gerufen = set(re.findall(r"neon\??\.([a-zA-Z]+)\s*\(", orb))
    vorhanden = set(re.findall(r"public ([a-zA-Z]+)\s*\(", aktiv))
    fehlend = gerufen - vorhanden
    assert not fehlend, f"orb.ts ruft, was es nicht gibt: {sorted(fehlend)}"
