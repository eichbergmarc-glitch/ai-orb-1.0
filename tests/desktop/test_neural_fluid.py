"""Tests des Nervengeflechts.

Diese Datei prueft nicht, ob die Animation schoen ist - das kann kein
Test, und der Benutzer hat sie in der Vorschau abgenommen. Geprueft wird
das, was beim naechsten Umbau STILL kaputtgehen kann, ohne dass jemand
eine Fehlermeldung sieht.

Vier Dinge sind in diesem Modul genau von dieser Art:

1. **Die Verdrahtung.** Ein Renderer-Modul, das niemand einbindet, faellt
   nirgends auf: Es wird uebersetzt, gebuendelt, mitgeliefert - und
   gezeichnet wird der alte Aufbau. Genau das ist hier schon einmal
   passiert (die Fassung auf dem Rechner war 0.8.4, waehrend ich 0.9.0
   glaubte). Deshalb steht die Verdrahtung an erster Stelle.

2. **Eigene Shader.** three.js uebersetzt `ShaderMaterial` als GLSL ES
   1.00. Was dort nicht erlaubt ist, scheitert LAUTLOS - es wird nichts
   gezeichnet, ohne Fehlerbild. Ein gerechneter Kern ist auf dem Rechner
   des Benutzers aus genau diesem Grund nie erschienen. Dieses Modul darf
   deshalb keinen eigenen Shader benutzen.

3. **Die harte Decke.** Das Orb-Fenster schneidet bei etwa 1.34 ab. Ein
   Nebel, der darueber hinausreicht, bekommt an dieser Stelle eine Kante -
   und die Kante ist genau das, wegen dem die Kugelhuelle weichen musste.

4. **Die Schleife.** Alles Feldgetriebene haengt an ganzzahligen
   Vielfachen von OM. Nur dadurch kehrt die Verformung nach T Sekunden
   EXAKT zurueck. Schreibt jemand spaeter eine 2.5 statt einer 2, schliesst
   die Schleife nicht mehr - und ein Sprung im Bild faellt jedes Mal auf,
   ohne dass irgendetwas abstuerzt.
"""

from __future__ import annotations

import re

from backend.utils.paths import get_project_root

QUELLE = get_project_root() / "desktop" / "renderer" / "neural_fluid.ts"
ORB = get_project_root() / "desktop" / "renderer" / "orb.ts"


def _text() -> str:
    return QUELLE.read_text(encoding="utf-8")


def _zahl(name: str) -> float:
    treffer = re.search(rf"const {name} = ([0-9.]+)", _text())
    assert treffer is not None, f"{name} nicht gefunden"
    return float(treffer.group(1))


def _koerper(name: str) -> str:
    """Liefert den Rumpf einer Methode - grob, aber ausreichend."""

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


def test_das_geflecht_liegt_nur_noch_bereit():
    """Der Benutzer hat die zwei Punkte gewaehlt; das Geflecht bleibt liegen.

    Liegen und nicht geloescht - er hat sich durch mehrere Darstellungen
    gearbeitet und mehrfach eine fruehere wiedergewollt. Aktiv sein darf
    aber nur EINE: Zwei additive Animationen im selben Fenster ergeben
    Matsch, und man saehe nicht einmal, dass es zwei sind.
    """

    orb = ORB.read_text(encoding="utf-8")
    assert "new NeuralFluid()" not in orb, (
        "Das Geflecht ist noch eingebunden - zusammen mit den zwei Punkten "
        "ergibt das Matsch."
    )
    assert QUELLE.is_file(), "Das Modul selbst muss liegen bleiben."


def test_der_vorgaenger_ist_vollstaendig_abgeloest():
    """Zwei Animationen zugleich waeren Matsch - und niemand saehe warum."""

    orb = ORB.read_text(encoding="utf-8")
    assert "DualOrbit" not in orb, "Der alte Aufbau haengt noch im Orb."
    assert "dual_orbit" not in orb


def test_die_schnittstelle_passt_zu_den_aufrufstellen():
    """`orb.ts` ruft diese sechs Dinge auf. Fehlt eines, bricht es dort."""

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
    """Ein Shader, der nicht uebersetzt wird, zeichnet nichts. Ohne Fehler."""

    text = _text()
    assert "ShaderMaterial" not in text
    assert "RawShaderMaterial" not in text
    assert "vertexShader" not in text


def test_nur_erprobte_materialien():
    text = _text()
    assert "THREE.LineBasicMaterial" in text
    assert "THREE.PointsMaterial" in text


# --- Die harte Decke ----------------------------------------------------------------


def test_der_nebel_bleibt_im_fenster():
    """Der aeusserste Fleck darf nicht am Fensterrand abgeschnitten werden."""

    kern = _zahl("KERN_R")
    decke = _zahl("HARTE_DECKE")
    weiten = [float(w) for w in re.findall(r"weite: ([0-9.]+)", _text())]
    assert weiten, "Keine Nebellagen gefunden."
    assert kern * max(weiten) <= decke, (
        f"Der Nebel reicht bis {kern * max(weiten):.2f}, "
        f"das Fenster schneidet bei {decke:.2f} ab."
    )


def test_am_fensterrand_ist_der_nebel_praktisch_weg():
    """Sonst sieht man dort eine Kante - und darum ging der ganze Umbau."""

    kern = _zahl("KERN_R")
    decke = _zahl("HARTE_DECKE")
    # Die Dichtefunktion aus dem Modul: exp(-(weg/1.8)^2), weg in KERN_R.
    treffer = re.search(r"Math\.pow\(weg / ([0-9.]+), 2\)", _text())
    assert treffer is not None, "Die Dichtefunktion wurde umgeschrieben."
    breite = float(treffer.group(1))
    weg = decke / kern
    dichte = 2.718281828459045 ** (-((weg / breite) ** 2))
    assert dichte < 0.1, (
        f"Am Fensterrand hat der Nebel noch {dichte:.0%} Dichte - "
        "dort entsteht eine sichtbare Kante."
    )


def test_es_gibt_eine_deckelung_im_lauf():
    """Drift und Atmen koennen einen Fleck ueber die Decke hinaustragen."""

    assert "HARTE_DECKE / abstand" in _text(), (
        "Die Flecken werden nicht auf die Decke zurueckgeholt."
    )


# --- Die Schleife -------------------------------------------------------------------


def test_die_stroemungsfelder_kehren_exakt_zurueck():
    """Jede Frequenz muss ein ganzzahliges Vielfaches von OM sein.

    Das ist der Unterschied zwischen einer Schleife, die schliesst, und
    einer, die "ungefaehr" schliesst. Letztere hat einen Sprung, und den
    sieht man bei jedem Durchlauf an derselben Stelle.

    Ausgenommen ist bewusst das Leuchten in der Mitte: Sein Tempo haengt
    am Zustand (ruhig, denkend, sprechend) und nicht an der Schleife. Es
    KANN nicht loop-fest sein, weil sich der Zustand aendert, wann er
    will - und weil es ein formloser Schein ist, faellt das nicht auf.
    """

    for name in ("stroemung", "kernStroemung"):
        rumpf = _koerper(f"private {name}")
        faktoren = re.findall(r"tt \* OM \* ([0-9.]+)", rumpf)
        assert faktoren, f"In {name} steht kein OM-Vielfaches."
        for f in faktoren:
            assert float(f) == int(float(f)), (
                f"In {name} steht der Faktor {f} - kein ganzzahliges "
                "Vielfaches von OM. Die Schleife schliesst dann nicht."
            )


def test_die_uhr_laeuft_in_der_grundperiode_um():
    assert "% T" in _text(), "Die eigene Uhr laeuft nicht in T um."


# --- Was je Bild nicht passieren darf ------------------------------------------------


def test_im_lauf_entsteht_kein_neues_objekt():
    """Bei 60 Bildern je Sekunde waere jedes `new` Arbeit fuer den Sammler."""

    rumpf = _koerper("public update")
    assert "new THREE." not in rumpf, (
        "In update() wird ein Objekt erzeugt - das kostet je Bild."
    )
    assert "new Array" not in rumpf


def test_die_traegheit_haengt_an_der_zeit_und_nicht_am_bild():
    """Sonst bewegt sich alles auf einem schnellen Rechner anders."""

    rumpf = _koerper("public update")
    assert "Math.exp(-dt *" in rumpf, (
        "Die Annaeherung ist nicht zeitgefuehrt - auf einem 144-Hz-Bildschirm "
        "liefe der Zustandswechsel dann mehr als doppelt so schnell."
    )


# --- Das Netz, das das Bild traegt ---------------------------------------------------


def test_das_netz_ist_verbunden_und_nicht_bloss_bestreut():
    """Ein Knoten ohne Nachbarn leitet nichts weiter."""

    text = _text()
    treffer = re.search(r"const INNEN_K = (\d+)", text)
    assert treffer is not None
    assert int(treffer.group(1)) >= 2, (
        "Mit einem Nachbarn je Knoten entstehen Paare, kein Netz - "
        "und Licht, das an einem Knoten ankommt, kann nirgends weiterlaufen."
    )


def test_das_licht_laeuft_wirklich_ueber_die_knoten_weiter():
    """Das ist der Unterschied zu einem bloss beleuchteten Geflecht."""

    rumpf = _koerper("public update")
    assert "innenGlut[f.b] = 1.0" in rumpf and "innenGlut[f.a] = 1.0" in rumpf, (
        "Ankommende Lichtpunkte regen die Knoten nicht an."
    )


def test_die_verbindungen_sind_gebogen():
    """Ein Netz aus Geraden sieht aus wie ein Drahtmodell."""

    assert "bogen" in _text()
    assert "FASER_G" in _text(), "Ohne Zwischenglieder gibt es keine Kruemmung."


# --- Kein Kreis mehr ----------------------------------------------------------------


def test_die_huelle_bleibt_aus():
    """Der Einwand, der viermal kam - und viermal derselbe war.

    Der bestehende Orb hat eine Kugelhuelle mit Fresnel-Rand. Sie zeichnet
    genau den hell umrandeten Kreis, den der Benutzer nicht wollte. Dass
    das Nervengeflecht selbst keinen Umriss hat, nuetzt nichts, wenn
    daneben eine Kugel steht.
    """

    orb = ORB.read_text(encoding="utf-8")
    assert "this.gehaeuseSichtbar = false;" in orb, (
        "Huelle, Aura und Nebel des alten Aufbaus sind nicht abgeschaltet - "
        "dann liegt wieder ein Kreis um das Geflecht."
    )


def test_die_leistungsstufe_holt_die_huelle_nicht_zurueck():
    """`setQuality` regelt den AUFWAND, nicht, was zum Bild gehoert.

    Frueher stand dort `this.aura.visible = level >= 1`. Waere das so
    geblieben, waere der Kreis beim ersten Wechsel der Leistungsstufe
    zurueckgewesen - also genau dann, wenn niemand hinsieht.
    """

    orb = ORB.read_text(encoding="utf-8")
    for teil in ("this.aura.visible", "this.smoke.visible", "this.shell.visible"):
        stellen = [z for z in orb.splitlines() if teil in z and "=" in z]
        assert stellen, f"{teil} wird nirgends gesetzt."
        for zeile in stellen:
            assert "gehaeuseSichtbar" in zeile, (
                f"Diese Zeile schaltet am Gehaeuse vorbei: {zeile.strip()}"
            )


# --- Der Fehler, der die erste Fassung im Orb unsichtbar machte ----------------------


def test_die_punktgroessen_folgen_dem_massstab():
    """Die Eigenheit von three.js, die man nicht vermutet.

    `PointsMaterial.size` wird von der Objektskalierung NICHT erfasst. Der
    Vertex-Shader setzt `gl_PointSize = size` und teilt danach nur noch
    durch die Tiefe; die Modellmatrix wirkt auf die POSITION der Punkte,
    nicht auf ihre Groesse.

    Im Orb steht `orb.scale: 0.20`. Die Positionen schrumpften damit auf
    ein Sechstel, die weichen Flecken behielten ihre volle Groesse - jeder
    Nebelfleck war so gross wie die ganze Wolke. Zu sehen war ein Schmier
    ohne Struktur. Nichts stuerzte ab, nichts stand im Protokoll.

    Deshalb muss JEDE Zuweisung an `material.size` den Massstab tragen.
    """

    rumpf = _koerper("public update")
    zuweisungen = [
        z.strip()
        for z in rumpf.splitlines()
        if re.search(r"\.size\s*=", z)
    ]
    assert zuweisungen, "Keine Punktgroesse wird je Bild gesetzt."
    for zeile in zuweisungen:
        assert "mass" in zeile, (
            "Diese Groesse folgt der Skalierung des Orb nicht: " + zeile
        )


def test_der_massstab_wird_wirklich_ausgelesen():
    text = _text()
    assert "getWorldScale" in text, (
        "Der Massstab wird nicht aus der Gruppe gelesen - ein fest "
        "eingetragener Wert waere beim naechsten `orb.scale` wieder falsch."
    )


def test_das_netz_passt_zur_groesse_des_orb():
    """Zweiundneunzig Knoten auf 27 Bildpunkten sind kein Netz, sondern ein Fleck.

    Der Orb ist bei `orb.scale: 0.20` etwa 63 Bildpunkte gross. Was in der
    Vorschau auf 600 Punkten filigran wirkte, muss hier gruendlich duenner
    sein - sonst sieht man Struktur, wo keine mehr aufloesbar ist.
    """

    treffer = re.search(r"const INNEN_N = (\d+)", _text())
    assert treffer is not None
    assert int(treffer.group(1)) <= 48, (
        f"{treffer.group(1)} Knoten sind fuer einen 63 Punkte grossen Orb "
        "zu viele - die Leitungen verschmelzen zu einer Flaeche."
    )
