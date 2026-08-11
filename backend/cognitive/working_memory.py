"""Working Memory – das Kurzzeitgedächtnis des Cognitive Core.

Enthält ausschließlich das, was **gerade jetzt** relevant ist: das laufende
Gespräch, aktive Dokumente, aktuelle Programme, laufende Aufgaben,
temporäre Notizen und Zwischenergebnisse.

Working Memory ist kurzlebig. Einträge verfallen nach einer konfigurierbaren
Zeitspanne und werden nicht auf die Festplatte geschrieben. Was dauerhaft
erhalten bleiben soll, wandert über das Cognitive Core in das
Langzeitgedächtnis.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

#: Zulässige Kategorien des Working Memory.
SLOTS: tuple[str, ...] = (
    "conversation",
    "documents",
    "applications",
    "tasks",
    "notes",
    "intermediate",
)


@dataclass
class WorkingItem:
    """Ein einzelner, kurzlebiger Eintrag im Arbeitsgedächtnis."""

    slot: str
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)

    def age(self) -> float:
        """Alter des Eintrags in Sekunden seit dem letzten Zugriff."""

        return time.time() - self.touched_at


class WorkingMemory:
    """Kurzlebiger Arbeitsspeicher des Orb."""

    def __init__(self, ttl_seconds: float = 3600.0, max_items_per_slot: int = 50) -> None:
        """
        Args:
            ttl_seconds: Lebensdauer eines Eintrags ohne erneuten Zugriff.
            max_items_per_slot: Obergrenze pro Kategorie; ältere Einträge
                werden verdrängt.
        """

        self._ttl = ttl_seconds
        self._max_items = max_items_per_slot
        self._items: dict[str, dict[str, WorkingItem]] = {slot: {} for slot in SLOTS}
        self._lock = threading.RLock()

    def put(self, slot: str, key: str, value: Any) -> None:
        """Legt einen Eintrag ab oder aktualisiert ihn."""

        if slot not in self._items:
            self._items[slot] = {}
        with self._lock:
            self._items[slot][key] = WorkingItem(slot=slot, key=key, value=value)
            self._enforce_limit(slot)

    def get(self, slot: str, key: str, default: Any = None) -> Any:
        """Liest einen Eintrag und frischt dessen Lebensdauer auf."""

        with self._lock:
            item = self._items.get(slot, {}).get(key)
            if item is None:
                return default
            if item.age() > self._ttl:
                self._items[slot].pop(key, None)
                return default
            item.touched_at = time.time()
            return item.value

    def remove(self, slot: str, key: str) -> None:
        """Entfernt einen Eintrag."""

        with self._lock:
            self._items.get(slot, {}).pop(key, None)

    def slot(self, slot: str) -> dict[str, Any]:
        """Gibt alle gültigen Einträge einer Kategorie zurück."""

        self.expire()
        with self._lock:
            return {key: item.value for key, item in self._items.get(slot, {}).items()}

    def append(self, slot: str, value: Any, *, key: str | None = None) -> str:
        """Hängt einen Eintrag an eine Kategorie an und gibt dessen Schlüssel zurück."""

        generated_key = key or f"{slot}-{int(time.time() * 1000)}-{len(self._items.get(slot, {}))}"
        self.put(slot, generated_key, value)
        return generated_key

    def expire(self) -> int:
        """Entfernt abgelaufene Einträge.

        Returns:
            Anzahl der entfernten Einträge.
        """

        removed = 0
        with self._lock:
            for slot, entries in self._items.items():
                stale = [key for key, item in entries.items() if item.age() > self._ttl]
                for key in stale:
                    entries.pop(key, None)
                    removed += 1
        return removed

    def _enforce_limit(self, slot: str) -> None:
        entries = self._items.get(slot, {})
        if len(entries) <= self._max_items:
            return
        ordered = sorted(entries.values(), key=lambda item: item.touched_at)
        for item in ordered[: len(entries) - self._max_items]:
            entries.pop(item.key, None)

    def clear(self, slot: str | None = None) -> None:
        """Leert eine Kategorie oder das gesamte Arbeitsgedächtnis."""

        with self._lock:
            if slot is None:
                self._items = {name: {} for name in SLOTS}
            else:
                self._items[slot] = {}

    def snapshot(self) -> dict[str, Any]:
        """Vollständige Momentaufnahme für die Transparenzansicht."""

        self.expire()
        with self._lock:
            return {
                slot: {
                    key: {"value": item.value, "age_seconds": round(item.age(), 1)}
                    for key, item in entries.items()
                }
                for slot, entries in self._items.items()
            }
