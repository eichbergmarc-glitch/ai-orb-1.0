"""Misst, wie lange die Websuche wirklich braucht.

Vor und nach der Aenderung dasselbe aufrufen - dann steht der Unterschied
in Sekunden da, statt dass man ihn vermutet. Es wird nichts veraendert und
nichts gespeichert; das Skript stellt nur Fragen und stoppt die Zeit.

    python werkzeug/suche_zeitprobe.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: Drei Fragen, die im Orb unterschiedliche Wege nehmen: eine Sachfrage
#: (offene Quellen zuerst), eine Nachrichtenfrage (Feeds zuerst) und eine
#: Alltagsfrage (echter Webindex zuerst).
FRAGEN = (
    ("Sachfrage", "Wer war Otto von Bismarck"),
    ("Nachrichten", "Was gibt es Neues aus der Ukraine"),
    ("Alltag", "Oeffnungszeiten Stadtbibliothek Zuerich"),
)


def main() -> int:
    try:
        from backend.tools.web_tools import search_web
    except Exception as fehler:  # noqa: BLE001
        print(f"Die Suche liess sich nicht laden: {fehler}")
        print("Bitte aus dem Orb-Ordner heraus starten.")
        return 1

    from backend.tools import web_tools

    budget = getattr(web_tools, "_SUCH_GESAMTBUDGET", None)
    print("=" * 70)
    print(" Zeitprobe der Websuche")
    print("=" * 70)
    print(" Zeitbudget: %s" % (f"{budget:.0f} Sekunden" if budget else "keines (alter Stand)"))
    print()

    gesamt = 0.0
    for art, frage in FRAGEN:
        begonnen = time.monotonic()
        try:
            treffer = search_web(frage, limit=5)
            ergebnis = f"{len(treffer)} Treffer"
        except Exception as fehler:  # noqa: BLE001
            ergebnis = f"kein Treffer ({str(fehler)[:60]})"
        dauer = time.monotonic() - begonnen
        gesamt += dauer
        print(f"  {art:<12} {dauer:6.1f} s   {ergebnis}")

    print()
    print(f"  {'zusammen':<12} {gesamt:6.1f} s")
    print()
    if budget is None:
        print(" Ohne Zeitbudget kann eine einzelne Frage beliebig lange dauern.")
        print(" Einspielen mit: python werkzeug/suche_beschleunigen.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
