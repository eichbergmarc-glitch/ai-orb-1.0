"""Invertierter Index für die Memory Engine.

Der Index bildet Tokens auf Eintrags-IDs ab und ermöglicht damit eine
schnelle Vorauswahl, bevor die aufwendigere Ähnlichkeitsberechnung in
:mod:`backend.memory.memory_search` durchgeführt wird. Große Speicher
werden dadurch inkrementell statt vollständig durchsucht.
"""

from __future__ import annotations

import threading
from collections import defaultdict

from backend.memory.memory_store import MemoryRecord
from backend.utils.text import tokenize


class MemoryIndex:
    """Invertierter Token-Index über alle Gedächtniseinträge."""

    def __init__(self) -> None:
        self._index: dict[str, set[str]] = defaultdict(set)
        self._record_tokens: dict[str, set[str]] = {}
        self._lock = threading.RLock()

    def add(self, record: MemoryRecord) -> None:
        """Nimmt einen Eintrag in den Index auf (oder aktualisiert ihn)."""

        tokens = set(tokenize(f"{record.content} {' '.join(record.tags)}"))
        with self._lock:
            self.remove(record.id)
            self._record_tokens[record.id] = tokens
            for token in tokens:
                self._index[token].add(record.id)

    def remove(self, record_id: str) -> None:
        """Entfernt einen Eintrag aus dem Index."""

        with self._lock:
            tokens = self._record_tokens.pop(record_id, set())
            for token in tokens:
                bucket = self._index.get(token)
                if bucket is not None:
                    bucket.discard(record_id)
                    if not bucket:
                        self._index.pop(token, None)

    def rebuild(self, records: list[MemoryRecord]) -> None:
        """Baut den gesamten Index neu auf."""

        with self._lock:
            self._index.clear()
            self._record_tokens.clear()
            for record in records:
                self.add(record)

    def candidates(self, query: str) -> set[str]:
        """Liefert IDs aller Einträge, die mindestens ein Query-Token teilen.

        Findet der Index keine Übereinstimmung, wird eine leere Menge
        zurückgegeben; die Suche fällt dann auf einen vollständigen
        Durchlauf zurück (siehe :mod:`backend.memory.memory_search`).
        """

        tokens = set(tokenize(query))
        result: set[str] = set()
        with self._lock:
            for token in tokens:
                result |= self._index.get(token, set())
        return result

    @property
    def token_count(self) -> int:
        """Anzahl der indizierten unterschiedlichen Tokens."""

        with self._lock:
            return len(self._index)
