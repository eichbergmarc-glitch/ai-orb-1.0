"""Kontextmanager – verwaltet mehrere gleichzeitig aktive Kontexte.

Der Orb hält verschiedene Kontexte strikt getrennt:

* **Projektkontext** – z. B. "Hausarbeit Mittelalter"
* **Arbeitskontext** – geöffnete Programme (VS Code, Browser, PDF)
* **Gesprächskontext** – die laufende Unterhaltung
* **Lernkontext** – das Thema, mit dem sich der Benutzer gerade befasst

Alle Kontexte bleiben getrennt; ein Kontextwechsel vermischt niemals
Wissen. Der Cognitive Core fragt hier ab, welcher Kontext für eine Anfrage
relevant ist.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

#: Die vier Kontextarten gemäß Architekturvorgabe.
CONTEXT_TYPES: tuple[str, ...] = ("projekt", "arbeit", "gespräch", "lernen")


@dataclass
class Context:
    """Ein einzelner Kontext."""

    type: str
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    active: bool = False
    created_at: float = field(default_factory=time.time)
    activated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "data": self.data,
            "active": self.active,
            "created_at": self.created_at,
            "activated_at": self.activated_at,
        }


class ContextManager:
    """Verwaltet alle Kontexte und deren Aktivierung."""

    def __init__(self) -> None:
        self._contexts: dict[str, dict[str, Context]] = {kind: {} for kind in CONTEXT_TYPES}
        self._active: dict[str, str | None] = {kind: None for kind in CONTEXT_TYPES}
        self._lock = threading.RLock()

    def set(self, context_type: str, name: str, data: dict[str, Any] | None = None) -> Context:
        """Legt einen Kontext an oder aktualisiert ihn und aktiviert ihn.

        Args:
            context_type: Eine der Arten aus :data:`CONTEXT_TYPES`.
            name: Bezeichner des Kontexts (z. B. Projektname).
            data: Beliebige Zusatzdaten des Kontexts.

        Returns:
            Der aktivierte Kontext.
        """

        if context_type not in self._contexts:
            self._contexts[context_type] = {}
            self._active[context_type] = None

        with self._lock:
            existing = self._contexts[context_type].get(name)
            if existing is None:
                existing = Context(type=context_type, name=name, data=dict(data or {}))
                self._contexts[context_type][name] = existing
            elif data:
                existing.data.update(data)

            previous = self._active.get(context_type)
            if previous and previous != name:
                other = self._contexts[context_type].get(previous)
                if other is not None:
                    other.active = False

            existing.active = True
            existing.activated_at = time.time()
            self._active[context_type] = name
            return existing

    def active(self, context_type: str) -> Context | None:
        """Gibt den aktiven Kontext einer Art zurück."""

        with self._lock:
            name = self._active.get(context_type)
            if name is None:
                return None
            return self._contexts.get(context_type, {}).get(name)

    def active_project_id(self) -> str | None:
        """Bequemlichkeitsfunktion: die ID des aktiven Projekts."""

        context = self.active("projekt")
        if context is None:
            return None
        project_id = context.data.get("project_id")
        return str(project_id) if project_id else context.name

    def clear(self, context_type: str) -> None:
        """Deaktiviert den aktiven Kontext einer Art."""

        with self._lock:
            name = self._active.get(context_type)
            if name:
                context = self._contexts.get(context_type, {}).get(name)
                if context is not None:
                    context.active = False
            self._active[context_type] = None

    def list(self, context_type: str) -> list[Context]:
        """Listet alle bekannten Kontexte einer Art."""

        with self._lock:
            return list(self._contexts.get(context_type, {}).values())

    def describe(self) -> dict[str, Any]:
        """Beschreibt alle aktiven Kontexte.

        Beantwortet die Transparenzfrage "Welcher Kontext ist aktiv?".
        """

        with self._lock:
            return {
                kind: (context.to_dict() if (context := self.active(kind)) else None)
                for kind in self._contexts
            }

    def summary_text(self) -> str:
        """Formuliert die aktiven Kontexte als kurzen Text für Modellanfragen."""

        parts: list[str] = []
        for kind in CONTEXT_TYPES:
            context = self.active(kind)
            if context is None:
                continue
            parts.append(f"{kind.capitalize()}: {context.name}")
        if not parts:
            return ""
        return "Aktive Kontexte – " + "; ".join(parts)
