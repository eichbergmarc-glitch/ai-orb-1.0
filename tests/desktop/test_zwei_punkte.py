"""Tests der zwei Punkte.

Der Benutzer hat diese Darstellung beschrieben, in der Vorschau in drei
Runden abgestimmt und abgenommen ("das ist perfekt"). Die Tests sichern
nicht die Schoenheit - die ist abgenommen -, sondern das, was beim
naechsten Umbau STILL kaputtgehen kann. Die Liste stammt aus den Fehlern,
die bei den Vorgaengern wirklich passiert sind:

1. Ein Modul, das niemand einbindet, faellt nirgends auf (Fassung 0.8.4
   lief, waehrend ich 0.9.0 glaubte).
2. Ein eigener Shader scheitert lautlos (der gerechnete Kern erschien nie).
3. ``PointsMaterial.size`` folgt der Gruppenskalierung nicht (das Geflecht
   war im Orb ein Schmier, weil jeder Fleck so gross blieb wie die Wolke).
"""

from __future__ import annotations

import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "desktop" / "renderer" / "zwei_punkte.ts"
ORB = get_project_root() / "desktop" / "renderer" / "orb.ts"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def _koerper(name: str) -> str:
    text = _text()
    start = text.index(f"{name}(")
    tiefe = 0
    begonnen = False
    for i in range(text.index("{", start), len(text)):
        if text[i] == "{":
            tiefe += 1
            begonnen = True
        elif text[i] == "}":
            tiefe -= 1
            if begonnen and tiefe == 0:
                return text[start : i + 1]
    raise AssertionError(f"Rumpf von {name} nicht gefunden")


# --- Die Verdrahtung ----------------------------------------------------------------


def test_die_datei_ist_da():
    assert QUELLE.is_file()


def test_der_orb_benutzt_es_wirklich():
    orb = ORB.read_text(encoding="utf-8")
    assert 'from "./zwei_punkte"' in orb, "Das Modul wird nicht eingebunden."
    assert "new ZweiPunkte(" in orb, "Es wird nie erzeugt."


def test_die_schnittstelle_passt_zu_den_aufrufstellen():
    text = _text()
    for name in (
        "public setColors(",
        "public setVoiceLevel(",
        "public restartIntro(",
        "public update(",
        "public setQuality(",
        "public dispose(",
        "public readonly group",
    ):
        assert name in text, f"{name} fehlt - orb.ts ruft es aber auf."


# --- Keine eigenen Shader -----------------------------------------------------------


def test_kein_eigener_shader():
    text = _text()
    assert "ShaderMaterial" not in text
    assert "vertexShader" not in text


# --- Der Massstab -------------------------------------------------------------------


def test_die_punktgroessen_folgen_dem_massstab():
    """Der Fehler, der das Geflecht im Orb unsichtbar machte."""

    rumpf = _koerper("public update")
    # Bis zum Semikolon lesen, nicht bis zum Zeilenende: Der Formatierer
    # bricht laengere Zuweisungen um, und ein Test, der nur die erste
    # Zeile sieht, schluege genau an der korrekten Stelle fehl.
    zuweisungen = re.findall(r"[\w.\]]+\.size\s*=[^;]+;", rumpf)
    assert zuweisungen, "Keine Punktgroesse wird je Bild gesetzt."
    for stueck in zuweisungen:
        assert "mass" in stueck, (
            "Diese Groesse folgt der Skalierung des Orb nicht: "
            + " ".join(stueck.split())
        )


def test_der_massstab_wird_ausgelesen():
    assert "getWorldScale" in _text()


# --- Was der Benutzer verlangt hat --------------------------------------------------


def test_rot_und_blau_bleiben_rot_und_blau():
    """"sie sollen jeweils rot und blau sein" - das Theme darf das nicht
    verschieben. Uebernommen wird nur die Leuchtstaerke."""

    text = _text()
    assert "TON_ROT = 1.0" in text, (
        "Rot muss als 1.0 stehen, nicht als 0.0 - sonst mischt der Weg von "
        "Blau nach Rot ueber GRUEN statt ueber Violett."
    )
    assert "TON_BLAU = 0.62" in text
    rumpf = _koerper("public setColors")
    assert "this.staerke = staerke" in rumpf
    assert "zustandTon" not in rumpf, "Die Toene haengen wieder am Theme."


def test_das_mischen_geschieht_je_fleck():
    """Sonst ist es ein Farbwechsel auf Knopfdruck statt Nebel."""

    rumpf = _koerper("public update")
    assert "neigung" in rumpf, "Die Mischneigung je Fleck fehlt."
    assert "schliere" in rumpf


def test_der_drehsinn_kommt_aus_dem_lorenz_system():
    """"die richtung wechseln, dynamisch" - Zufall saehe nach Zittern aus."""

    text = _text()
    for stueck in ("28.0", "8.0 / 3.0", "Math.tanh"):
        assert stueck in text, f"{stueck} fehlt - das Lorenz-System wurde entfernt."


def test_die_annaeherung_ist_zeitgefuehrt():
    """Sonst laeuft alles auf einem 144-Hz-Bildschirm doppelt so schnell."""

    rumpf = _koerper("public update")
    assert "Math.exp(-dt" in rumpf


def test_im_lauf_entsteht_kein_neues_objekt():
    rumpf = _koerper("public update")
    assert "new THREE." not in rumpf, "In update() wird je Bild ein Objekt erzeugt."


def test_verschmolzen_ziehen_die_schweife_nicht():
    """Ein stehender Nebel zieht keine Spur."""

    assert "(1 - misch)" in _koerper("public update")
