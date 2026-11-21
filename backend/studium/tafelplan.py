"""Die Lehrtafel zur Vorlesung - geplant vom Sprachmodell, nicht erraten.

Marc, 19.11.2026: "Die Animationen bei den Vorlesungen sind noch nicht gut.
Ich will richtige Darstellungen des Inhalts und nicht so zufaellige
Praesentationen."

Bisher entstanden Titel, Karten und Bildsuche aus Regeln, die Woerter aus
dem gesprochenen Abschnitt fischten (``vorlesungs_bilder.py``): Grossge-
schriebene Wortgruppen wurden zu Bildsuchbegriffen, Saetze zu Karten. Die
Regeln verstehen den Inhalt nicht - daher das Zufaellige: ein Foto zum
erstbesten Eigennamen, Karten mit halben Saetzen.

Jetzt liest das Sprachmodell den Abschnitt einmal und plant die Tafel:

* die passende Darstellung (Aufzaehlung, Zeitleiste, Gegenueberstellung,
  Uebersicht) - so, wie der Inhalt gebaut ist;
* drei bis fuenf Karten mit den Kernaussagen, knapp formuliert;
* EINEN genauen Bildbegriff - oder bewusst keinen, wenn kein Bild den
  Inhalt zeigt. Lieber keine Fotografie als eine beliebige.

Das laeuft im Hintergrund, waehrend der Abschnitt schon gesprochen wird;
der Vortrag wartet nie darauf. Faellt das Modell aus oder antwortet
unbrauchbar, gilt die bisherige Regel-Tafel.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: Darstellungen, die die Lehrtafel kennt (desktop/renderer/main.ts).
DARSTELLUNGEN = ("enumeration", "timeline", "comparison", "overview")

ANWEISUNG = (
    "Du gestaltest die Lehrtafel zu einem gesprochenen Vorlesungsabschnitt. "
    "Die Tafel zeigt, was das Auge schneller erfasst als das Ohr: Struktur, "
    "Reihenfolge, Gegensaetze, Kernbegriffe. Sie wiederholt nicht den Sprechtext.\n\n"
    "Antworte NUR mit einem JSON-Objekt, ohne Erklaerung, mit diesen Feldern:\n"
    '{"titel": "...", "darstellung": "enumeration|timeline|comparison|overview", '
    '"karten": [{"titel": "...", "text": "..."}], "bildbegriff": "..."}\n\n'
    "Regeln:\n"
    "- titel: das eigentliche Thema DIESES Abschnitts, hoechstens 6 Woerter.\n"
    "- darstellung: timeline, wenn der Abschnitt eine zeitliche Abfolge erzaehlt "
    "(Kartentitel = Jahr oder Epoche); comparison, wenn zwei Positionen, Epochen oder "
    "Begriffe gegeneinander stehen (genau 2 oder 3 Karten); enumeration, wenn er Gruende, "
    "Merkmale oder Schritte aufzaehlt; sonst overview.\n"
    "- karten: 3 bis 5. Kartentitel hoechstens 4 Woerter; Text ein vollstaendiger, "
    "verstaendlicher Gedanke in hoechstens 18 Woertern, sachlich korrekt und nur aus dem "
    "Abschnitt. Keine Fuellkarten.\n"
    "- bildbegriff: ein konkretes, eindeutig abbildbares Motiv, das genau diesen Inhalt "
    "zeigt (eine Person, ein Bauwerk, ein Objekt, eine historische Karte, ein Gemaelde mit "
    "Namen), so wie es in Wikimedia Commons heissen wuerde, z. B. 'Karte Frankenreich 814' "
    "oder 'Stele des Hammurabi'. Ist der Abschnitt abstrakt (Methode, Begriff, Theorie), "
    "lass bildbegriff leer - dann zeigt die Tafel nur die Karten.\n"
    "- Alles auf Deutsch."
)


@dataclass
class Tafelplan:
    titel: str
    darstellung: str
    karten: list[dict[str, str]] = field(default_factory=list)
    bildbegriff: str = ""

    def als_ereignis(self) -> dict[str, Any]:
        """Die Felder so, wie die Lehrtafel sie erwartet."""

        return {"title": self.titel, "layout": self.darstellung, "summary": self.karten}


def nachrichten(abschnitt: str, thema: str = "") -> list[tuple[str, str]]:
    """(Rolle, Inhalt) fuer den Planungsaufruf."""

    text = " ".join(str(abschnitt or "").split())[:3500]
    kopf = f"Vorlesungsthema: {thema}\n\n" if thema else ""
    return [("system", ANWEISUNG), ("user", f"{kopf}Abschnitt:\n{text}")]


def _kuerzen(text: str, woerter: int, zeichen: int) -> str:
    teile = " ".join(str(text or "").split()).split()
    kurz = " ".join(teile[:woerter])
    if len(kurz) > zeichen:
        kurz = kurz[:zeichen].rsplit(" ", 1)[0]
    return kurz.strip(" ,;:")


def auswerten(antwort: str) -> Tafelplan | None:
    """Liest die Modellantwort - streng. Unbrauchbares ergibt ``None``."""

    roh = str(antwort or "").strip()
    treffer = re.search(r"\{.*\}", roh, re.DOTALL)
    if not treffer:
        return None
    try:
        daten = json.loads(treffer.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(daten, dict):
        return None

    titel = _kuerzen(daten.get("titel", ""), 8, 60)
    darstellung = str(daten.get("darstellung", "")).strip().lower()
    if darstellung not in DARSTELLUNGEN:
        darstellung = "overview"

    karten: list[dict[str, str]] = []
    gesehen: set[str] = set()
    for karte in daten.get("karten", []) or []:
        if not isinstance(karte, dict):
            continue
        ktitel = _kuerzen(karte.get("titel", ""), 6, 40)
        ktext = _kuerzen(karte.get("text", ""), 26, 170)
        if not ktext or ktext.casefold() in gesehen:
            continue
        gesehen.add(ktext.casefold())
        karten.append({"title": ktitel, "text": ktext})
        if len(karten) == 5:
            break

    if not titel or len(karten) < 2:
        return None
    if darstellung == "comparison" and len(karten) > 3:
        darstellung = "enumeration"

    bildbegriff = _kuerzen(daten.get("bildbegriff", ""), 8, 80)
    return Tafelplan(titel=titel, darstellung=darstellung, karten=karten, bildbegriff=bildbegriff)
