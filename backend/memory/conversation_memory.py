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

    def sitzung_festhalten(
        self,
        summary: str,
        *,
        session_id: str,
        project_id: str | None = None,
        message_count: int = 0,
    ) -> MemoryRecord | None:
        """Hält den Stand einer LAUFENDEN Sitzung fest - und aktualisiert ihn.

        Der Unterschied zu :meth:`add_summary` ist der Zeitpunkt. Jene
        Methode ist für den Abschluss gedacht: einmal am Ende, ein Eintrag.
        Genau darin lag das Problem.

        Im Gedächtnis des Benutzers standen am 19.08.2026 zweihundert-
        zweiundzwanzig Einträge - und **keine einzige**
        Gesprächszusammenfassung. Der Grund: Geschrieben wurde sie nur
        beim sauberen Herunterfahren, und ein Sprachassistent auf einem
        Arbeitsrechner wird nicht sauber heruntergefahren. Er wird
        geschlossen, neu gestartet, sein Fenster weggeklickt. Alles, was
        besprochen wurde, war damit beim nächsten Start weg - daher „er
        kann sich nicht an Themen erinnern, die schon behandelt wurden".

        Deshalb wird jetzt schon während des Gesprächs festgehalten, und
        zwar bei jeder Verdichtung des Verlaufs. Damit daraus keine Kette
        halber Zusammenfassungen wird, ersetzt ein neuer Stand den alten
        derselben Sitzung.

        Returns:
            Der angelegte oder aktualisierte Eintrag, oder ``None``, wenn
            nichts festzuhalten war.
        """

        knapp = " ".join(str(summary or "").split())
        if not knapp:
            return None

        for record in self._store.filter(kind=KIND):
            if record.metadata.get("session_id") != session_id:
                continue
            record.content = knapp
            record.updated_at = time.time()
            record.metadata["message_count"] = message_count
            record.metadata["summarized_at"] = time.time()
            if project_id and record.project_id is None:
                record.project_id = project_id
            self._store.update(record)
            return record

        return self.add_summary(
            knapp,
            session_id=session_id,
            project_id=project_id,
            message_count=message_count,
        )

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
