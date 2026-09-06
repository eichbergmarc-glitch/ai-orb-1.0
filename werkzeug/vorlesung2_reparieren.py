# -*- coding: utf-8 -*-
"""Setzt die erneuerte Vorlesungserkennung in den Orb ein.

Was ersetzt wird, steht in ``vorlesung2_ersatz.txt`` daneben - lesbar, mit
Begruendung. Dieses Werkzeug tut nichts weiter, als genau diese Mitglieder in
``backend/studium/vorlesungs_session.py`` auszutauschen:

    VorlesungsSession._FORTSETZEN
    VorlesungsSession._thema_aus
    VorlesungsSession.befehl

und die dafuer noetigen Klassenkonstanten daneben zu legen.

Gearbeitet wird ueber den Syntaxbaum, nicht ueber Textsuche: Die Mitglieder
werden an ihrer Klasse und ihrem Namen gefunden, nie an einer Zeichenkette.
Vor jeder Aenderung entsteht eine Sicherung. Nach jeder Aenderung wird die
Datei uebersetzt; scheitert das, wird die Sicherung zurueckgespielt.

    python vorlesung2_reparieren.py --pruefen        nur zeigen, nichts tun
    python vorlesung2_reparieren.py                  einsetzen
    python vorlesung2_reparieren.py --rueckgaengig   Sicherung zurueckholen
"""

from __future__ import annotations

import argparse
import ast
import shutil
import sys
from pathlib import Path

KLASSE = "VorlesungsSession"
ZIEL = Path("backend") / "studium" / "vorlesungs_session.py"
ERSATZDATEI = "vorlesung2_ersatz.txt"
SICHERUNG = ".vor-vorlesung2"

#: Diese Mitglieder werden ersetzt.
ZU_ERSETZEN = ("_FORTSETZEN", "_thema_aus", "befehl")

#: Diese Namen legt der Ersatz zusaetzlich an. Beim erneuten Lauf muessen sie
#: mit entfernt werden, sonst stuenden sie doppelt in der Klasse.
ZUSAETZLICH = (
    "_LEHRWORT", "_THEMA_MUSTER", "_THEMA_DOPPELPUNKT", "_THEMA_STICHWORT",
    "_THEMA_LEHRVERB", "_ALS_FORM", "_BITTWORT", "_EINENGUNG", "_SATZENDE",
    "_ARTIKEL", "_NEUANFANG", "_THEMA_GENANNT", "_LEHRVERB_GENANNT",
    "_LEHRWORT_MIT_WORT", "_BITTRAHMEN", "_ANHALTEN_GETRENNT",
    "_ANHALTEWORTE", "_ZURUFE", "_STARTMARKER", "_FORT_LOSE", "_WEITERREDEN",
    "_saeubern",
)


def orb_wurzel(start: Path) -> Path:
    """Sucht das Verzeichnis, in dem der Orb liegt."""

    for verzeichnis in (start, *start.parents):
        if (verzeichnis / ZIEL).is_file():
            return verzeichnis
    raise SystemExit(
        "Ich finde %s nicht. Lege dieses Werkzeug in den Ordner des Orb\n"
        "(dort, wo ORB-STARTEN.bat liegt) und starte es von dort." % ZIEL
    )


def _bereich(knoten: ast.AST) -> tuple[int, int]:
    """Erste und letzte Zeile eines Mitglieds, Schmuecker eingeschlossen."""

    erste = knoten.lineno
    for schmuecker in getattr(knoten, "decorator_list", ()):
        erste = min(erste, schmuecker.lineno)
    return erste, knoten.end_lineno


def mitglieder(quelle: str, namen: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    """Sucht Mitglieder der Klasse ``KLASSE`` und liefert ihre Zeilenbereiche."""

    baum = ast.parse(quelle)
    gefunden: dict[str, tuple[int, int]] = {}
    for oben in ast.walk(baum):
        if not isinstance(oben, ast.ClassDef) or oben.name != KLASSE:
            continue
        for eintrag in oben.body:
            if isinstance(eintrag, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if eintrag.name in namen:
                    gefunden[eintrag.name] = _bereich(eintrag)
            elif isinstance(eintrag, ast.Assign):
                for ziel in eintrag.targets:
                    if isinstance(ziel, ast.Name) and ziel.id in namen:
                        gefunden[ziel.id] = (eintrag.lineno, eintrag.end_lineno)
            elif isinstance(eintrag, ast.AnnAssign):
                ziel = eintrag.target
                if isinstance(ziel, ast.Name) and ziel.id in namen:
                    gefunden[ziel.id] = (eintrag.lineno, eintrag.end_lineno)
    return gefunden


def neue_quelle(quelle: str, ersatz: str) -> str:
    """Baut den neuen Dateiinhalt: alte Mitglieder raus, Ersatz an ihre Stelle."""

    alle = ZU_ERSETZEN + ZUSAETZLICH
    stellen = mitglieder(quelle, alle)
    fehlend = [name for name in ZU_ERSETZEN if name not in stellen]
    if fehlend:
        raise SystemExit(
            "In %s fehlen diese Mitglieder von %s: %s\n"
            "Damit passt dieses Werkzeug nicht zu deiner Fassung der Datei.\n"
            "Nichts wurde geaendert."
            % (ZIEL, KLASSE, ", ".join(fehlend))
        )

    zeilen = quelle.splitlines(keepends=True)
    entfernen: set[int] = set()
    for erste, letzte in stellen.values():
        entfernen.update(range(erste - 1, letzte))
    # Der Block kommt dorthin, wo bisher ``befehl`` stand: Die Klasse
    # behaelt damit ihre gewohnte Reihenfolge - erst die Konstanten des
    # Zustands, dann __init__, dann die Erkennung.
    einfuegen_vor = stellen["befehl"][0] - 1

    gebaut: list[str] = []
    for nummer, zeile in enumerate(zeilen):
        if nummer == einfuegen_vor:
            gebaut.append(ersatz if ersatz.endswith("\n") else ersatz + "\n")
            gebaut.append("\n")
        if nummer in entfernen:
            continue
        gebaut.append(zeile)
    return "".join(gebaut)


def bericht(quelle: str) -> None:
    stellen = mitglieder(quelle, ZU_ERSETZEN + ZUSAETZLICH)
    print("Datei      : %s" % ZIEL)
    print("Klasse     : %s" % KLASSE)
    print()
    print("Wird ersetzt:")
    for name in ZU_ERSETZEN:
        if name in stellen:
            erste, letzte = stellen[name]
            print("  %-20s Zeile %5d bis %5d" % (KLASSE + "." + name, erste, letzte))
        else:
            print("  %-20s NICHT GEFUNDEN" % (KLASSE + "." + name))
    schon_da = [n for n in ZUSAETZLICH if n in stellen]
    if schon_da:
        print()
        print("Aus einem frueheren Lauf vorhanden und ebenfalls erneuert:")
        print("  " + ", ".join(schon_da))
    print()
    print("Alles andere in der Datei bleibt unangetastet.")


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(add_help=True, description=__doc__)
    zerleger.add_argument("--pruefen", action="store_true",
                          help="nur zeigen, was geschehen wuerde")
    zerleger.add_argument("--rueckgaengig", action="store_true",
                          help="die Sicherung zurueckspielen")
    args = zerleger.parse_args(argv)

    hier = Path(__file__).resolve().parent
    wurzel = orb_wurzel(hier)
    datei = wurzel / ZIEL
    sicherung = datei.with_suffix(datei.suffix + SICHERUNG)

    if args.rueckgaengig:
        if not sicherung.is_file():
            print("Es gibt keine Sicherung (%s)." % sicherung.name)
            return 1
        shutil.copy2(sicherung, datei)
        print("Zurueckgespielt: %s" % datei)
        return 0

    quelle = datei.read_text(encoding="utf-8")
    ersatz = (hier / ERSATZDATEI).read_text(encoding="utf-8")

    if args.pruefen:
        bericht(quelle)
        gebaut = neue_quelle(quelle, ersatz)
        try:
            compile(gebaut, str(datei), "exec")
        except SyntaxError as fehler:
            print()
            print("PROBE FEHLGESCHLAGEN: %s" % fehler)
            return 1
        print()
        print("Probe bestanden: Die neue Fassung laesst sich uebersetzen.")
        print("Zum Einsetzen dasselbe Werkzeug ohne --pruefen starten.")
        return 0

    gebaut = neue_quelle(quelle, ersatz)
    try:
        compile(gebaut, str(datei), "exec")
    except SyntaxError as fehler:
        print("Abbruch: Die neue Fassung liesse sich nicht uebersetzen (%s)." % fehler)
        print("Nichts wurde geaendert.")
        return 1

    # Die Sicherung wird nur beim ERSTEN Lauf angelegt. Sonst sicherte ein
    # zweiter Lauf die bereits geaenderte Datei, und --rueckgaengig fuehrte
    # nicht mehr auf den urspruenglichen Stand zurueck.
    if sicherung.is_file():
        print("Sicherung  : %s (aus einem frueheren Lauf, bleibt)" % sicherung.name)
    else:
        shutil.copy2(datei, sicherung)
        print("Gesichert  : %s" % sicherung.name)
    datei.write_text(gebaut, encoding="utf-8")
    print("Erneuert   : %s" % datei)
    print()
    print("Der Orb erkennt jetzt eine neue Vorlesung auch dann, wenn du sie")
    print("frei formulierst - und er nimmt das Thema so, wie du es gesagt hast.")
    print("Starte den Orb neu, damit die Aenderung wirkt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
