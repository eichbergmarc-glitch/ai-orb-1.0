"""Historical Professor & Mentor Engine.

Ein persönlicher akademischer Mentor für Geschichtswissenschaft. Nicht
eine Antwortmaschine mit Professorentonfall, sondern ein Betreuer, der
sich erinnert, nachfragt statt aufzulösen, und das Niveau mitgehen lässt.

Das Ziel steht in Abschnitt 32 der Vorgabe und ist ungewöhnlich klar:
Der Benutzer soll nicht mehr Fakten kennen, sondern lernen, selbst wie ein
Historiker zu denken. Daraus folgt der wichtigste Konstruktionsgrundsatz –
der Professor liefert die Lösung nicht, wenn der Benutzer sie sich selbst
erarbeiten kann.
"""

from backend.agents.history_agent.learning_profile import (
    COMPETENCE_LABELS,
    COMPETENCES,
    LEVELS,
    LearningProfile,
)

__all__ = [
    "COMPETENCES",
    "COMPETENCE_LABELS",
    "LEVELS",
    "LearningProfile",
]
