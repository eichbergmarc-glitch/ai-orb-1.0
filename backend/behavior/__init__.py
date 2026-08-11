"""Behavior Engine von AI-Orb (v2 Phase 3).

Lernt das Verhalten des Benutzers – bevorzugte Orb-Positionen,
Arbeitszeiten, Programmverwendung und Mausaktivität – und stellt daraus
Bewertungen für die Smart Desktop Engine bereit.

Alle Daten bleiben ausschließlich lokal.
"""

from backend.behavior.behavior_engine import BehaviorEngine, PositionPreference

__all__ = ["BehaviorEngine", "PositionPreference"]
