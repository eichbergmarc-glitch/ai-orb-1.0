"""Tests dafür, dass der Orb seine eigene Animation verändern kann.

Der Benutzer will künftig nicht mehr Werte von Hand ändern, sondern es dem
Orb sagen: „mach die Punkte grösser", „die Fäden länger", „grün und gelb".
Und für Grösseres soll der Orb den Code selbst umschreiben.

Geprüft wird das, was still kaputtgehen kann:
  - dass gesprochene Wünsche richtig gedeutet werden,
  - dass die config.yaml dabei ihre KOMMENTARE behält (sie erklären jeden
    Wert – ein yaml-Dump würde sie wegwerfen),
  - dass Unsinn abgefangen wird, statt die Animation zu zerbröseln,
  - dass ein Wunsch, der KEINE Werteänderung ist, auf den Code-Weg
    geleitet wird und nicht still im Nichts endet.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from backend.animation import config_schreiber
from backend.animation.wunsch_deuter import deute


# --- Die Deutung -------------------------------------------------------------------


def test_groesser_und_kleiner():
    assert deute("mach die punkte grösser").erkannt
    d = deute("mach alles viel kleiner")
    assert d.erkannt
    # "viel" verstärkt: der Faktor liegt unter 1 und deutlich unter dem
    # von "etwas kleiner".
    a = d.aenderungen[0]
    assert a.anwenden(1.0) < 0.8


def test_die_richtung_stimmt():
    """'grösser' darf nicht kleiner machen und umgekehrt."""

    groesser = deute("die punkte deutlich grösser").aenderungen[0]
    kleiner = deute("die punkte deutlich kleiner").aenderungen[0]
    assert groesser.anwenden(1.0) > 1.0
    assert kleiner.anwenden(1.0) < 1.0


def test_faeden_tempo_abstand_helligkeit():
    assert deute("die fäden länger").aenderungen[0].schluessel == "schweif_laenge"
    assert deute("mach es schneller").aenderungen[0].schluessel == "tempo"
    assert deute("ruhiger bitte").aenderungen[0].anwenden(1.0) < 1.0
    assert deute("die punkte weiter auseinander").aenderungen[0].schluessel == "abstand"
    assert deute("heller").aenderungen[0].schluessel == "helligkeit"
    assert deute("dunkler").aenderungen[0].anwenden(1.0) < 1.0


def test_farben_werden_erkannt():
    d = deute("mach sie grün und gelb")
    schluessel = {a.schluessel for a in d.aenderungen}
    assert schluessel == {"farbe_a", "farbe_b"}
    werte = sorted(a.zielwert for a in d.aenderungen)
    # grün 0.33, gelb 0.15
    assert werte == [0.15, 0.33]


def test_eine_farbe_geht_an_den_ferneren_punkt():
    # aktuell: a=1.0 (rot), b=0.62 (blau). "grün" (0.33) ist beiden fern,
    # dem roten (1.0) ferner -> farbe_a.
    d = deute("mach einen grün", aktuell={"farbe_a": 1.0, "farbe_b": 0.62})
    assert d.aenderungen[0].schluessel == "farbe_a"


def test_ein_strukturwunsch_ist_kein_wertewunsch():
    """Der Fall, der auf den Code-Weg gehört."""

    d = deute("lass sie wie ein herzschlag pulsieren")
    assert not d.erkannt
    assert d.unklar


def test_grenzen_verhindern_unsinn():
    """'kleiner', zehnmal gesagt, darf den Punkt nicht auf null schrumpfen."""

    from backend.animation.wunsch_deuter import _GRENZEN

    wert = 1.0
    for _ in range(10):
        a = deute("viel kleiner", aktuell={"scale": wert}).aenderungen[0]
        wert = a.anwenden(wert)
    lo, _hi = _GRENZEN["scale"]
    assert wert >= lo


# --- Der Config-Schreiber ----------------------------------------------------------


def _config(tmp_path) -> Path:
    ziel = tmp_path / "config.yaml"
    from backend.utils.paths import get_project_root

    shutil.copy(get_project_root() / "config.yaml", ziel)
    return ziel


def test_werte_werden_geschrieben_und_gelesen(tmp_path):
    pfad = _config(tmp_path)
    ok, fehlend = config_schreiber.schreibe_animationswerte(
        pfad, {"scale": 0.8, "abstand": 0.9, "schweif_laenge": 40}
    )
    assert ok and not fehlend
    nach = config_schreiber.lies_animationswerte(pfad)
    assert nach["scale"] == 0.8
    assert nach["abstand"] == 0.9
    assert nach["schweif_laenge"] == 40


def test_die_kommentare_ueberleben(tmp_path):
    """Ein yaml-Dump würde sie wegwerfen – das ist der ganze Grund für den
    zeilengenauen Schreiber."""

    pfad = _config(tmp_path)
    vorher = pfad.read_text(encoding="utf-8")
    kommentarzeilen = [z for z in vorher.splitlines() if z.strip().startswith("#")]
    config_schreiber.schreibe_animationswerte(pfad, {"scale": 0.42})
    nachher = pfad.read_text(encoding="utf-8")
    nachher_kommentare = [z for z in nachher.splitlines() if z.strip().startswith("#")]
    assert len(nachher_kommentare) == len(kommentarzeilen), (
        "Kommentare gingen verloren – der Schreiber hat die Datei umgebaut."
    )


def test_die_datei_bleibt_gueltiges_yaml(tmp_path):
    import yaml

    pfad = _config(tmp_path)
    config_schreiber.schreibe_animationswerte(
        pfad, {"scale": 0.5, "farbe_a": 0.33, "tempo": 1.5}
    )
    daten = yaml.safe_load(pfad.read_text(encoding="utf-8"))
    assert daten["orb"]["scale"] == 0.5
    assert daten["orb"]["animation"]["farbe_a"] == 0.33


def test_nur_der_animationsblock_wird_angefasst(tmp_path):
    """Ein 'tempo' oder 'abstand' anderswo darf nicht mitgeändert werden."""

    pfad = _config(tmp_path)
    vorher = pfad.read_text(encoding="utf-8")
    config_schreiber.schreibe_animationswerte(pfad, {"abstand": 1.1})
    nachher = pfad.read_text(encoding="utf-8")
    # Genau EINE Zeile hat sich geändert.
    verschieden = [
        (a, b) for a, b in zip(vorher.splitlines(), nachher.splitlines()) if a != b
    ]
    assert len(verschieden) == 1, f"Mehr als eine Zeile geändert: {verschieden}"
    assert "abstand" in verschieden[0][1]


# --- Das Werkzeug als Ganzes -------------------------------------------------------


class _Bus:
    def __init__(self) -> None:
        self.ereignisse: list[str] = []

    async def publish(self, name, payload=None) -> None:
        self.ereignisse.append(name)


def test_das_werkzeug_aendert_und_laedt_neu(tmp_path):
    from backend.tools.animation_tools import NEU_LADEN, AnimationAnpassenTool

    pfad = _config(tmp_path)
    bus = _Bus()
    werkzeug = AnimationAnpassenTool(bus, pfad)

    ergebnis = asyncio.run(werkzeug.execute({"wunsch": "mach die fäden viel länger"}))
    assert ergebnis.ok
    assert NEU_LADEN in bus.ereignisse, "Die Oberfläche wurde nicht zum Neuladen angestossen."
    # Der Wert steht wirklich höher in der config.
    assert config_schreiber.lies_animationswerte(pfad)["schweif_laenge"] > 26


def test_das_werkzeug_leitet_strukturwuensche_auf_den_code_weg(tmp_path):
    from backend.tools.animation_tools import AnimationAnpassenTool

    bus = _Bus()
    werkzeug = AnimationAnpassenTool(bus, _config(tmp_path))
    ergebnis = asyncio.run(
        werkzeug.execute({"wunsch": "lass die punkte wie ein herzschlag schlagen"})
    )
    # Erfolg, aber mit dem Hinweis auf den Code-Weg – und OHNE Neuladen.
    assert ergebnis.ok
    assert "eigenen_code_aendern" in ergebnis.output
    assert not bus.ereignisse, "Es wurde neu geladen, obwohl nichts geändert wurde."


def test_die_animationswerkzeuge_sind_angemeldet():
    """Ein Werkzeug, das niemand registriert, kann der Orb nicht rufen."""

    from backend.utils.paths import get_project_root

    runtime = (get_project_root() / "backend" / "runtime.py").read_text(encoding="utf-8")
    assert "build_animation_tools" in runtime
