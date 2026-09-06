"""Die Offlineabnahme - mit wirklich gesperrtem Netz, nicht mit Vorsatz.

Aufruf::

    python -m scripts.offline_abnahme
    python -m scripts.offline_abnahme --tests tests/backend/test_lehrer_schueler.py
    python -m scripts.offline_abnahme --auch-rueckschleife-sperren

Der Ablauf, und warum er in dieser Reihenfolge steht:

1. **Sperren.** ``backend.lernen.netzsperre`` ersetzt die Engpaesse des
   Betriebssystems, ueber die jeder Netzverkehr laeuft.
2. **Beweisen, VOR den Tests.** Ein echter Verbindungsversuch und eine
   echte Namensauflösung müssen beide mit ``NetzGesperrt`` scheitern. Ein
   gewöhnlicher Netzfehler zählt nicht - er käme auch von einem Rechner
   ohne Anschluss und würde eine untätige Sperre als Erfolg ausweisen.
3. **Tests im GLEICHEN Prozess.** ``pytest.main`` statt eines
   Unterprozesses: Ein Unterprozess erbt die Ersetzung nicht und liefe
   trotz aller Beteuerungen mit offenem Netz.
4. **Nochmals beweisen, NACH den Tests.** Ein Test, der die Sperre
   versehentlich zurücknimmt, würde sonst unbemerkt bleiben.
5. **Bericht.** Wer bestanden hat, wer nicht, und beide Beweise im
   Wortlaut - abgelegt unter ``logs/``.

Der Rückgabewert ist 0 nur dann, wenn beide Beweise standhielten UND kein
Test fehlschlug. Alles andere ist ein Fehlschlag, auch ein "die Tests
liefen ja durch" bei untätiger Sperre.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

WURZEL = Path(__file__).resolve().parent.parent
if str(WURZEL) not in sys.path:
    sys.path.insert(0, str(WURZEL))

from backend.lernen import netzsperre  # noqa: E402

#: Was offline bestehen muss. Bewusst benannt und nicht "alles": Ein
#: Testlauf, der Dinge einschliesst, die ohne Netz gar nicht laufen
#: koennen, waere kein Nachweis, sondern eine Ausrede.
STANDARDTESTS: tuple[str, ...] = (
    "tests/backend/test_lehrer_schueler.py",
    "tests/backend/test_blindbewertung.py",
    "tests/backend/test_messpfad_werkzeuge.py",
    "tests/backend/test_schattenpfad.py",
    "tests/backend/test_netzsperre.py",
    "tests/backend/test_paarvergleich.py",
    "tests/backend/test_bedingung_vier.py",
    "tests/backend/test_zahlenvergleich.py",
    "tests/backend/test_pfadaufloesung.py",
    "tests/backend/test_kalenderprobe.py",
)


def _beweise() -> dict[str, Any]:
    """Beide Beweise auf einmal - Verbindung und Namensdienst."""

    verbindung = netzsperre.beweis()
    namen = netzsperre.namensbeweis()
    return {
        "verbindung": verbindung,
        "namensdienst": namen,
        "gesperrt": bool(verbindung["gesperrt"] and namen["gesperrt"]),
    }


def abnahme(tests: list[str], *, rueckschleife_sperren: bool = False) -> dict[str, Any]:
    """Führt die Abnahme durch und gibt den Bericht zurück."""

    bericht: dict[str, Any] = {
        "zeitpunkt": time.time(),
        "tests": list(tests),
        "rueckschleife_gesperrt": rueckschleife_sperren,
        "sperre_vorher": {},
        "sperre_nachher": {},
        "pytest_rueckgabe": None,
        "bestanden": False,
        "grund": "",
    }

    netzsperre.sperren(loopback_erlaubt=not rueckschleife_sperren)
    bericht["sperre_vorher"] = _beweise()

    if not bericht["sperre_vorher"]["gesperrt"]:
        bericht["grund"] = (
            "Die Netzsperre liess sich nicht nachweisen. Es wurden KEINE "
            "Tests ausgefuehrt, weil ihr Ergebnis nichts belegen wuerde."
        )
        return bericht

    import pytest

    bericht["pytest_rueckgabe"] = int(
        pytest.main(["-q", "--no-header", "-p", "no:cacheprovider", *tests])
    )

    bericht["sperre_nachher"] = _beweise()

    if not bericht["sperre_nachher"]["gesperrt"]:
        bericht["grund"] = (
            "Die Sperre war nach dem Testlauf nicht mehr aktiv. Ein Test hat "
            "sie zurueckgenommen; der Lauf gilt damit als nicht offline."
        )
        return bericht

    if bericht["pytest_rueckgabe"] != 0:
        bericht["grund"] = (
            f"pytest endete mit {bericht['pytest_rueckgabe']}; siehe Ausgabe."
        )
        return bericht

    bericht["bestanden"] = True
    bericht["grund"] = "Sperre vor und nach dem Lauf nachgewiesen, alle Tests gruen."
    return bericht


def _hauptprogramm() -> int:
    zerleger = argparse.ArgumentParser(description="Offlineabnahme fuer AI-Orb")
    zerleger.add_argument(
        "--tests", nargs="*", default=list(STANDARDTESTS), help="Testpfade"
    )
    zerleger.add_argument(
        "--auch-rueckschleife-sperren",
        action="store_true",
        help="auch 127.0.0.1 sperren (dann laeuft kein lokales Modell mehr)",
    )
    zerleger.add_argument(
        "--bericht", default="", help="Pfad fuer den Bericht (Vorgabe: logs/)"
    )
    argumente = zerleger.parse_args()

    ergebnis = abnahme(
        list(argumente.tests),
        rueckschleife_sperren=argumente.auch_rueckschleife_sperren,
    )

    ziel = Path(argumente.bericht) if argumente.bericht else (
        WURZEL / "logs" / f"offline-abnahme-{time.strftime('%Y-%m-%d-%H%M%S')}.json"
    )
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(
            json.dumps(ergebnis, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as fehler:
        print(f"Der Bericht liess sich nicht ablegen: {fehler}")
    else:
        print(f"\nBericht: {ziel}")

    print(
        "\nNetzsperre vorher : "
        f"{ergebnis['sperre_vorher'].get('gesperrt')} "
        f"({ergebnis['sperre_vorher'].get('verbindung', {}).get('art')})"
    )
    print(
        "Netzsperre nachher: "
        f"{ergebnis['sperre_nachher'].get('gesperrt')} "
        f"({ergebnis['sperre_nachher'].get('verbindung', {}).get('art')})"
    )
    print(f"Ergebnis: {'BESTANDEN' if ergebnis['bestanden'] else 'NICHT BESTANDEN'}")
    print(f"Grund   : {ergebnis['grund']}")
    return 0 if ergebnis["bestanden"] else 1


if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    raise SystemExit(_hauptprogramm())
