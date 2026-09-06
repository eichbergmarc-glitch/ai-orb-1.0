"""Die Wissenslandkarten der einzelnen Felder.

Jedes Feld steht in einer eigenen Datei und trägt sich über
``alle_eintragen()`` ins Verzeichnis ein. Der Eintrag prüft die Karte:
Ein Verweis auf ein Thema, das es nicht gibt, oder ein Ringschluss - für
A braucht man B und für B wieder A - kommt gar nicht erst herein.

Neue Felder werden hier ergänzt. Geschichte, Philosophie, Geografie,
Sprachwissenschaft, Germanistik und Wirtschaft folgen.
"""

from __future__ import annotations

from backend.studium.landkarte import eintragen


def alle_eintragen() -> None:
    """Trägt alle mitgelieferten Felder ein."""

    from backend.studium.fachplaene.geografie import GEOGRAFIE
    from backend.studium.fachplaene.germanistik import GERMANISTIK
    from backend.studium.fachplaene.geschichte import GESCHICHTE
    from backend.studium.fachplaene.philosophie import PHILOSOPHIE
    from backend.studium.fachplaene.sprachwissenschaft import SPRACHWISSENSCHAFT
    from backend.studium.fachplaene.wirtschaft import WIRTSCHAFT

    eintragen(SPRACHWISSENSCHAFT)
    eintragen(GERMANISTIK)
    eintragen(GESCHICHTE)
    eintragen(PHILOSOPHIE)
    eintragen(GEOGRAFIE)
    eintragen(WIRTSCHAFT)
