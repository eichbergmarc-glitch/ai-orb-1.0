"""Prüft, ob die offenen Suchquellen von diesem Rechner aus erreichbar sind.

Warum es das gibt: Die Umgebung, in der dieser Code geschrieben wurde, hat
keinen Zugang zum offenen Netz - GDELT, Wikipedia und OpenAlex liessen sich
dort nicht anfragen. Geprüft wurde deshalb gegen nachgebaute Antworten mit
den echten Feldnamen. Ob die Dienste vom Rechner des Benutzers aus wirklich
antworten, kann nur dieser Rechner beantworten. Genau das tut dieses Skript.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _zeile(name: str, text: str) -> None:
    print(f"        {name:<24}{text}")


def quellen_pruefen() -> int:
    from backend.research import offene_quellen as offen

    proben = [
        ("GDELT (Nachrichten)",
         lambda: offen.gdelt_suchen("Bundestag", limit=3, sprache="german", zeitraum="1w")),
        ("Wikipedia", lambda: offen.wikipedia_suchen("Julikrise", limit=3)),
        ("OpenAlex (Literatur)",
         lambda: offen.openalex_suchen("Fritz Fischer Kriegsziele", limit=3)),
        ("Crossref (DOI)",
         lambda: offen.crossref_suchen("Weltkrieg Historiographie", limit=3)),
    ]

    fehlend = 0
    for name, probe in proben:
        try:
            treffer = probe()
        except Exception as fehler:  # noqa: BLE001
            _zeile(name, f"KEINE ANTWORT - {fehler}")
            fehlend += 1
            continue
        if treffer:
            _zeile(name, f"OK - {len(treffer)} Treffer, z.B. {treffer[0]['titel'][:52]}")
        else:
            _zeile(name, "antwortet, aber keine Treffer zu dieser Probe")

    if offen.google_verfuegbar():
        try:
            treffer = offen.google_suchen("Julikrise 1914", limit=3)
            _zeile("Google (mit Schluessel)", f"OK - {len(treffer)} Treffer")
        except Exception as fehler:  # noqa: BLE001
            _zeile("Google (mit Schluessel)", f"KEINE ANTWORT - {fehler}")
            fehlend += 1
    else:
        _zeile("Google", "kein Schluessel hinterlegt (optional, nicht noetig)")

    return fehlend


def suchen_pruefen() -> int:
    from backend.tools.web_tools import search_web

    fragen = [
        ("Sachfrage", "Wer war Otto von Bismarck?"),
        ("Nachrichten", "Was gibt es Neues aus Berlin?"),
        ("Eine Zeitung", "site:tagesschau.de Haushalt"),
        ("Forschung", "Forschungsstand zur Julikrise"),
    ]

    leer = 0
    for name, frage in fragen:
        try:
            treffer = search_web(frage, limit=3)
        except Exception as fehler:  # noqa: BLE001
            _zeile(name, f"GESCHEITERT - {fehler}")
            leer += 1
            continue
        if not treffer:
            _zeile(name, "keine Treffer")
            leer += 1
            continue
        _zeile(name, f"{len(treffer)} Treffer")
        for eintrag in treffer:
            print(f"           - {eintrag['titel'][:66]}")
    return leer


def main() -> int:
    print()
    print("   Erreichbarkeit der offenen Quellen")
    print("   " + "-" * 56)
    fehlend = quellen_pruefen()

    print()
    print("   Eine echte Suche, wie der Orb sie macht")
    print("   " + "-" * 56)
    leer = suchen_pruefen()

    print()
    if fehlend == 0 and leer == 0:
        print("   Alles beantwortet. Die Suche ist wieder da.")
        return 0
    if leer == 0:
        print(f"   {fehlend} Quelle(n) antworteten nicht, die Suche liefert")
        print("   trotzdem Treffer - genau dafuer sind es mehrere.")
        return 0
    print("   Es kam nichts zurueck. Den Grund im Klartext findest du in")
    print("   logs\\backend_research_offene_quellen.log")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
