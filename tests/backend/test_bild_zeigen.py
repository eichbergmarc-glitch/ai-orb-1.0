"""Bilder werden GEZEIGT, nicht als Pfad vorgelesen.

Der Beleg steht im Protokoll vom 19.08.2026, 15:14 Uhr: Der Orb hatte
zwei Golderz-Fotos heruntergeladen und sagte dann woertlich - "Die
Bilder kann ich dir nicht direkt oeffnen lassen, weil ich keine Anzeige
fuer Bilddateien implementiert habe." Er hatte recht: bild_suchen und
bild_erzeugen legten Dateien ab, aber kein Werkzeug zeigte sie an. Der
Benutzer meldete es am 20.08. als seit langem ungeloest.

Diese Tests halten fest, dass es das Werkzeug jetzt gibt, dass es die
Bilder wirklich in eine anzeigbare Schau einbettet und den Browser
oeffnet - und dass die Bildwerkzeuge in ihren Antworten auf das Zeigen
HINWEISEN, damit das Sprachmodell nie wieder glaubt, es gebe keines.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import backend.tools.grafik_tools as grafik_tools
from backend.tools.grafik_tools import ZeigeBilderTool

#: Ein winziges, echtes PNG (1x1, rot) - genug fuer das Einbetten.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg=="
)


def _bild(pfad: Path) -> Path:
    pfad.write_bytes(_PNG)
    return pfad


def _zeigen(monkeypatch, tmp_path, **argumente):
    geoeffnet: list[Path] = []
    monkeypatch.setattr(grafik_tools, "_im_browser_oeffnen", lambda p: (geoeffnet.append(p), True)[1])
    monkeypatch.setattr(grafik_tools, "_ablage", lambda unterordner: tmp_path / unterordner)
    ergebnis = asyncio.run(ZeigeBilderTool().execute(argumente))
    return ergebnis, geoeffnet


def test_das_werkzeug_ist_registriert():
    from backend.tools.grafik_tools import build_grafik_tools

    class _Sicherheit:  # das Diagrammwerkzeug will eine SecurityEngine sehen
        pass

    namen = {w.name for w in build_grafik_tools(_Sicherheit())}
    assert "bild_zeigen" in namen


def test_bilder_werden_eingebettet_und_im_browser_geoeffnet(tmp_path, monkeypatch):
    eins = _bild(tmp_path / "gold_metal_in_quartz_01.png")
    zwei = _bild(tmp_path / "gold_metal_in_quartz_02.png")

    ergebnis, geoeffnet = _zeigen(
        monkeypatch, tmp_path,
        pfade=f"{eins}\n{zwei}",
        titel="Golderz",
        unterschrift="Wikimedia Commons, CC BY-SA",
    )

    assert ergebnis.ok, ergebnis.error
    assert len(geoeffnet) == 1
    schau = geoeffnet[0].read_text(encoding="utf-8")
    # Eingebettet, nicht verlinkt: Die Schau muss auch dann noch stehen,
    # wenn die Bilddateien spaeter aufgeraeumt werden.
    assert schau.count("data:image") == 2
    assert "Golderz" in schau
    assert "Wikimedia Commons" in schau
    assert "2 Bild(er)" in ergebnis.output


def test_fehlende_dateien_werden_ehrlich_benannt(tmp_path, monkeypatch):
    ergebnis, geoeffnet = _zeigen(
        monkeypatch, tmp_path, pfade=str(tmp_path / "gibt-es-nicht.jpg")
    )

    assert not ergebnis.ok
    assert "gibt-es-nicht.jpg" in ergebnis.error
    assert not geoeffnet


def test_ein_fehlendes_bild_verhindert_die_uebrigen_nicht(tmp_path, monkeypatch):
    da = _bild(tmp_path / "da.png")
    ergebnis, geoeffnet = _zeigen(
        monkeypatch, tmp_path, pfade=f"{da}; {tmp_path / 'weg.png'}"
    )

    assert ergebnis.ok
    assert len(geoeffnet) == 1
    assert "Nicht gefunden" in ergebnis.output
    assert "weg.png" in ergebnis.output


def test_die_bildwerkzeuge_weisen_auf_das_zeigen_hin():
    """Das Sprachmodell erfaehrt vom Zeigen dort, wo es die Pfade bekommt.

    Genau daran scheiterte es am 19.08.: Das Werkzeug haette gebaut sein
    koennen, wie es wollte - solange das Modell nach bild_suchen nicht
    erfuhr, dass es die Bilder auch ZEIGEN kann, las es Pfade vor.
    """

    quelle = Path("backend/tools/grafik_tools.py").read_text(encoding="utf-8")
    suche = quelle.index("class SucheBildTool")
    erzeuge = quelle.index("class ErzeugeBildTool")
    zeige = quelle.index("class ZeigeBilderTool")
    assert "bild_zeigen" in quelle[suche:erzeuge], (
        "bild_suchen verschweigt das Zeigen"
    )
    assert "bild_zeigen" in quelle[erzeuge:zeige], (
        "bild_erzeugen verschweigt das Zeigen"
    )
