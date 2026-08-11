"""Conversation Memory – frühere Gespräche und deren Zusammenfassungen.

Speichert nicht jede einzelne Nachricht dauerhaft: Laufende Gespräche
liegen im Working Memory des Cognitive Core; hier landen ausschließlich
verdichtete Gesprächszusammenfassungen sowie explizit als wichtig
eingestufte Aussagen.
"""

from __future__ import annotations

import time
from typing import Any

from backend.memory.memory_store import MemoryRecord, MemoryStore

KIND = "conversation"


class ConversationMemory:
    """Verwaltet Gesprächserinnerungen."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def add_summary(
        self,
        summary: str,
        *,
        session_id: str,
        project_id: str | None = None,
        message_count: int = 0,
    ) -> MemoryRecord:
        """Legt die Zusammenfassung eines abgeschlossenen Gesprächs ab."""

        record = MemoryRecord(
            kind=KIND,
            content=summary,
            project_id=project_id,
            tags=["gespräch"],
            metadata={
                "session_id": session_id,
                "message_count": message_count,
                "summarized_at": time.time(),
            },
        )
        return self._store.add(record)

    def recent(self, limit: int = 5, project_id: str | None = None) -> list[MemoryRecord]:
        """Gibt die zuletzt gespeicherten Gesprächszusammenfassungen zurück."""

        records = self._store.filter(kind=KIND, project_id=project_id)
        records.sort(key=lambda record: record.updated_at, reverse=True)
        return records[:limit]

    def for_session(self, session_id: str) -> list[MemoryRecord]:
        """Gibt alle Erinnerungen einer bestimmten Sitzung zurück."""

        return [
            record
            for record in self._store.filter(kind=KIND)
            if record.metadata.get("session_id") == session_id
        ]

    def as_context(self, limit: int = 3, project_id: str | None = None) -> list[dict[str, Any]]:
        """Bereitet Gesprächserinnerungen als Kontext für eine KI-Anfrage auf."""

        return [
            {
                "content": record.content,
                "age_days": round((time.time() - record.updated_at) / 86400.0, 1),
            }
            for record in self.recent(limit=limit, project_id=project_id)
        ]
