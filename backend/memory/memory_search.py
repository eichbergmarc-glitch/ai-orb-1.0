"""Semantische Suche über das Gedächtnis von AI-Orb.

Die Suche ist bewusst nicht auf reine Volltexttreffer beschränkt: Über die
Tokenisierung mit Stammformbildung und die Kosinus-Ähnlichkeit aus
:mod:`backend.utils.text` findet eine Anfrage wie "Mein Raspberry Projekt"
auch einen Eintrag "Projekt Smart Home mit Raspberry Pi".

Die Rangfolge berücksichtigt zusätzlich Wichtigkeit, Aktualität und
Zugriffshäufigkeit eines Eintrags.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from backend.memory.memory_index import MemoryIndex
from backend.memory.memory_store import MemoryRecord, MemoryStore
from backend.utils.text import cosine_similarity

# Halbwertszeit in Sekunden, nach der der Aktualitätsbonus eines Eintrags
# auf die Hälfte fällt (30 Tage).
_RECENCY_HALF_LIFE = 30 * 24 * 60 * 60.0


@dataclass
class SearchResult:
    """Ein Suchtreffer mit zugehöriger Bewertung."""

    record: MemoryRecord
    score: float
    similarity: float


class MemorySearch:
    """Führt semantische Suchen über den :class:`MemoryStore` aus."""

    def __init__(self, store: MemoryStore, index: MemoryIndex) -> None:
        self._store = store
        self._index = index

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kind: str | None = None,
        project_id: str | None = None,
        min_similarity: float = 0.05,
    ) -> list[SearchResult]:
        """Sucht die relevantesten Einträge zu einer Anfrage.

        Args:
            query: Suchtext in natürlicher Sprache.
            limit: Maximale Anzahl Treffer.
            kind: Optionale Einschränkung auf eine Eintragsart.
            project_id: Optionale Einschränkung auf ein Projekt. Wird ein
                Projekt angegeben, werden ausschließlich Einträge dieses
                Projekts sowie projektunabhängige Einträge berücksichtigt.
            min_similarity: Mindestähnlichkeit, ab der ein Eintrag als
                Treffer gilt.

        Returns:
            Absteigend nach Bewertung sortierte Trefferliste.
        """

        candidate_ids = self._index.candidates(query)
        pool = self._store.all()
        if candidate_ids:
            pool = [record for record in pool if record.id in candidate_ids]

        now = time.time()
        results: list[SearchResult] = []

        for record in pool:
            if kind is not None and record.kind != kind:
                continue
            if project_id is not None and record.project_id not in (None, project_id):
                continue

            similarity = cosine_similarity(query, f"{record.content} {' '.join(record.tags)}")
            if similarity < min_similarity:
                continue

            age = max(0.0, now - record.updated_at)
            recency = 0.5 ** (age / _RECENCY_HALF_LIFE)
            usage = min(1.0, record.access_count / 10.0)

            score = (
                similarity * 0.65
                + min(record.importance, 5.0) / 5.0 * 0.20
                + recency * 0.10
                + usage * 0.05
            )
            results.append(SearchResult(record=record, score=score, similarity=similarity))

        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    def find_similar(
        self, content: str, *, threshold: float = 0.82, kind: str | None = None
    ) -> MemoryRecord | None:
        """Findet einen inhaltlich nahezu identischen Eintrag.

        Wird von der Memory Engine genutzt, um Wiederholungen zu erkennen:
        Statt einen Duplikateintrag anzulegen, wird die Wichtigkeit des
        bestehenden Eintrags erhöht (siehe Anforderung "Gedächtnisbildung").
        """

        matches = self.search(content, limit=1, kind=kind, min_similarity=threshold)
        return matches[0].record if matches else None
