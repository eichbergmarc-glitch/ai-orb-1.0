"""Long Term Memory – die Langzeitschicht des Cognitive Core.

Diese Klasse ist eine dünne, fachlich orientierte Sicht auf die
:class:`~backend.memory.memory_engine.MemoryEngine`. Sie fügt keine eigene
Persistenz hinzu, sondern gruppiert den Zugriff nach den in der
Architekturvorgabe genannten Kategorien: Projekte, Gewohnheiten,
Vorlieben, Lernfortschritte, wissenschaftliche Themen, Literatur und
Wissensgraph.

Das Langzeitgedächtnis wird transparent verwaltet: Der Benutzer kann es
vollständig einsehen, bearbeiten und löschen.
"""

from __future__ import annotations

from typing import Any

from backend.memory.memory_engine import MemoryEngine
from backend.memory.memory_store import MemoryRecord

#: Fachliche Kategorien des Langzeitgedächtnisses.
CATEGORIES: tuple[str, ...] = (
    "projekt",
    "gewohnheit",
    "vorliebe",
    "lernfortschritt",
    "wissenschaft",
    "literatur",
)


class LongTermMemory:
    """Kategorisierte Sicht auf das dauerhafte Wissen des Orb."""

    def __init__(self, memory: MemoryEngine) -> None:
        self._memory = memory

    def store(
        self,
        category: str,
        content: str,
        *,
        project_id: str | None = None,
        source: str | None = None,
        certainty: str = "fakt",
    ) -> MemoryRecord | None:
        """Speichert eine Information in einer Kategorie.

        Args:
            category: Eine der Kategorien aus :data:`CATEGORIES`.
            content: Der Inhalt.
            project_id: Zugehöriges Projekt, falls projektbezogen.
            source: Herkunft der Information.
            certainty: Sicherheitsgrad der Aussage.

        Returns:
            Der gespeicherte Eintrag, oder ``None``, wenn die Information
            als nicht speicherwürdig eingestuft wurde.
        """

        tags = [category] if category in CATEGORIES else [category, "sonstiges"]
        return self._memory.remember(
            content,
            kind="knowledge",
            tags=tags,
            project_id=project_id,
            source=source,
            certainty=certainty,
        )

    def by_category(self, category: str, project_id: str | None = None) -> list[MemoryRecord]:
        """Gibt alle Einträge einer Kategorie zurück."""

        return [
            record
            for record in self._memory.all(kind="knowledge", project_id=project_id)
            if category in record.tags
        ]

    def recall(self, query: str, *, limit: int = 5, project_id: str | None = None) -> list[MemoryRecord]:
        """Sucht relevante Langzeiterinnerungen."""

        return [
            result.record
            for result in self._memory.recall(query, limit=limit, project_id=project_id)
        ]

    def knowledge_graph(self, project_id: str | None = None) -> dict[str, Any]:
        """Gibt den Wissensgraphen zurück (Knoten und Kanten)."""

        return self._memory.knowledge.graph(project_id=project_id)

    def overview(self) -> dict[str, Any]:
        """Übersicht über das Langzeitgedächtnis (Transparenzansicht)."""

        counts = {category: len(self.by_category(category)) for category in CATEGORIES}
        return {
            "categories": counts,
            "statistics": self._memory.statistics(),
            "user_profile": self._memory.user.profile(),
        }

    def edit(self, record_id: str, content: str) -> bool:
        """Ändert einen Eintrag (Transparenzanforderung)."""

        return self._memory.edit(record_id, content)

    def delete(self, record_id: str) -> bool:
        """Löscht einen Eintrag endgültig."""

        return self._memory.forget(record_id)

    def maintenance(self) -> int:
        """Führt den Vergessensvorgang aus.

        Returns:
            Anzahl der entfernten Einträge.
        """

        return self._memory.apply_forgetting()
