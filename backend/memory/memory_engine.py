"""Memory Engine – die zentrale Gedächtnis-API von AI-Orb.

Alle Module greifen ausschließlich über diese Klasse auf Erinnerungen zu;
direkte Datenbankzugriffe sind nicht erlaubt (Architekturvorgabe
"Memory API").

Die Engine entscheidet außerdem, **ob** eine Information überhaupt
langfristig gespeichert wird, erhöht die Wichtigkeit wiederholt
auftretender Informationen und lässt unwichtige Informationen über die Zeit
an Gewicht verlieren ("Vergessen").
"""

from __future__ import annotations

import time
from typing import Any

from backend.config import get_config
from backend.memory.conversation_memory import ConversationMemory
from backend.memory.knowledge_memory import KnowledgeMemory
from backend.memory.memory_index import MemoryIndex
from backend.memory.memory_search import MemorySearch, SearchResult
from backend.memory.memory_store import MemoryRecord, MemoryStore
from backend.memory.summary_engine import SummaryEngine
from backend.memory.task_memory import TaskMemory
from backend.memory.user_memory import UserMemory
from backend.system.logging_setup import get_logger
from backend.utils.text import tokenize

logger = get_logger(__name__)

# Begriffe, die auf dauerhaft relevante Aussagen hindeuten. Sie werden für
# die Entscheidung genutzt, ob eine Information gespeichert wird.
_RELEVANCE_MARKERS: tuple[str, ...] = (
    "projekt",
    "hausarbeit",
    "deadline",
    "frist",
    "termin",
    "ziel",
    "lernen",
    "merke",
    "wichtig",
    "immer",
    "nie",
    "bevorzug",
    "lieblings",
    "arbeite",
    "studiere",
    "heiße",
    "meine",
    "quelle",
    "literatur",
    "aufgabe",
)


class MemoryEngine:
    """Fassade über alle Gedächtnisarten von AI-Orb."""

    def __init__(self, provider_manager: Any | None = None) -> None:
        config = get_config()
        memory_config = config.section("memory")

        self._store = MemoryStore()
        self._index = MemoryIndex()
        self._index.rebuild(self._store.all())

        self._search = MemorySearch(self._store, self._index)
        self.summaries = SummaryEngine(provider_manager)

        self.conversations = ConversationMemory(self._store)
        self.knowledge = KnowledgeMemory(self._store)
        self.tasks = TaskMemory(self._store)
        self.user = UserMemory()

        self._min_content_length = int(memory_config.get("min_content_length", 12))
        self._forget_enabled = bool(memory_config.get("forgetting_enabled", True))
        self._forget_half_life_days = float(memory_config.get("forget_half_life_days", 90))
        self._forget_threshold = float(memory_config.get("forget_threshold", 0.15))

        logger.info(
            "Memory Engine bereit (%d Einträge, %d indizierte Begriffe).",
            self._store.count(),
            self._index.token_count,
        )

    # --- Speicherentscheidung ------------------------------------------------

    def is_worth_remembering(self, content: str) -> bool:
        """Entscheidet, ob eine Information langfristig gespeichert wird.

        Nicht jede Nachricht wird gespeichert. Gespeichert wird, was
        inhaltlich substanziell ist und auf dauerhaft relevante Aussagen
        hindeutet (Projekte, Ziele, Vorlieben, Fristen, Fachbegriffe).

        Args:
            content: Der zu bewertende Text.

        Returns:
            ``True``, wenn die Information gespeichert werden soll.
        """

        stripped = content.strip()
        if len(stripped) < self._min_content_length:
            return False

        tokens = tokenize(stripped)
        if len(tokens) < 3:
            return False

        lowered = stripped.lower()
        if any(marker in lowered for marker in _RELEVANCE_MARKERS):
            return True

        # Längere, inhaltsreiche Aussagen werden ebenfalls behalten.
        return len(tokens) >= 12

    # --- Schreiben -----------------------------------------------------------

    def remember(
        self,
        content: str,
        *,
        kind: str = "knowledge",
        tags: list[str] | None = None,
        project_id: str | None = None,
        source: str | None = None,
        certainty: str = "fakt",
        force: bool = False,
    ) -> MemoryRecord | None:
        """Speichert eine Information – oder verstärkt eine bestehende.

        Tritt eine inhaltlich sehr ähnliche Information erneut auf, wird
        kein Duplikat angelegt, sondern die Wichtigkeit des bestehenden
        Eintrags erhöht.

        Args:
            content: Zu speichernder Inhalt.
            kind: Art des Eintrags.
            tags: Schlagworte.
            project_id: Zugehöriges Projekt.
            source: Herkunft der Information.
            certainty: Sicherheitsgrad (``fakt``, ``annahme``,
                ``vermutung`` …).
            force: Umgeht die Relevanzprüfung.

        Returns:
            Der neue oder verstärkte Eintrag, oder ``None``, wenn die
            Information als nicht speicherwürdig verworfen wurde.
        """

        if not force and not self.is_worth_remembering(content):
            logger.debug("Information als nicht speicherwürdig verworfen.")
            return None

        existing = self._search.find_similar(content, kind=kind)
        if existing is not None:
            existing.importance += 1.0
            existing.updated_at = time.time()
            if project_id and existing.project_id is None:
                existing.project_id = project_id
            self._store.update(existing)
            self._index.add(existing)
            logger.debug("Bestehende Erinnerung verstärkt (Gewicht %.1f).", existing.importance)
            return existing

        record = MemoryRecord(
            kind=kind,
            content=content.strip(),
            tags=list(tags or []),
            project_id=project_id,
            metadata={"source": source, "certainty": certainty, "links": []},
        )
        self._store.add(record)
        self._index.add(record)
        logger.debug("Neue Erinnerung gespeichert (%s).", record.id)
        return record

    # --- Lesen ---------------------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        limit: int = 5,
        kind: str | None = None,
        project_id: str | None = None,
    ) -> list[SearchResult]:
        """Sucht relevante Erinnerungen zu einer Anfrage."""

        return self._search.search(query, limit=limit, kind=kind, project_id=project_id)

    def context_for(
        self, query: str, *, project_id: str | None = None, limit: int = 5
    ) -> dict[str, Any]:
        """Liefert den für eine KI-Anfrage relevanten Gedächtniskontext.

        Wird vor jeder Anfrage vom Cognitive Core aufgerufen und enthält
        passende Wissenseinträge, jüngste Gesprächszusammenfassungen sowie
        die wichtigsten Benutzerangaben.
        """

        matches = self.recall(query, limit=limit, project_id=project_id)
        return {
            "memories": [
                {
                    "content": result.record.content,
                    "kind": result.record.kind,
                    "certainty": result.record.metadata.get("certainty", "fakt"),
                    "relevance": round(result.score, 3),
                }
                for result in matches
            ],
            "conversations": self.conversations.as_context(limit=2, project_id=project_id),
            "user_facts": [fact["text"] for fact in self.user.top_facts(limit=5)],
            "open_tasks": [
                task.content for task in self.tasks.open_tasks(project_id=project_id)[:5]
            ],
        }

    def get(self, record_id: str) -> MemoryRecord | None:
        """Liest einen einzelnen Eintrag."""

        return self._store.get(record_id)

    def all(self, *, kind: str | None = None, project_id: str | None = None) -> list[MemoryRecord]:
        """Gibt alle Einträge zurück (für die Transparenzansicht)."""

        return self._store.filter(kind=kind, project_id=project_id)

    # --- Ändern und Löschen ---------------------------------------------------

    def edit(self, record_id: str, content: str) -> bool:
        """Ändert den Inhalt eines Eintrags (Transparenzanforderung)."""

        record = self._store.get(record_id)
        if record is None:
            return False
        record.content = content
        self._store.update(record)
        self._index.add(record)
        return True

    def forget(self, record_id: str) -> bool:
        """Löscht einen Eintrag endgültig."""

        self._index.remove(record_id)
        return self._store.delete(record_id)

    def forget_project(self, project_id: str) -> int:
        """Entfernt sämtliches Wissen zu einem Projekt."""

        records = self._store.filter(project_id=project_id)
        for record in records:
            self._index.remove(record.id)
        return self._store.delete_where(project_id=project_id)

    # --- Vergessen ------------------------------------------------------------

    def apply_forgetting(self) -> int:
        """Reduziert das Gewicht selten genutzter Einträge über die Zeit.

        Einträge, deren Gewicht unter die konfigurierte Schwelle fällt,
        werden entfernt. Das Verfahren ist konfigurierbar und kann über
        ``memory.forgetting_enabled`` in ``config.yaml`` abgeschaltet
        werden.

        Returns:
            Anzahl der entfernten Einträge.
        """

        if not self._forget_enabled:
            return 0

        now = time.time()
        half_life_seconds = max(1.0, self._forget_half_life_days * 86400.0)
        removed = 0

        for record in self._store.all():
            # Aufgaben und Benutzerangaben unterliegen nicht dem Vergessen.
            if record.kind == "task":
                continue

            age = max(0.0, now - record.updated_at)
            decayed = record.importance * (0.5 ** (age / half_life_seconds))

            if decayed < self._forget_threshold and record.access_count == 0:
                self._index.remove(record.id)
                self._store.delete(record.id)
                removed += 1
            elif abs(decayed - record.importance) > 0.01:
                record.importance = decayed
                self._store.update(record)

        if removed:
            logger.info("Vergessen: %d Einträge entfernt.", removed)
        return removed

    # --- Statistik -------------------------------------------------------------

    def statistics(self) -> dict[str, Any]:
        """Kennzahlen des Gedächtnisses für die Transparenzansicht."""

        records = self._store.all()
        by_kind: dict[str, int] = {}
        for record in records:
            by_kind[record.kind] = by_kind.get(record.kind, 0) + 1
        return {
            "total": len(records),
            "by_kind": by_kind,
            "indexed_terms": self._index.token_count,
            "storage_path": str(self._store._store.path),  # noqa: SLF001 - Transparenz
        }
