"""Gibt der Websuche ein Zeitbudget - gegen den Haenger bei der Suche.

Was das Problem war
-------------------
``backend/tools/web_tools.py`` versuchte die Zugaenge zur Websuche
NACHEINANDER, jeden mit eigener Frist, und die Fristen addierten sich:
zwei Suchmaschinen mal zwei Anfragevarianten mal zwoelf Sekunden sind
achtundvierzig Sekunden. Dazu kamen bis zu acht Sekunden fuer die offenen
Quellen. Und ``mehrquellensuche`` ruft ``search_web`` einmal je Haus auf -
bei acht Haeusern und vier gleichzeitigen Anfragen also zweimal
hintereinander. Aus einer Suche wurden so ueber zwei Minuten Stille.

Dazu kam eine Stelle, an der die Suche nicht nur langsam war, sondern
wirklich haengen bleiben konnte: ``response.read()`` ohne Groessenangabe.
Das Zeitlimit von ``urlopen`` gilt je Datenpaket, nicht fuer die ganze
Uebertragung. Eine Gegenstelle, die langsam tropft statt zu schweigen,
haelt den Faden damit beliebig lange fest.

Was dieses Skript aendert
-------------------------
Es ersetzt in ``web_tools.py`` genau zwei Funktionen:

``_fetch``      bekommt eine Frist fuer die GESAMTE Uebertragung und eine
                Obergrenze fuer ihre Groesse.
``search_web``  bekommt ein Gesamtbudget und fragt die Suchmaschinen
                gleichzeitig statt nacheinander. Die Rangfolge der
                Maschinen bleibt erhalten - ausgewertet wird nach ihr, nicht
                danach, wer zuerst fertig war.

Alles andere bleibt unberuehrt. Weil ``search_web`` unter allen anderen
Suchwegen liegt - ``mehrquellensuche``, ``favoriten_suche``, die
Suchmasken der Fachportale -, wirkt die Grenze ueberall.

Benutzung
---------
    python werkzeug/suche_beschleunigen.py --pruefen      nur berichten
    python werkzeug/suche_beschleunigen.py                aendern
    python werkzeug/suche_beschleunigen.py --rueckgaengig  zuruecknehmen

Vor jeder Aenderung entsteht eine Sicherung neben der Datei. Nach der
Aenderung wird die Datei neu eingelesen; misslingt das, wird die Sicherung
sofort zurueckgespielt und nichts bleibt kaputt.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent
ZIEL = WURZEL / "backend" / "tools" / "web_tools.py"
SICHERUNG = ZIEL.with_suffix(".py.vor-zeitbudget")
VORRAT = HIER / "neue_funktionen.txt"

MARKE = "# --- Zeitbudget der Websuche (siehe docs/SUCHE-ZEITBUDGET.md) ---"

#: Was oben im Kopf stehen muss, damit die neuen Funktionen laufen.
NOETIGE_IMPORTE = (
    "import time",
    "import zlib",
    "from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait",
)


def teile_lesen() -> dict[str, str]:
    """Holt die Ersatztexte aus ``neue_funktionen.txt``."""

    if not VORRAT.exists():
        raise SystemExit(f"Der Textvorrat fehlt: {VORRAT}")
    roh = VORRAT.read_text(encoding="utf-8")
    teile = dict(re.findall(r"###(\w+)###\n(.*?)\n###ENDE###", roh, re.S))
    for name in ("KONSTANTEN", "_fetch", "search_web"):
        if name not in teile:
            raise SystemExit(f"Im Textvorrat fehlt der Abschnitt {name}.")
        ast.parse(teile[name])  # Fruehe Warnung, bevor irgendetwas angefasst wird.
    return teile


def funktion_finden(baum: ast.Module, name: str) -> ast.FunctionDef:
    for knoten in baum.body:
        if isinstance(knoten, ast.FunctionDef) and knoten.name == name:
            return knoten
    raise SystemExit(
        f"In {ZIEL.name} gibt es keine Funktion {name} auf oberster Ebene. "
        "Wurde die Datei umgebaut? Dann bitte von Hand nachsehen."
    )


def letzte_importzeile(baum: ast.Module) -> int:
    """Die Zeilennummer des letzten Imports im Kopf der Datei."""

    letzte = 0
    for knoten in baum.body:
        if isinstance(knoten, (ast.Import, ast.ImportFrom)):
            letzte = max(letzte, knoten.end_lineno or knoten.lineno)
        elif letzte:
            break
    if not letzte:
        raise SystemExit("Im Kopf der Datei stehen keine Importe - das ist unerwartet.")
    return letzte


def anwenden(text: str, teile: dict[str, str]) -> str:
    baum = ast.parse(text)
    zeilen = text.splitlines(keepends=True)

    fetch = funktion_finden(baum, "_fetch")
    suche = funktion_finden(baum, "search_web")
    import_ende = letzte_importzeile(baum)

    # Von hinten nach vorn ersetzen, damit die Zeilennummern gueltig bleiben.
    ersetzungen: list[tuple[int, int, str]] = [
        (suche.lineno - 1, suche.end_lineno, teile["search_web"].rstrip() + "\n"),
        (
            fetch.lineno - 1,
            fetch.end_lineno,
            MARKE + "\n" + teile["KONSTANTEN"].rstrip() + "\n\n\n"
            + teile["_fetch"].rstrip() + "\n",
        ),
    ]
    for anfang, ende, neu in sorted(ersetzungen, reverse=True):
        zeilen[anfang:ende] = [neu]

    # Fehlende Importe ergaenzen.
    fehlend = [zeile for zeile in NOETIGE_IMPORTE
               if not re.search(r"^" + re.escape(zeile) + r"\s*$", text, re.M)]
    if fehlend:
        zeilen.insert(import_ende, "".join(z + "\n" for z in fehlend))

    return "".join(zeilen)


def bericht(text: str) -> None:
    baum = ast.parse(text)
    fetch = funktion_finden(baum, "_fetch")
    suche = funktion_finden(baum, "search_web")
    print(f"  Datei          : {ZIEL}")
    print(f"  _fetch         : Zeile {fetch.lineno}-{fetch.end_lineno}")
    print(f"  search_web     : Zeile {suche.lineno}-{suche.end_lineno}")
    print(f"  Schon geaendert: {'ja' if MARKE in text else 'nein'}")


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    zerleger.add_argument("--pruefen", action="store_true",
                          help="Nur berichten, nichts aendern.")
    zerleger.add_argument("--rueckgaengig", action="store_true",
                          help="Die Sicherung zurueckspielen.")
    zerleger.add_argument("--datei", default=None,
                          help="Andere Zieldatei (fuer Tests).")
    argumente = zerleger.parse_args()

    global ZIEL, SICHERUNG
    if argumente.datei:
        ZIEL = Path(argumente.datei).resolve()
        SICHERUNG = ZIEL.with_suffix(".py.vor-zeitbudget")

    print("=" * 70)
    print(" Zeitbudget fuer die Websuche des AI-Orb")
    print("=" * 70)

    if argumente.rueckgaengig:
        if not SICHERUNG.exists():
            print(f"  Es gibt keine Sicherung ({SICHERUNG.name}).")
            return 1
        shutil.copy2(SICHERUNG, ZIEL)
        SICHERUNG.unlink()
        print("  Der urspruengliche Stand ist zurueck.")
        return 0

    if not ZIEL.exists():
        print(f"  Nicht gefunden: {ZIEL}")
        print("  Bitte aus dem Orb-Ordner heraus starten.")
        return 1

    text = ZIEL.read_text(encoding="utf-8")
    try:
        bericht(text)
    except SyntaxError as fehler:
        print(f"  Die Datei laesst sich nicht einlesen: {fehler}")
        return 1

    if MARKE in text:
        print()
        print("  Die Aenderung ist bereits eingespielt. Es gibt nichts zu tun.")
        return 0

    teile = teile_lesen()
    neu = anwenden(text, teile)

    # Vor dem Schreiben pruefen, ob das Ergebnis ueberhaupt gueltig ist.
    try:
        compile(neu, str(ZIEL), "exec")
    except SyntaxError as fehler:
        print()
        print(f"  Das Ergebnis waere fehlerhaft ({fehler}). Es wurde NICHTS geaendert.")
        return 1

    if argumente.pruefen:
        print()
        print("  Pruefung bestanden. Die Aenderung waere:")
        print(f"    - _fetch bekommt Frist und Groessengrenze")
        print(f"    - search_web bekommt ein Gesamtbudget von 20 Sekunden")
        print(f"    - die Suchmaschinen werden gleichzeitig gefragt")
        print(f"    - {len(neu.splitlines()) - len(text.splitlines()):+d} Zeilen")
        print()
        print("  Zum Anwenden dasselbe ohne --pruefen aufrufen.")
        return 0

    shutil.copy2(ZIEL, SICHERUNG)
    ZIEL.write_text(neu, encoding="utf-8")
    print()
    print(f"  Sicherung : {SICHERUNG.name}")
    print("  Geaendert : _fetch, search_web")
    print()
    print("  Der Orb muss neu gestartet werden, damit es wirkt.")
    print("  Danach SUCHE-PRUEFEN.bat - es zeigt jede Quelle einzeln.")
    print("  Zuruecknehmen: python werkzeug/suche_beschleunigen.py --rueckgaengig")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
