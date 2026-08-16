"""Trägt den Stimmserver in die config.yaml ein - oder schaltet ihn ab.

Warum ein eigenes Skript und keine Textersetzung in der BAT-Datei: Es sind
ZWEI Dinge zu tun, und das zweite wäre beinahe untergegangen.

1. Die Adresse unter ``voice.output.remote.endpoint`` eintragen.
2. ``remote`` in ``voice.output.engines`` nach VORN stellen.

Der zweite Schritt ist der entscheidende. Die Liste lautet in der
Voreinstellung ``[elevenlabs, piper, sapi, kokoro]`` - ``remote`` steht dort
überhaupt nicht. Wer nur die Adresse einträgt, hat einen laufenden Server,
eine gültige Konfiguration und hört trotzdem weiter die alte Stimme, ohne
dass irgendwo ein Fehler erschiene.

Die Datei wird mit ruamel/PyYAML NICHT neu geschrieben, sondern zeilenweise
bearbeitet: Die config.yaml ist über tausend Zeilen sorgfältig kommentiert,
und ein Neuschreiben würde jeden dieser Kommentare löschen.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def _endpunkt_setzen(text: str, adresse: str) -> tuple[str, bool]:
    """Trägt die Adresse unter ``remote: endpoint:`` ein."""

    muster = re.compile(r"(^(\s*)remote:\s*\n\2\s+endpoint:\s*)\S*.*$", re.M)
    neu, anzahl = muster.subn(
        lambda m: m.group(1) + (f'"{adresse}"' if adresse else '""'), text, count=1
    )
    return neu, anzahl > 0


def _remote_nach_vorn(text: str, anschalten: bool) -> tuple[str, bool]:
    """Stellt ``remote`` in der Engine-Liste nach vorn - oder nimmt es heraus.

    Die Liste steht als BLOCK, mit Kommentaren dazwischen::

        engines:
          # elevenlabs zuerst: die authentische Stimme ...
          - "elevenlabs"
          - "piper"

    Deshalb wird nur die erste Eintragszeile gesucht und ``remote`` davor
    gesetzt beziehungsweise die ``remote``-Zeile entfernt. Die Kommentare
    bleiben dabei unangetastet - sie erklären die Reihenfolge, und wer sie
    beim Umstellen wegwirft, nimmt der Datei ihren Sinn.
    """

    zeilen = text.splitlines(keepends=True)

    # Den Beginn des Abschnitts finden.
    start = None
    einrueckung = ""
    for i, zeile in enumerate(zeilen):
        treffer = re.match(r"^(\s*)engines:\s*$", zeile)
        if treffer:
            start = i
            einrueckung = treffer.group(1)
            break
    if start is None:
        return text, False

    # Den Bereich der Listeneinträge bestimmen (Kommentare gehören dazu).
    erste_eintragszeile = None
    ende = len(zeilen)
    for i in range(start + 1, len(zeilen)):
        zeile = zeilen[i]
        if not zeile.strip():
            continue
        eintrag = re.match(r"^(\s*)-\s*[\"']?([\w_]+)[\"']?\s*$", zeile)
        kommentar = re.match(r"^\s*#", zeile)
        if eintrag and len(eintrag.group(1)) > len(einrueckung):
            if erste_eintragszeile is None:
                erste_eintragszeile = i
            continue
        if kommentar:
            continue
        ende = i
        break

    if erste_eintragszeile is None:
        return text, False

    bereich = zeilen[erste_eintragszeile:ende]
    eintrags_einrueckung = re.match(r"^(\s*)-", bereich[0]).group(1)

    # Vorhandene remote-Zeilen entfernen.
    gesaeubert = [
        z for z in bereich
        if not re.match(r"^\s*-\s*[\"']?remote[\"']?\s*$", z)
    ]

    if anschalten:
        gesaeubert.insert(0, f'{eintrags_einrueckung}- "remote"\n')

    neu = zeilen[:erste_eintragszeile] + gesaeubert + zeilen[ende:]
    return "".join(neu), True


def main(argv: list[str]) -> int:
    adresse = (argv[1].strip().rstrip("/") if len(argv) > 1 else "")
    pfad = Path(argv[2]) if len(argv) > 2 else Path("config.yaml")

    if not pfad.is_file():
        print(f"   [FEHLER] {pfad} nicht gefunden.")
        return 1

    text = pfad.read_text(encoding="utf-8")

    text, ok_endpunkt = _endpunkt_setzen(text, adresse)
    if not ok_endpunkt:
        print("   [FEHLER] 'remote: endpoint:' war in der config.yaml nicht zu finden.")
        return 3

    text, ok_liste = _remote_nach_vorn(text, bool(adresse))
    pfad.write_text(text, encoding="utf-8")

    if adresse:
        print(f"        Adresse eingetragen: {adresse}")
    else:
        print("        Adresse geloescht.")

    if ok_liste:
        print(
            "        'remote' steht jetzt an erster Stelle der Stimmen."
            if adresse
            else "        'remote' aus der Stimmenliste entfernt."
        )
    else:
        # Das ist kein Schoenheitsfehler: Ohne diesen Schritt laeuft der
        # Server, die Adresse steht drin - und es spricht trotzdem die
        # alte Stimme, ohne dass irgendwo ein Fehler erschiene.
        print(
            "   [WARNUNG] Die Stimmenliste (voice.output.engines) war nicht\n"
            "             zu finden. Trage 'remote' dort bitte von Hand an\n"
            "             erster Stelle ein - sonst bleibt die alte Stimme."
        )
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
