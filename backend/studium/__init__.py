"""Das Studium: Landkarte, Mitlesen, Zeigen.

Der verbindende Gedanke steht in :mod:`backend.studium.landkarte`: eine
Landkarte des Wissens, kein Studienplan. Wer die Reihenfolge bestimmt,
ist der Lernende - der Orb sagt ihm, was womit zusammenhängt und was ihm
für ein Ziel noch fehlt.
"""

from backend.studium.landkarte import (
    TIEFEN,
    TIEFEN_KLARTEXT,
    Anlass,
    Feld,
    Gebiet,
    LandkarteFehler,
    Thema,
    feld,
    feld_suchen,
    felder,
    thema_suchen,
)

__all__ = [
    "TIEFEN",
    "TIEFEN_KLARTEXT",
    "Anlass",
    "Feld",
    "Gebiet",
    "LandkarteFehler",
    "Thema",
    "feld",
    "feld_suchen",
    "felder",
    "thema_suchen",
]
