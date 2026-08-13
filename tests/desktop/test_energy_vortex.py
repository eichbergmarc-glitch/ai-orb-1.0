"""Tests des Energiewirbels.

Nach mehreren Anlaeufen die Lehre vorweg: Der Vorgaenger war eine KURVE,
die verformt wurde, und das Vorbild ist ein STURM aus einzelnen Lichtspuren.
Keine noch so organische Verformung einer Kurve wird zu einem Sturm - es
war die falsche Bauart und nicht die falsche Einstellung. Der erste Test
haelt deshalb die Bauart fest.

Der zweite Teil prueft, was am Atem haengt. Er soll ein geschlossener
Sechs-Sekunden-Bogen sein: zusammengezogen, ausgedehnt, genau zurueck. Das
sieht man beim Zusehen schlecht, weil ein Sprung nur alle sechs Sekunden
vorkommt und dann leicht fuer ein Ruckeln gehalten wird - also wird es
gerechnet.
"""

from __future__ import annotations

import math
import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "desktop" / "renderer" / "energy_vortex.ts"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def _zahl(name: str) -> float:
    treffer = re.search(rf"const {name} = ([0-9.]+)", _text())
    assert treffer is not None, f"{name} nicht gefunden"
    return float(treffer.group(1))


# --- Die Bauart ------------------------------------------------------------------


def test_die_datei_ist_da():
    assert QUELLE.is_file()


def test_es_ist_ein_sturm_und_keine_kurve():
    """Die Lehre aus drei vergeblichen Anlaeufen."""

    text = _text()
    assert _zahl("BAHNEN") >= 400, "zu wenige Bahnen fuer einen Sturm"
    # Jede Bahn zieht eine Spur - ein Punkt zeigt, WO etwas ist, ein
    # Strich, WOHIN es geht.
    assert _zahl("GLIEDER") >= 2, "die Bahnen ziehen keine Spur"
    assert "LineSegments" in text


def test_der_ring_entsteht_aus_der_haeufung():
    """Nicht gezeichnet, sondern das, was die Bahnen zusammen bilden."""

    text = _text()
    assert "BAND_MITTE" in text and "BAND_BREITE" in text
    mitte, breite = _zahl("BAND_MITTE"), _zahl("BAND_BREITE")
    assert _zahl("R_INNEN") < mitte < _zahl("R_AUSSEN")
    assert breite < mitte, "das Band ist so breit, dass kein Ring entsteht"


def test_die_bahnen_werden_nach_innen_gezogen():
    """Ohne Sog kreisen sie bloss - mit ihm wird etwas hineingezogen."""

    assert "const sog" in _text(), "es gibt keinen Sog nach innen"
    assert "gebaeren" in _text(), "die Bahnen entstehen aussen nicht neu"


# --- Was "organisch" heisst -------------------------------------------------------


def test_das_stroemungsfeld_haengt_am_ort_und_nicht_an_der_nummer():
    """Der Unterschied zwischen Rauch und Konfetti.

    Ein Versatz je Teilchen laesst jedes fuer sich zappeln. Ein Feld ueber
    dem ORT verzieht benachbarte Bahnen gemeinsam - und nur das liest das
    Auge als Stroemung.
    """

    text = _text()
    block = text[text.index("private stroemung("): text.index("private ortAuf(")]
    for achse in ("x *", "y *", "z *"):
        assert achse in block.replace("this.stroem.", ""), (
            f"das Feld haengt nicht von {achse[0]} ab"
        )
    assert "[i]" not in block, "das Feld haengt an der Nummer des Teilchens"


def test_die_bahnen_sind_keine_kreise_mit_versatz():
    """Ein verschobener Kreis bleibt sichtbar ein Kreis.

    Der Radius muss ENTLANG der Bahn schwingen - also ueber dem Winkel.
    Daraus wird ein Weg, der sich windet, statt einer Linie, die zittert.
    """

    text = _text()
    assert "const ranke" in text, "die Bahnen winden sich nicht"
    block = text[text.index("const ranke"): text.index("const wall")]
    assert "w * 2.0" in block and "w * 3.0" in block, (
        "die Ranke schwingt nicht ueber dem Winkel"
    )


def test_der_schlag_laeuft_um_den_wirbel():
    """Ueberall gleichzeitig waere ein Wirbel, der als Ganzes waechst."""

    text = _text()
    assert "this.takt - this.winkel[i]" in text, "der Schlag laeuft nicht um"
    # Und er greift in die BEWEGUNG ein, nicht nur in die Helligkeit.
    assert "schub * 0.30" in text, "der Schlag bewegt nichts"


# --- Der Atem ---------------------------------------------------------------------


def test_der_atem_dauert_sechs_sekunden():
    assert _zahl("ATEM_DAUER") == 6.0


def test_der_atem_kommt_genau_zurueck():
    """Nach sechs Sekunden derselbe Zustand - nicht ein aehnlicher."""

    def atem(t: float) -> float:
        return 0.5 - 0.5 * math.cos((t / 6.0) * math.tau)

    for start in (0.0, 0.37, 1.5, 2.9, 4.25):
        assert abs(atem(start) - atem(start + 6.0)) < 1e-9, start

    assert atem(0.0) < 0.01, "beginnt nicht zusammengezogen"
    assert atem(3.0) > 0.99, "ist nach der Haelfte nicht ausgedehnt"


def test_der_atem_laesst_den_ring_nicht_verschwinden():
    """Ein Ring, der verschwindet, ist kein Atmen mehr, sondern ein Blinken."""

    enge = _zahl("ATEM_ENGE")
    assert 0.35 <= enge <= 0.75, f"die Enge von {enge} ist kein Atmen"


def test_alle_drei_lagen_atmen_mit():
    """Sonst haetten Ring, Nebel und Kern nichts miteinander zu tun."""

    text = _text()
    assert text.count("this.weite") >= 3, "nicht alle Lagen haengen am Atem"


def test_der_takt_wird_mitgefuehrt_und_nicht_gerechnet():
    """Aus elapsed * tempo folgt ein Sprung bei jedem Zustandswechsel."""

    text = _text()
    assert "this.atemTakt = (this.atemTakt +" in text
    assert "delta * tempo) / ATEM_DAUER" in text


# --- Groesse und Vertraeglichkeit --------------------------------------------------


def test_der_wirbel_bleibt_in_der_groesse_des_orb():
    """Die bestehende Aura kreist bis 1.40 - darueber schneidet das Fenster ab.

    Geprueft wird die Decke und nicht eine Handrechnung ueber den
    schlimmsten Fall. Eine solche Rechnung wird bei jeder neuen Bewegung
    enger, bis sie die Animation einschnuert - die Decke gilt dagegen auch
    fuer alles, was spaeter noch dazukommt.
    """

    text = _text()
    assert "function gedeckelt" in text, "es gibt keine Decke"
    assert _zahl("HARTE_DECKE") <= 1.40, "die Decke liegt ausserhalb des Fensters"
    assert _zahl("WEICHE_DECKE") < _zahl("HARTE_DECKE")
    assert "gedeckelt(r * wall)" in text, "die Decke wird nicht angewendet"


def test_die_decke_kappt_nicht_sondern_drueckt():
    """Ein hartes Kappen ergaebe eine Kreiskante, an der sich alle Bahnen
    sammeln - und die faellt sofort auf."""

    weich, hart = _zahl("WEICHE_DECKE"), _zahl("HARTE_DECKE")

    def gedeckelt(r: float) -> float:
        if r <= weich:
            return r
        spiel = hart - weich
        return weich + spiel * (1.0 - math.exp(-(r - weich) / spiel))

    assert gedeckelt(0.8) == 0.8
    assert gedeckelt(1.2) < gedeckelt(1.6) < gedeckelt(2.2)
    assert gedeckelt(2.2) < hart
    assert gedeckelt(1e6) <= hart


def test_kein_eigener_shader():
    """Eigene Shader sind auf diesem Rechner nachweislich nicht angekommen."""

    text = _text()
    assert "ShaderMaterial" not in text
    for standard in ("LineBasicMaterial", "PointsMaterial"):
        assert standard in text, standard


def test_der_alte_wirbel_ist_nicht_zusaetzlich_eingebunden():
    """Der Energy-Orb darf nicht mit einem alten Renderer vermischt werden."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    assert 'from "./energy_vortex"' not in orb
    assert "new EnergyVortex()" not in orb


def test_alle_gerufenen_methoden_gibt_es():
    """Der haeufigste Weg, wie so etwas still bricht."""

    orb = (get_project_root() / "desktop" / "renderer" / "orb.ts").read_text(
        encoding="utf-8"
    )
    gerufen = set(re.findall(r"neon\??\.([a-zA-Z]+)\s*\(", orb))
    vorhanden = set(re.findall(r"public ([a-zA-Z]+)\s*\(", _text()))
    fehlend = gerufen - vorhanden
    assert not fehlend, f"orb.ts ruft, was es nicht gibt: {sorted(fehlend)}"
