"""Tests für den Patchschmied - vor allem für die Auswahl der Ziele.

Warum gerade hier Tests stehen
------------------------------
Der Patchschmied hat lange nichts gefunden, ohne sich zu beschweren. Vier
Ursachen, jede einzeln harmlos aussehend, zusammen aber lähmend:

1. Der Durchlauf durch den Quelltext ging erst durch ``runtime`` und
   ``node_modules`` und warf sie hinterher weg - Minuten statt Sekunden.
2. Die Tabu-Liste galt in jeder Tiefe. ``audio`` war gemeint als der
   Ordner mit den Klangproben oben im Projekt, traf aber auch
   ``backend/audio`` - und damit den häufigsten Fehler überhaupt.
3. Die Pfade in den Protokollen stehen in Windows-Schreibweise; wer sie
   nicht als Weg liest, findet die Datei nie wieder.
4. Gleichnamige Methoden in einer Datei belegten alle drei Nachtpatches.

Ein Werkzeug, das nichts findet und nichts sagt, sieht aus wie eines, das
nichts zu tun hat. Diese Tests halten den Unterschied fest.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from werkzeug import patchschmied as ps


@pytest.fixture()
def projekt(tmp_path):
    """Ein Miniaturprojekt mit genau den Ordnern, die früher gestört haben."""

    wurzel = tmp_path / "AI-Orb"
    (wurzel / "backend" / "audio").mkdir(parents=True)
    (wurzel / "backend" / "audio" / "audio_capture.py").write_text(
        "def start(self):\n    return 1\n", encoding="utf-8")

    # Beigepacktes, das nie eigener Quelltext ist.
    for tabu in ("runtime/python/Lib", "node_modules/paket",
                 "games/spiel/.tools", "AI-Orb-iPad/backend",
                 "tests/backend", "__pycache__"):
        ordner = wurzel / tabu
        ordner.mkdir(parents=True, exist_ok=True)
        (ordner / "fremd.py").write_text("def x():\n    pass\n", encoding="utf-8")

    (wurzel / "logs").mkdir(exist_ok=True)
    return wurzel


# ============================================================ Der Durchlauf
def test_durchlauf_laesst_beigepacktes_aus(projekt):
    gefunden = {p.name for p in ps.python_dateien(projekt)}
    assert gefunden == {"audio_capture.py"}


def test_versteckte_ordner_werden_nie_betreten(projekt):
    wege = [str(p) for p in ps.python_dateien(projekt)]
    assert not any(".tools" in w for w in wege)


def test_kopie_des_projekts_zaehlt_nicht_mit(projekt):
    wege = [str(p) for p in ps.python_dateien(projekt)]
    assert not any("AI-Orb-iPad" in w for w in wege)


# ================================================== Tabu nur, wo es gilt
def test_backend_audio_ist_kein_tabu(projekt):
    """Der Regressionsfall: vierzehn Mikrofonfehler, lautlos übergangen."""

    pfad = r"C:\Users\info\AI-Orb\backend\audio\audio_capture.py"
    assert ps._gehoert_dazu(Path(pfad), projekt) is True


@pytest.mark.parametrize("fremd", [
    r"C:\Users\info\AI-Orb\runtime\python\Lib\site-packages\sounddevice.py",
    r"C:\Users\info\AI-Orb\tests\backend\test_irgendwas.py",
    r"C:\Users\info\AI-Orb\AI-Orb-iPad\backend\api\server.py",
    r"urllib\request.py",
])
def test_fremdes_gehoert_nicht_dazu(projekt, fremd):
    assert ps._gehoert_dazu(Path(fremd), projekt) is False


def test_teilpfad_nimmt_den_innersten_treffer(projekt):
    """Liegt eine Kopie im Projekt, gilt der innerste Projektname."""

    rel = ps._teilpfad(r"C:\Alt\AI-Orb\zwischen\AI-Orb\backend\x.py", projekt)
    assert rel == Path("backend/x.py")


# ====================================================== Ziele aus Protokollen
def _protokoll_schreiben(projekt: Path, name: str, text: str, alter: float = 0.0):
    datei = projekt / "logs" / name
    datei.write_text(text, encoding="utf-8")
    if alter:
        zeit = datei.stat().st_mtime - alter
        os.utime(datei, (zeit, zeit))
    return datei


RUECKVERFOLGUNG = (
    "Traceback (most recent call last):\n"
    '  File "C:\\Users\\info\\AI-Orb\\backend\\audio\\audio_capture.py", line 91, in start\n'
    "    self._stream.start()\n"
    '  File "C:\\Users\\info\\AI-Orb\\runtime\\python\\Lib\\site-packages\\sounddevice.py", line 12, in _check\n'
    "    raise PortAudioError(msg)\n"
    "PortAudioError: Error opening InputStream\n"
)


def test_ziel_kommt_aus_dem_innersten_eigenen_rahmen(projekt):
    _protokoll_schreiben(projekt, "system.log", RUECKVERFOLGUNG * 3)
    ziele = ps.ziele_aus_protokollen(projekt)
    assert [(z.datei.name, z.funktion) for z in ziele] == [("audio_capture.py", "start")]
    assert ziele[0].gewicht == 3


def test_ziel_liegt_im_untersuchten_projekt(projekt):
    """Der protokollierte Pfad kann von einer alten Installation stammen."""

    _protokoll_schreiben(projekt, "system.log",
                         RUECKVERFOLGUNG.replace(r"C:\Users\info", r"D:\Alt"))
    ziele = ps.ziele_aus_protokollen(projekt)
    assert ziele and ziele[0].datei == projekt / "backend" / "audio" / "audio_capture.py"


def test_ohne_rueckverfolgung_kein_ziel(projekt):
    _protokoll_schreiben(projekt, "system.log", "ERROR  Irgendwas ging schief\n")
    assert ps.ziele_aus_protokollen(projekt) == []


def test_juengste_protokolle_zaehlen_nicht_die_alphabetisch_letzten(projekt):
    """Sieben Protokolle, das mit dem Fund heißt 'a...' und ist das neueste."""

    _protokoll_schreiben(projekt, "aktuell.log", RUECKVERFOLGUNG)
    for nummer in range(6):
        _protokoll_schreiben(projekt, f"zzz-{nummer}.log", "nichts\n",
                             alter=3600 * (nummer + 1))
    assert ps.ziele_aus_protokollen(projekt), "das neueste Protokoll wurde übergangen"


# ========================================================== Ziele aus Code
def test_je_datei_nur_ein_ziel(tmp_path):
    """Drei Klassen, drei Methoden 'execute' - trotzdem ein Vorschlag."""

    wurzel = tmp_path / "AI-Orb"
    (wurzel / "backend").mkdir(parents=True)
    klassen = "".join(
        f"class K{i}:\n    def execute(self):\n"
        + "".join(f"        w{j} = {j}\n" for j in range(10))
        + "        return w0\n\n"
        for i in range(3)
    )
    (wurzel / "backend" / "grafik_tools.py").write_text(klassen, encoding="utf-8")

    ziele = ps.ziele_aus_code(wurzel, hoechstens=10)
    dateien = [z.datei for z in ziele if z.art == "dokumentation"]
    assert len(dateien) == len(set(dateien)) == 1


def test_unlesbare_datei_bricht_den_durchlauf_nicht_ab(tmp_path):
    wurzel = tmp_path / "AI-Orb"
    (wurzel / "backend").mkdir(parents=True)
    (wurzel / "backend" / "kaputt.py").write_bytes(b"\xa4\xa4\xa4 def x():\n")
    (wurzel / "backend" / "gut.py").write_text(
        "def machwas(a, b):\n" + "".join(f"    z{i} = {i}\n" for i in range(8))
        + "    return a + b\n", encoding="utf-8")

    ziele = ps.ziele_aus_code(wurzel, hoechstens=5)
    assert [z.funktion for z in ziele] == ["machwas"]
