"""User Memory – das persönliche Profil des Benutzers.

Enthält Vorlieben, Sprache, Zeitzone, Arbeitszeiten, bevorzugte Programme
und die bevorzugte KI. Das Profil entsteht schrittweise aus der Nutzung;
alle Werte sind jederzeit einsehbar, änderbar und löschbar
(Transparenzanforderung).

Es werden ausschließlich sachbezogene Angaben gespeichert – keine
personenbezogenen Bewertungen und keine Schlussfolgerungen über die Person.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from backend.utils.store import JsonStore

_DEFAULT_PROFILE: dict[str, Any] = {
    "name": None,
    "language": None,
    "timezone": None,
    "preferred_provider": None,
    "preferred_theme": None,
    "working_hours": {},
    "program_usage": {},
    "preferences": {},
    "facts": [],
    "created_at": None,
    "updated_at": None,
}


class UserMemory:
    """Verwaltet das persistente Benutzerprofil in ``data/user_profile.json``."""

    def __init__(self, filename: str = "user_profile.json") -> None:
        self._store = JsonStore(filename, default=dict(_DEFAULT_PROFILE))
        if self._store.get("created_at") is None:
            self._store.update({"created_at": time.time(), "updated_at": time.time()})

    # --- Profilfelder -------------------------------------------------------

    def set_field(self, field: str, value: Any) -> None:
        """Setzt ein einzelnes Profilfeld (z. B. ``language``)."""

        self._store.update({field: value, "updated_at": time.time()})

    def get_field(self, field: str, default: Any = None) -> Any:
        """Liest ein einzelnes Profilfeld."""

        return self._store.get(field, default)

    def set_preference(self, key: str, value: Any) -> None:
        """Speichert eine benannte Benutzervorliebe."""

        preferences = dict(self._store.get("preferences", {}) or {})
        preferences[key] = value
        self._store.update({"preferences": preferences, "updated_at": time.time()})

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Liest eine benannte Benutzervorliebe."""

        return (self._store.get("preferences", {}) or {}).get(key, default)

    # --- Beobachtete Nutzung -------------------------------------------------

    def record_activity(self, hour: int, program: str | None = None) -> None:
        """Vermerkt eine Aktivität zur Ermittlung von Arbeitszeiten und
        bevorzugten Programmen.

        Args:
            hour: Stunde des Tages (0–23).
            program: Optionaler Name des zu diesem Zeitpunkt aktiven
                Programms.
        """

        hours = dict(self._store.get("working_hours", {}) or {})
        key = str(max(0, min(23, int(hour))))
        hours[key] = int(hours.get(key, 0)) + 1

        updates: dict[str, Any] = {"working_hours": hours, "updated_at": time.time()}

        if program:
            usage = dict(self._store.get("program_usage", {}) or {})
            usage[program] = int(usage.get(program, 0)) + 1
            updates["program_usage"] = usage

        self._store.update(updates)

    def top_programs(self, limit: int = 5) -> list[tuple[str, int]]:
        """Gibt die am häufigsten genutzten Programme zurück."""

        usage = Counter(self._store.get("program_usage", {}) or {})
        return usage.most_common(limit)

    def typical_working_hours(self) -> list[int]:
        """Ermittelt die Stunden, in denen der Benutzer überdurchschnittlich
        aktiv ist."""

        hours = {int(key): int(value) for key, value in (self._store.get("working_hours", {}) or {}).items()}
        if not hours:
            return []
        average = sum(hours.values()) / len(hours)
        return sorted(hour for hour, count in hours.items() if count > average)

    # --- Fakten --------------------------------------------------------------

    def add_fact(self, fact: str, source: str = "conversation") -> None:
        """Speichert eine sachliche Angabe über den Benutzer.

        Wiederholt genannte Angaben erhöhen ihr Gewicht, statt mehrfach
        gespeichert zu werden (siehe Anforderung "Gedächtnisbildung").
        """

        facts: list[dict[str, Any]] = list(self._store.get("facts", []) or [])
        normalized = fact.strip()
        if not normalized:
            return

        for entry in facts:
            if entry.get("text", "").strip().lower() == normalized.lower():
                entry["weight"] = float(entry.get("weight", 1.0)) + 1.0
                entry["updated_at"] = time.time()
                self._store.update({"facts": facts, "updated_at": time.time()})
                return

        facts.append(
            {
                "text": normalized,
                "source": source,
                "weight": 1.0,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
        )
        self._store.update({"facts": facts, "updated_at": time.time()})

    def top_facts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Gibt die wichtigsten gespeicherten Angaben zurück."""

        facts = list(self._store.get("facts", []) or [])
        facts.sort(key=lambda entry: float(entry.get("weight", 0.0)), reverse=True)
        return facts[:limit]

    def remove_fact(self, text: str) -> bool:
        """Löscht eine gespeicherte Angabe."""

        facts = list(self._store.get("facts", []) or [])
        remaining = [entry for entry in facts if entry.get("text") != text]
        changed = len(remaining) != len(facts)
        if changed:
            self._store.update({"facts": remaining, "updated_at": time.time()})
        return changed

    # --- Gesamtsicht ---------------------------------------------------------

    def profile(self) -> dict[str, Any]:
        """Gibt das vollständige Profil zurück (für die Transparenzansicht)."""

        return dict(self._store.data)

    def reset(self) -> None:
        """Löscht das Benutzerprofil vollständig."""

        self._store.clear()
        self._store.update({"created_at": time.time(), "updated_at": time.time()})
