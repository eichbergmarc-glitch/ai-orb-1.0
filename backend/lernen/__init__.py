"""Lehrer und Schüler: Claude als Referenz, Ollama als lokaler Nachfolger.

Der Gedanke ist einfach und die Umsetzung heikel: Ein starkes Modell in der
Wolke beantwortet, was schwierig ist. Ein lokales Modell lernt mit. Sobald
es eine Aufgabenart nachweislich genauso gut kann, übernimmt es sie - und
zwar dauerhaft, offline, ohne Wolke.

Das entscheidende Wort ist **nachweislich**. Dieses Paket enthält deshalb
zuerst die Messung und erst danach die Übergabe:

* ``faehigkeitskatalog`` - was gekonnt werden muss, versioniert.
* ``messwerte``          - was gemessen wurde, unveränderlich abgelegt.
* ``bewertung``          - wie bewertet wird: feste Rubriken, deterministische
                           Prüfungen, mehrere Bewerter. Claude ist einer davon,
                           nie der einzige.
* ``uebergabe``          - der Zustand je Kategorie und die Stufen 0 bis 100 %.
* ``schattenlauf``       - beide rechnen, nur einer antwortet.

Was hier NICHT steht, steht mit Absicht nicht hier: Es gibt keine
Voreinstellung, die eine Kategorie ohne Messung an das lokale Modell gibt.
"""

from backend.lernen.faehigkeitskatalog import (
    KATALOG_VERSION,
    KATEGORIEN,
    Pruefkatalog,
    Pruefstueck,
    katalog,
)
from backend.lernen.messwerte import Messreihe, Messung
from backend.lernen.uebergabe import STUFEN, Uebergabe, Kategoriestand

__all__ = [
    "KATALOG_VERSION",
    "KATEGORIEN",
    "Pruefkatalog",
    "Pruefstueck",
    "katalog",
    "Messreihe",
    "Messung",
    "STUFEN",
    "Uebergabe",
    "Kategoriestand",
]
