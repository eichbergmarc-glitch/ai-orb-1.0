"""Event-Schicht von AI-Orb.

Alle Backend-Module kommunizieren ausschließlich über den zentralen
:class:`~backend.events.event_bus.EventBus`. Es gibt keine direkte
Kommunikation zwischen Fachmodulen. Event-Namen sind in
:mod:`backend.events.event_types` als Konstanten definiert, um Tippfehler
und uneinheitliche Benennung zu vermeiden.
"""

from backend.events.event_bus import EventBus, get_event_bus
from backend.events import event_types

__all__ = ["EventBus", "get_event_bus", "event_types"]
