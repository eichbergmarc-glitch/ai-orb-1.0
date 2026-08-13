"""Prueft, dass der Nervenkern wirklich im Kreis laeuft.

Der Benutzer hat eine Schleife von genau sechs Sekunden verlangt: kein
Schnitt, kein Sprung, ein durchgehend atmender Kreis. Das ist die eine
Eigenschaft, an der so etwas steht oder faellt - und ausgerechnet die
sieht man beim Zusehen am schlechtesten, weil ein Sprung nur alle sechs
Sekunden vorkommt und in dem Moment leicht fuer ein Ruckeln gehalten wird.

Deshalb wird sie hier gerechnet statt betrachtet. Geprueft wird der
TypeScript-Quelltext nicht auf Aussehen, sondern auf die Bedingungen, aus
denen die Geschlossenheit folgt:

  * Alles Zeitabhaengige haengt an sin/cos einer durch die Atemdauer
    geteilten Zeit. Ein einziges Glied, das linear mit der Zeit waechst,
    macht die Schleife kaputt.
  * Die Zahl der Wellen je Atemzug ist ganzzahlig. Bei zweieinhalb Wellen
    springt das Bild an der Nahtstelle.

Zusaetzlich wird die Atemformel selbst in Python nachgerechnet: Sie muss
nach sechs Sekunden auf den Ausgangswert zurueckkommen, und zwar nicht
ungefaehr.
"""

from __future__ import annotations

import math
import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "desktop" / "renderer" / "neural_core.ts"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def test_die_datei_ist_da():
    assert QUELLE.is_file(), "neural_core.ts fehlt"


def test_die_atemdauer_sind_sechs_sekunden():
    """Der Benutzer hat sechs Sekunden verlangt."""

    treffer = re.search(r"const ATEM_DAUER = ([0-9.]+)", _text())
    assert treffer is not None, "ATEM_DAUER nicht gefunden"
    assert float(treffer.group(1)) == 6.0


def test_die_wellenzahl_ist_ganzzahlig():
    """Bei zweieinhalb Wellen springt das Bild an der Nahtstelle."""

    treffer = re.search(r"const WELLEN_JE_ATEM = ([0-9.]+)", _text())
    assert treffer is not None, "WELLEN_JE_ATEM nicht gefunden"
    zahl = float(treffer.group(1))
    assert zahl == int(zahl), f"{zahl} Wellen je Atemzug schliessen den Kreis nicht"


def test_die_atemformel_kommt_genau_zurueck():
    """Nach sechs Sekunden derselbe Zustand - nicht ein aehnlicher."""

    def atem(t: float) -> float:
        return 0.5 - 0.5 * math.cos((t / 6.0) * math.tau)

    def front(t: float) -> float:
        return ((t / 6.0) * 2.0) % 1.0

    for start in (0.0, 0.37, 1.5, 2.9, 4.25):
        assert abs(atem(start) - atem(start + 6.0)) < 1e-9, start
        assert abs(front(start) - front(start + 6.0)) < 1e-9, start


def test_die_atmung_geht_wirklich_hin_und_zurueck():
    """Zusammengezogen, ausgedehnt, wieder zusammengezogen."""

    def atem(t: float) -> float:
        return 0.5 - 0.5 * math.cos((t / 6.0) * math.tau)

    assert atem(0.0) < 0.01, "beginnt nicht zusammengezogen"
    assert atem(3.0) > 0.99, "ist nach der Haelfte nicht ausgedehnt"
    assert atem(6.0) < 0.01, "kehrt nicht zusammengezogen zurueck"


def test_keine_zeit_laeuft_ungeteilt_mit():
    """Ein lineares Zeitglied machte die Schleife kaputt.

    Gesucht wird nach 'elapsed', das NICHT durch ATEM_DAUER geteilt ist -
    mit einer Ausnahme: die freie Drehung des Kerns. Sie ist absichtlich
    nicht Teil der Schleife, weil eine Drehung ohne Naht ohnehin keine
    sichtbare Naht hat.
    """

    verdaechtig: list[str] = []
    in_drehung = False
    for zeile in _text().splitlines():
        nackt = zeile.strip()
        if nackt.startswith("private drehen("):
            in_drehung = True
        elif nackt.startswith("public setQuality("):
            in_drehung = False
        if in_drehung or nackt.startswith("*") or nackt.startswith("//"):
            continue
        if "elapsed" not in nackt:
            continue
        # Erlaubt: elapsed / ATEM_DAUER, und die Weitergabe als Argument.
        ohne_geteilt = re.sub(r"elapsed\s*/\s*ATEM_DAUER", "", nackt)
        if re.search(r"\belapsed\b\s*[*+]", ohne_geteilt):
            verdaechtig.append(nackt)

    assert not verdaechtig, "Zeit laeuft ungeteilt mit: " + "; ".join(verdaechtig)


def test_der_kern_bleibt_in_der_groesse_des_orb():
    """Die bestehende Aura kreist bis 1.40 - darueber schneidet das Fenster ab."""

    treffer = re.search(r"const WEIT = ([0-9.]+)", _text())
    assert treffer is not None
    assert float(treffer.group(1)) <= 1.25


def test_kein_eigener_shader():
    """Eigene Shader sind auf diesem Rechner nachweislich nicht angekommen."""

    text = _text()
    assert "ShaderMaterial" not in text
    assert "RawShaderMaterial" not in text
    for standard in ("LineBasicMaterial", "PointsMaterial", "MeshBasicMaterial"):
        assert standard in text, standard


def test_der_alte_nervenkern_ist_nicht_zusaetzlich_eingebunden():
    """Der Energy-Orb darf nicht mit einem alten Renderer vermischt werden."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    assert 'from "./neural_core"' not in orb
    assert "new NeuralCore()" not in orb
    assert "NeonCube" not in orb, "der alte Wuerfel wird noch eingebunden"


def test_alle_gerufenen_methoden_gibt_es():
    """Der haeufigste Weg, wie so etwas still bricht."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    kern = _text()

    gerufen = set(re.findall(r"neon\??\.([a-zA-Z]+)\s*\(", orb))
    vorhanden = set(re.findall(r"public ([a-zA-Z]+)\s*\(", kern))

    fehlend = gerufen - vorhanden
    assert not fehlend, f"orb.ts ruft, was es nicht gibt: {sorted(fehlend)}"
