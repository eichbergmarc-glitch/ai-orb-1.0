"""Task Memory – offene Aufgaben, Erinnerungen und Langzeitaufgaben.

Dieses Modul speichert Aufgaben dauerhaft. Die aktive Bearbeitung und
Strukturierung von Aufgaben übernimmt der Task Manager des Cognitive Core
(:mod:`backend.cognitive.task_manager`); dieser greift ausschließlich über
die Memory API auf die hier abgelegten Daten zu.
"""

from __future__ import annotations

import time
from typing import Any

from backend.memory.memory_store import MemoryRecord, MemoryStore

KIND = "task"

#: Zulässige Aufgabenzustände gemäß Architekturvorgabe.
STATUSES: tuple[str, ...] = ("offen", "in_bearbeitung", "blockiert", "erledigt")


class TaskMemory:
    """Persistente Verwaltung von Aufgaben."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def add(
        self,
        title: str,
        *,
        project_id: str | None = None,
        priority: str = "normal",
        due: float | None = None,
        parent_id: str | None = None,
        notes: str = "",
    ) -> MemoryRecord:
        """Legt eine neue Aufgabe an."""

        record = MemoryRecord(
            kind=KIND,
            content=title,
            project_id=project_id,
            tags=["aufgabe"],
            metadata={
                "status": "offen",
                "priority": priority,
                "due": due,
                "parent_id": parent_id,
                "notes": notes,
                "blocked_reason": None,
                "completed_at": None,
            },
        )
        return self._store.add(record)

    def set_status(self, task_id: str, status: str, *, reason: str | None = None) -> bool:
        """Ändert den Status einer Aufgabe.

        Args:
            task_id: ID der Aufgabe.
            status: Einer der Werte aus :data:`STATUSES`.
            reason: Begründung, insbesondere bei ``blockiert``.

        Returns:
            ``True``, wenn die Aufgabe existiert und der Status gültig ist.
        """

        if status not in STATUSES:
            return False
        record = self._store.get(task_id)
        if record is None or record.kind != KIND:
            return False

        record.metadata["status"] = status
        if status == "blockiert":
            record.metadata["blocked_reason"] = reason
        if status == "erledigt":
            record.metadata["completed_at"] = time.time()
        self._store.update(record)
        return True

    def list(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Listet Aufgaben, optional gefiltert nach Status und Projekt."""

        records = self._store.filter(kind=KIND, project_id=project_id)
        if status is not None:
            records = [r for r in records if r.metadata.get("status") == status]
        records.sort(key=lambda record: record.created_at)
        return records

    def open_tasks(self, project_id: str | None = None) -> list[MemoryRecord]:
        """Alle noch nicht erledigten Aufgaben."""

        return [
            record
            for record in self.list(project_id=project_id)
            if record.metadata.get("status") != "erledigt"
        ]

    def subtasks(self, parent_id: str) -> list[MemoryRecord]:
        """Gibt alle Unteraufgaben einer Aufgabe zurück."""

        return [
            record
            for record in self.list()
            if record.metadata.get("parent_id") == parent_id
        ]

    def next_step(self, project_id: str | None = None) -> MemoryRecord | None:
        """Schlägt den sinnvollsten nächsten Schritt vor.

        Priorisiert nach: bereits begonnene Aufgaben, dann Fälligkeit,
        dann Priorität, dann Alter. Blockierte Aufgaben werden übersprungen.
        """

        candidates = [
            record
            for record in self.open_tasks(project_id=project_id)
            if record.metadata.get("status") != "blockiert"
        ]
        if not candidates:
            return None

        priority_rank = {"hoch": 0, "normal": 1, "niedrig": 2}

        def sort_key(record: MemoryRecord) -> tuple[int, float, int, float]:
            in_progress = 0 if record.metadata.get("status") == "in_bearbeitung" else 1
            due = record.metadata.get("due")
            due_value = float(due) if isinstance(due, (int, float)) else float("inf")
            priority = priority_rank.get(str(record.metadata.get("priority")), 1)
            return (in_progress, due_value, priority, record.created_at)

        return sorted(candidates, key=sort_key)[0]

    def as_overview(self, project_id: str | None = None) -> dict[str, Any]:
        """Erzeugt eine Übersicht über alle Aufgabenzustände."""

        records = self.list(project_id=project_id)
        counts = {status: 0 for status in STATUSES}
        for record in records:
            status = str(record.metadata.get("status", "offen"))
            if status in counts:
                counts[status] += 1
        return {"total": len(records), "by_status": counts}
