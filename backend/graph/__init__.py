"""Persönlicher Knowledge Graph (Phase 7).

Speichert nicht nur, *was* AI-Orb weiß, sondern *wie es zusammenhängt*:
Personen, Ereignisse, Quellen, Projekte und Forschungsfragen als Knoten,
verbunden durch typisierte Beziehungen wie „zitiert", „widerspricht" oder
„gehört zu".

Alles liegt lokal in ``data/graph/`` und lässt sich einsehen, löschen und
exportieren.
"""

from backend.graph.knowledge_graph import (
    Edge,
    EdgeType,
    KnowledgeGraph,
    Node,
    NodeType,
    describe_types,
    edge_types,
    node_types,
)

__all__ = [
    "Edge",
    "EdgeType",
    "KnowledgeGraph",
    "Node",
    "NodeType",
    "describe_types",
    "edge_types",
    "node_types",
]
