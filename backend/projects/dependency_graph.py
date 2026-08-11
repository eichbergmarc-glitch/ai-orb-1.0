"""Dependency Graph – der Projektgraph.

Verbindet Dokumente, Literatur, Aufgaben, Personen, Orte, Kapitel, Quellen,
Notizen und Fragestellungen miteinander. Dadurch entstehen nachvollziehbare
Zusammenhänge: Welche Quelle stützt welches Kapitel? Welche Aufgabe hängt
an welchem Dokument?

Der Graph wird bei Bedarf aus dem Projektgedächtnis aufgebaut und nicht
dauerhaft dupliziert.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from backend.memory.memory_engine import MemoryEngine
from backend.projects.project_memory import ProjectMemory

#: Zulässige Knotenarten des Projektgraphen.
NODE_TYPES: tuple[str, ...] = (
    "dokument",
    "literatur",
    "aufgabe",
    "person",
    "ort",
    "kapitel",
    "quelle",
    "notiz",
    "fragestellung",
)


@dataclass
class GraphNode:
    """Ein Knoten im Projektgraphen."""

    id: str
    type: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "label": self.label, "data": self.data}


@dataclass
class GraphEdge:
    """Eine gerichtete Kante zwischen zwei Knoten."""

    source: str
    target: str
    relation: str = "bezieht_sich_auf"

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "relation": self.relation}


class DependencyGraph:
    """Baut und durchsucht den Projektgraphen."""

    def __init__(self, project_memory: ProjectMemory, memory: MemoryEngine) -> None:
        self._projects = project_memory
        self._memory = memory

    def build(self, project_id: str) -> tuple[list[GraphNode], list[GraphEdge]]:
        """Baut den vollständigen Graphen eines Projekts auf.

        Returns:
            Ein Tupel aus Knoten- und Kantenliste.
        """

        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        project = self._projects.get(project_id)
        if project is None:
            return [], []

        # Dokumente und Literatur.
        for section, node_type in (("files", "dokument"), ("literature", "literatur")):
            for entry in self._projects.entries(project_id, section):
                node_id = str(entry.get("id"))
                nodes[node_id] = GraphNode(
                    id=node_id,
                    type=node_type,
                    label=str(entry.get("name") or entry.get("text") or node_id),
                    data={"path": entry.get("path"), "source": entry.get("source")},
                )
                for link in entry.get("links", []) or []:
                    target = str(link.get("target", ""))
                    if target:
                        edges.append(
                            GraphEdge(
                                source=node_id,
                                target=target,
                                relation=str(link.get("relation", "bezug")),
                            )
                        )

        # Notizen, Gliederungen, Entscheidungen, offene Fragen.
        section_types = {
            "notes": "notiz",
            "outlines": "kapitel",
            "decisions": "notiz",
            "open_questions": "fragestellung",
        }
        for section, node_type in section_types.items():
            for entry in self._projects.entries(project_id, section):
                node_id = str(entry.get("id"))
                nodes[node_id] = GraphNode(
                    id=node_id,
                    type=node_type,
                    label=str(entry.get("text", ""))[:80] or node_id,
                    data={"section": section},
                )

        # Aufgaben aus der Memory Engine.
        for task in self._memory.tasks.list(project_id=project_id):
            nodes[task.id] = GraphNode(
                id=task.id,
                type="aufgabe",
                label=task.content[:80],
                data={"status": task.metadata.get("status")},
            )
            parent_id = task.metadata.get("parent_id")
            if parent_id:
                edges.append(GraphEdge(source=str(parent_id), target=task.id, relation="teilaufgabe"))

        # Wissenseinträge und deren Verknüpfungen.
        for record in self._memory.knowledge.for_project(project_id):
            nodes[record.id] = GraphNode(
                id=record.id,
                type="quelle" if record.metadata.get("source") else "notiz",
                label=record.content[:80],
                data={"certainty": record.metadata.get("certainty")},
            )
            for link in record.metadata.get("links", []) or []:
                target = str(link.get("target", ""))
                if target:
                    edges.append(
                        GraphEdge(
                            source=record.id,
                            target=target,
                            relation=str(link.get("relation", "bezieht_sich_auf")),
                        )
                    )

        # Kanten auf unbekannte Knoten verwerfen, damit der Graph konsistent bleibt.
        valid_edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]
        return list(nodes.values()), valid_edges

    def as_dict(self, project_id: str) -> dict[str, Any]:
        """Gibt den Graphen in serialisierbarer Form zurück."""

        nodes, edges = self.build(project_id)
        return {
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in edges],
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    def neighbours(self, project_id: str, node_id: str) -> list[GraphNode]:
        """Gibt alle direkt verbundenen Knoten zurück."""

        nodes, edges = self.build(project_id)
        index = {node.id: node for node in nodes}
        connected: list[GraphNode] = []
        for edge in edges:
            if edge.source == node_id and edge.target in index:
                connected.append(index[edge.target])
            elif edge.target == node_id and edge.source in index:
                connected.append(index[edge.source])
        return connected

    def path_between(self, project_id: str, start_id: str, end_id: str) -> list[str]:
        """Findet den kürzesten Zusammenhang zwischen zwei Elementen.

        Returns:
            Die Knoten-IDs des Pfades, oder eine leere Liste, wenn kein
            Zusammenhang besteht.
        """

        _, edges = self.build(project_id)
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.source].append(edge.target)
            adjacency[edge.target].append(edge.source)

        if start_id not in adjacency:
            return []

        queue: deque[list[str]] = deque([[start_id]])
        visited = {start_id}
        while queue:
            path = queue.popleft()
            current = path[-1]
            if current == end_id:
                return path
            for neighbour in adjacency[current]:
                if neighbour not in visited:
                    visited.add(neighbour)
                    queue.append([*path, neighbour])
        return []

    def isolated_nodes(self, project_id: str) -> list[GraphNode]:
        """Findet Elemente ohne jede Verknüpfung.

        Hilfreich, um auf noch nicht eingeordnete Quellen oder Notizen
        hinzuweisen.
        """

        nodes, edges = self.build(project_id)
        connected = {edge.source for edge in edges} | {edge.target for edge in edges}
        return [node for node in nodes if node.id not in connected]
