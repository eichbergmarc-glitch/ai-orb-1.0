"""Persistenter Speicher der Memory Engine.

Der Store kennt keine Semantik der gespeicherten Inhalte – er verwaltet
ausschließlich :class:`MemoryRecord`-Objekte und deren Persistenz in
``data/memory.json``. Sämtliche fachliche Logik (was gespeichert wird, wie
gesucht wird, wann vergessen wird) liegt in den darüberliegenden Modulen.

Alle Daten werden ausschließlich lokal gespeichert.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from backend.utils.store import JsonStore


@dataclass
class MemoryRecord:
    """Ein einzelner Gedächtniseintrag.

    Attributes:
        id: Eindeutige Kennung.
        kind: Art des Eintrags (``conversation``, ``user``, ``knowledge``,
            ``task`` …). Bestimmt, welches Fachmodul den Eintrag verwaltet.
        content: Der eigentliche Textinhalt.
        tags: Freie Schlagworte zur Filterung.
        project_id: Zugehöriges Projekt, falls der Eintrag projektbezogen
            ist. Projektwissen bleibt dadurch sauber getrennt.
        importance: Aktuelles Gewicht des Eintrags (steigt bei
            Wiederholung, sinkt durch Vergessen).
        created_at: Unix-Zeitstempel der Erstellung.
        updated_at: Unix-Zeitstempel der letzten Änderung.
        access_count: Wie oft der Eintrag bereits abgerufen wurde.
        metadata: Zusätzliche, frei belegbare Felder.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = "knowledge"
    content: str = ""
    tags: list[str] = field(default_factory=list)
    project_id: str | None = None
    importance: float = 1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialisiert den Eintrag als JSON-taugliches Dict."""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        """Erzeugt einen Eintrag aus einem zuvor serialisierten Dict."""

        known = {key: data.get(key) for key in cls.__dataclass_fields__ if key in data}
        record = cls(**known)  # type: ignore[arg-type]
        if not isinstance(record.tags, list):
            record.tags = []
        if not isinstance(record.metadata, dict):
            record.metadata = {}
        return record


class MemoryStore:
    """Verwaltet alle :class:`MemoryRecord`-Objekte und deren Persistenz."""

    def __init__(self, filename: str = "memory.json") -> None:
        self._store = JsonStore(filename, default={"records": []})
        self._lock = threading.RLock()
        self._records: dict[str, MemoryRecord] = {}
        self._load_records()

    def _load_records(self) -> None:
        raw_records = self._store.get("records", []) or []
        with self._lock:
            self._records = {}
            for raw in raw_records:
                if isinstance(raw, dict) and raw.get("id"):
                    record = MemoryRecord.from_dict(raw)
                    self._records[record.id] = record

    def _persist(self) -> None:
        with self._lock:
            serialized = [record.to_dict() for record in self._records.values()]
        self._store.set("records", serialized)

    # --- CRUD ---------------------------------------------------------------

    def add(self, record: MemoryRecord) -> MemoryRecord:
        """Fügt einen neuen Eintrag hinzu und speichert ihn."""

        with self._lock:
            self._records[record.id] = record
        self._persist()
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        """Liest einen Eintrag und erhöht dessen Zugriffszähler."""

        with self._lock:
            record = self._records.get(record_id)
            if record is not None:
                record.access_count += 1
        if record is not None:
            self._persist()
        return record

    def update(self, record: MemoryRecord) -> MemoryRecord:
        """Aktualisiert einen bestehenden Eintrag."""

        record.updated_at = time.time()
        with self._lock:
            self._records[record.id] = record
        self._persist()
        return record

    def delete(self, record_id: str) -> bool:
        """Löscht einen Eintrag endgültig.

        Returns:
            ``True``, wenn ein Eintrag entfernt wurde.
        """

        with self._lock:
            existed = self._records.pop(record_id, None) is not None
        if existed:
            self._persist()
        return existed

    def all(self) -> list[MemoryRecord]:
        """Gibt alle Einträge zurück (Kopie der internen Liste)."""

        with self._lock:
            return list(self._records.values())

    def filter(
        self,
        *,
        kind: str | None = None,
        project_id: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        """Filtert Einträge nach Art, Projekt und/oder Tags."""

        required_tags = set(tags or [])
        results: list[MemoryRecord] = []
        for record in self.all():
            if kind is not None and record.kind != kind:
                continue
            if project_id is not None and record.project_id != project_id:
                continue
            if required_tags and not required_tags.issubset(set(record.tags)):
                continue
            results.append(record)
        return results

    def delete_where(
        self, *, kind: str | None = None, project_id: str | None = None
    ) -> int:
        """Löscht alle Einträge, die den angegebenen Kriterien entsprechen.

        Ermöglicht dem Benutzer, Projektwissen vollständig zu entfernen
        (Transparenzanforderung).

        Returns:
            Anzahl der gelöschten Einträge.
        """

        targets = self.filter(kind=kind, project_id=project_id)
        with self._lock:
            for record in targets:
                self._records.pop(record.id, None)
        if targets:
            self._persist()
        return len(targets)

    def count(self) -> int:
        """Anzahl aller gespeicherten Einträge."""

        with self._lock:
            return len(self._records)
