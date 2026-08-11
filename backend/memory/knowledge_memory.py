"""Knowledge Memory – Sachwissen, Projekte, Dokumente, Notizen.

Enthält inhaltliches Wissen, das über einzelne Gespräche hinaus relevant
bleibt: Notizen, Exzerpte, Dokumentbezüge, Code-Erkenntnisse und
Verknüpfungen zwischen diesen Elementen (Wissensgraph).
"""

from __future__ import annotations

from typing import Any

from backend.memory.memory_store import MemoryRecord, MemoryStore

KIND = "knowledge"


class KnowledgeMemory:
    """Verwaltet Wissenseinträge und deren Verknüpfungen."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def add(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        project_id: str | None = None,
        source: str | None = None,
        certainty: str = "fakt",
    ) -> MemoryRecord:
        """Legt einen Wissenseintrag an.

        Args:
            content: Der Wissensinhalt.
            tags: Schlagworte zur Filterung.
            project_id: Zugehöriges Projekt, falls projektbezogen.
            source: Quelle der Information (URL, Dateiname, Gespräch).
            certainty: Einordnung gemäß Reasoning Context – ``fakt``,
                ``annahme``, ``vermutung``, ``interpretation`` oder
                ``hypothese``. Unsichere Angaben werden dadurch dauerhaft
                als solche gekennzeichnet.
        """

        record = MemoryRecord(
            kind=KIND,
            content=content,
            tags=list(tags or []),
            project_id=project_id,
            metadata={"source": source, "certainty": certainty, "links": []},
        )
        return self._store.add(record)

    def link(self, record_id: str, target_id: str, relation: str = "bezieht_sich_auf") -> bool:
        """Verknüpft zwei Wissenseinträge miteinander.

        Die Verknüpfungen bilden gemeinsam den Wissensgraphen, über den
        Zusammenhänge zwischen Projekten, Dokumenten, Gesprächen und
        Aufgaben nachvollziehbar bleiben.

        Returns:
            ``True``, wenn beide Einträge existieren und verknüpft wurden.
        """

        record = self._store.get(record_id)
        target = self._store.get(target_id)
        if record is None or target is None:
            return False

        links: list[dict[str, str]] = list(record.metadata.get("links", []) or [])
        if not any(link.get("target") == target_id for link in links):
            links.append({"target": target_id, "relation": relation})
            record.metadata["links"] = links
            self._store.update(record)
        return True

    def linked(self, record_id: str) -> list[MemoryRecord]:
        """Gibt alle mit einem Eintrag verknüpften Einträge zurück."""

        record = self._store.get(record_id)
        if record is None:
            return []
        results: list[MemoryRecord] = []
        for link in record.metadata.get("links", []) or []:
            target = self._store.get(link.get("target", ""))
            if target is not None:
                results.append(target)
        return results

    def for_project(self, project_id: str) -> list[MemoryRecord]:
        """Gibt alles Wissen zu einem Projekt zurück."""

        return self._store.filter(kind=KIND, project_id=project_id)

    def graph(self, project_id: str | None = None) -> dict[str, Any]:
        """Erzeugt eine Graph-Darstellung (Knoten + Kanten) des Wissens.

        Wird von der Transparenzansicht und vom Dependency Graph der
        Project Intelligence Engine genutzt.
        """

        records = self._store.filter(kind=KIND, project_id=project_id)
        nodes = [
            {
                "id": record.id,
                "label": record.content[:80],
                "tags": record.tags,
                "certainty": record.metadata.get("certainty", "fakt"),
            }
            for record in records
        ]
        edges = [
            {
                "source": record.id,
                "target": link.get("target"),
                "relation": link.get("relation", "bezieht_sich_auf"),
            }
            for record in records
            for link in (record.metadata.get("links", []) or [])
        ]
        return {"nodes": nodes, "edges": edges}
