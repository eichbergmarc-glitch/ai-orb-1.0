"""Lernen (Phasen 12 und 18).

Zwei verschiedene Dinge unter einem Dach:

* :mod:`backend.learning.preference_learner` – was AI-Orb aus der Nutzung
  über den Benutzer lernt (Antwortlänge, bevorzugter Weg, aktive Zeiten).
* :mod:`backend.learning.flashcards` und :mod:`backend.learning.study_plan` –
  was der Benutzer mit Hilfe von AI-Orb lernt: Karteikarten mit abgestuften
  Wiederholungen und Lernpläne bis zu einem Termin.

Beides liegt lokal in ``data/learning/`` und lässt sich einsehen und löschen.
"""

from backend.learning.flashcards import DAY, Card, FlashcardDeck, Grade
from backend.learning.preference_learner import Preference, PreferenceLearner
from backend.learning.study_plan import StudyPlan, StudyPlanner, Topic

__all__ = [
    "DAY",
    "Card",
    "FlashcardDeck",
    "Grade",
    "Preference",
    "PreferenceLearner",
    "StudyPlan",
    "StudyPlanner",
    "Topic",
]
