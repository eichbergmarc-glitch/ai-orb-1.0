"""Das Zeugnis: druckt die Tagesmesswerte des Orbs aus dem Laufzeitprotokoll.

Warum es das gibt: Am 17.08.2026 stand die Frage im Raum, ob der Orb über
die Tage schlechter geworden ist. Die Antwort liess sich messen - Hören
5,4 → 8,3 Sekunden, 60-95 % aller Transkriptionen für den Papierkorb -
aber nur mühsam von Hand. Ab jetzt liefert dieses Skript die Tabelle auf
Knopfdruck. Die Regel dazu: **Vor und nach jeder Änderung einmal laufen
lassen.** Eine Verbesserung, die hier nicht sichtbar wird, war keine.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

PROTOKOLL = Path(__file__).resolve().parents[1] / "logs" / "backend_system_performance_trace.log"


def eintraege_lesen(pfad: Path) -> list[dict]:
    ergebnis: list[dict] = []
    if not pfad.is_file():
        return ergebnis
    for zeile in pfad.open(encoding="utf-8", errors="replace"):
        treffer = re.search(r"TURN_LATENCY (\{.*\})", zeile)
        if not treffer:
            continue
        try:
            daten = json.loads(treffer.group(1))
        except ValueError:
            continue
        daten["_tag"] = zeile[:10]
        ergebnis.append(daten)
    return ergebnis


def _median(werte: list[float]) -> str:
    return f"{median(werte):7.1f}" if werte else "      -"


def zeugnis(tage: list[str] | None = None) -> int:
    eintraege = eintraege_lesen(PROTOKOLL)
    if not eintraege:
        print("   Kein Laufzeitprotokoll gefunden - der Orb muss erst laufen.")
        return 1

    nach_tag: dict[str, list[dict]] = defaultdict(list)
    for eintrag in eintraege:
        nach_tag[eintrag["_tag"]].append(eintrag)

    gewaehlt = tage or sorted(nach_tag)[-7:]

    print()
    print("   DAS ZEUGNIS DES ORBS (Median je Tag, Sekunden)")
    print("   " + "-" * 74)
    print(f"   {'Tag':12}{'Fragen':>7}{'Hören':>8}{'Suche':>8}{'Denken':>8}"
          f"{'gesamt':>8}   verworfen")
    for tag in gewaehlt:
        heute = nach_tag.get(tag, [])
        beantwortet = [e for e in heute if e.get("outcome") == "answered"]
        verworfen = sum(1 for e in heute if e.get("outcome") == "ignored")
        if not heute:
            continue
        hoeren = [e["transcript_ready"] for e in beantwortet if "transcript_ready" in e]
        suche = [
            e["provider_requested"] - e["orchestrator_received"]
            for e in beantwortet
            if "provider_requested" in e and "orchestrator_received" in e
        ]
        denken = [
            e["provider_first_text"] - e["provider_requested"]
            for e in beantwortet
            if "provider_first_text" in e and "provider_requested" in e
        ]
        gesamt = [e["completed"] for e in beantwortet if "completed" in e]
        anteil = f"{verworfen}/{len(heute)}"
        print(
            f"   {tag:12}{len(beantwortet):>7}{_median(hoeren)}{_median(suche)}"
            f"{_median(denken)}{_median(gesamt)}   {anteil}"
        )

    print()
    print("   Lesehilfe: 'Hören' wartest du bei JEDER Frage. 'verworfen' sind")
    print("   voll transkribierte Äußerungen, die am Ende niemand brauchte -")
    print("   jede kostete Rechenzeit, in der deine Sätze warteten.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(zeugnis(sys.argv[1:] or None))
