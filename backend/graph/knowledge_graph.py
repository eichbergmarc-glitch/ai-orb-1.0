"""Persönlicher Knowledge Graph (Phase 7).

Das Gedächtnis speichert einzelne Aussagen. Der Graph speichert, **wie sie
zusammenhängen**. Für Forschungsarbeit ist das der eigentliche Gewinn: Nicht
„was habe ich über Bismarck gespeichert", sondern „welche Quellen widersprechen
dieser These, und in welchem Projekt kam das vor".

Umgesetzt als gerichteter Graph mit typisierten Knoten und typisierten Kanten.
Bewusst ohne Graphdatenbank: Der Bestand eines einzelnen Benutzers umfasst
Tausende, nicht Millionen von Knoten. Dafür genügt eine JSON-Datei mit einem
Nachbarschaftsverzeichnis im Speicher – das ist sofort einsatzbereit,
nachvollziehbar und lässt sich vom Benutzer im Klartext einsehen.

Zwei Eigenschaften sind für die Nutzung entscheidend:

**Beziehungen haben eine Richtung und eine Gegenrichtung.** „A zitiert B"
heißt aus Sicht von B „wird zitiert von A". Beim Durchlaufen wird beides
berücksichtigt, sonst fände man von einer Quelle aus nie die Arbeiten, die
sie verwenden.

**Widerspruch ist eine eigene Beziehung.** Das ist kein Beiwerk: Wer
wissenschaftlich arbeitet, muss sehen, wo sich Positionen widersprechen.
:meth:`KnowledgeGraph.contradictions` gibt genau diese Kanten zurück.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from backend.system.logging_setup import get_logger
from backend.utils.paths import get_data_dir
from backend.utils.store import JsonStore

logger = get_logger(__name__)


class NodeType(Enum):
    """Die Arten von Knoten."""

    PERSON = "person"
    EVENT = "ereignis"
    PLACE = "ort"
    BOOK = "buch"
    ARTICLE = "artikel"
    SOURCE = "quelle"
    PROJECT = "projekt"
    NOTE = "notiz"
    QUESTION = "forschungsfrage"
    DOCUMENT = "dokument"
    CONCEPT = "begriff"

    @classmethod
    def parse(cls, value: str) -> "NodeType | None":
        cleaned = value.strip().lower()
        for member in cls:
            if member.value == cleaned or member.name.lower() == cleaned:
                return member
        return None


class EdgeType(Enum):
    """Die Arten von Beziehungen."""

    MENTIONS = "erwaehnt"
    CONTRADICTS = "widerspricht"
    SUPPORTS = "unterstuetzt"
    BELONGS_TO = "gehoert_zu"
    RELEVANT_FOR = "relevant_fuer"
    CITES = "zitiert"
    FOLLOWS = "folgt_auf"

    @classmethod
    def parse(cls, value: str) -> "EdgeType | None":
        cleaned = value.strip().lower().replace(" ", "_").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
        for member in cls:
            if member.value == cleaned or member.name.lower() == cleaned:
                return member
        return None

    def inverse_label(self) -> str:
        """Wie die Beziehung aus Sicht des Ziels heißt."""

        return {
            EdgeType.MENTIONS: "wird erwähnt von",
            EdgeType.CONTRADICTS: "wird widersprochen von",
            EdgeType.SUPPORTS: "wird unterstützt von",
            EdgeType.BELONGS_TO: "enthält",
            EdgeType.RELEVANT_FOR: "hat als relevant",
            EdgeType.CITES: "wird zitiert von",
            EdgeType.FOLLOWS: "geht voraus",
        }[self]

    def label(self) -> str:
        """Wie die Beziehung im Klartext heißt."""

        return {
            EdgeType.MENTIONS: "erwähnt",
            EdgeType.CONTRADICTS: "widerspricht",
            EdgeType.SUPPORTS: "unterstützt",
            EdgeType.BELONGS_TO: "gehört zu",
            EdgeType.RELEVANT_FOR: "ist relevant für",
            EdgeType.CITES: "zitiert",
            EdgeType.FOLLOWS: "folgt auf",
        }[self]

    @property
    def is_symmetric(self) -> bool:
        """Ob die Beziehung in beide Richtungen gleich gilt.

        Widerspruch ist symmetrisch: Wenn A B widerspricht, widerspricht B
        auch A. Zitieren ist es nicht.
        """

        return self is EdgeType.CONTRADICTS


@dataclass
class Node:
    """Ein Knoten im Graphen."""

    node_id: str
    type: NodeType
    label: str
    #: Freie Zusatzangaben: Jahr, Autor, Signatur, Fundstelle.
    attributes: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "type": self.type.value,
            "label": self.label,
            "attributes": self.attributes,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def describe(self) -> str:
        """Der Knoten als lesbarer Satz."""

        parts = [f"{self.label} ({self.type.value})"]
        for key in ("autor", "jahr", "ort", "seite"):
            value = self.attributes.get(key)
            if value:
                parts.append(f"{key}: {value}")
        if self.notes:
            parts.append(self.notes[:200])
        return ", ".join(parts)


@dataclass
class Edge:
    """Eine gerichtete Beziehung zwischen zwei Knoten."""

    edge_id: str
    source: str
    target: str
    type: EdgeType
    #: Warum diese Beziehung besteht – die Belegstelle.
    evidence: str = ""
    #: Wie sicher, von 0.0 bis 1.0.
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source": self.source,
            "target": self.target,
            "type": self.type.value,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 2),
            "created_at": self.created_at,
        }


class KnowledgeGraph:
    """Verwaltet Knoten, Beziehungen und Abfragen darauf."""

    def __init__(self, *, store_filename: str = "graph/knowledge_graph.json") -> None:
        self._store = JsonStore(store_filename, default={"nodes": {}, "edges": {}})

        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}

        # Nachbarschaftsverzeichnis. Wird beim Laden aufgebaut und bei jeder
        # Änderung nachgeführt – ohne es müsste jede Abfrage alle Kanten
        # durchlaufen.
        self._outgoing: dict[str, set[str]] = {}
        self._incoming: dict[str, set[str]] = {}

        self._load()

    # --- Laden und Speichern --------------------------------------------------------

    def _load(self) -> None:
        for raw in (self._store.get("nodes", {}) or {}).values():
            node_type = NodeType.parse(str(raw.get("type", "")))
            node_id = str(raw.get("node_id", ""))
            if node_type is None or not node_id:
                continue
            self._nodes[node_id] = Node(
                node_id=node_id,
                type=node_type,
                label=str(raw.get("label", "")),
                attributes=dict(raw.get("attributes", {}) or {}),
                notes=str(raw.get("notes", "")),
                created_at=float(raw.get("created_at", 0.0)),
                updated_at=float(raw.get("updated_at", 0.0)),
            )

        for raw in (self._store.get("edges", {}) or {}).values():
            edge_type = EdgeType.parse(str(raw.get("type", "")))
            edge_id = str(raw.get("edge_id", ""))
            source = str(raw.get("source", ""))
            target = str(raw.get("target", ""))

            # Eine Kante ohne ihre beiden Knoten ist wertlos und würde bei
            # jeder Abfrage ins Leere führen.
            if edge_type is None or not edge_id or source not in self._nodes or target not in self._nodes:
                continue

            edge = Edge(
                edge_id=edge_id,
                source=source,
                target=target,
                type=edge_type,
                evidence=str(raw.get("evidence", "")),
                confidence=float(raw.get("confidence", 1.0)),
                created_at=float(raw.get("created_at", 0.0)),
            )
            self._edges[edge_id] = edge
            self._index(edge)

        if self._nodes:
            logger.info(
                "Knowledge Graph geladen: %d Knoten, %d Beziehungen.",
                len(self._nodes),
                len(self._edges),
            )

    def _index(self, edge: Edge) -> None:
        self._outgoing.setdefault(edge.source, set()).add(edge.edge_id)
        self._incoming.setdefault(edge.target, set()).add(edge.edge_id)

    def _unindex(self, edge: Edge) -> None:
        self._outgoing.get(edge.source, set()).discard(edge.edge_id)
        self._incoming.get(edge.target, set()).discard(edge.edge_id)

    def _save(self) -> None:
        self._store.update(
            {
                "nodes": {node_id: node.to_dict() for node_id, node in self._nodes.items()},
                "edges": {edge_id: edge.to_dict() for edge_id, edge in self._edges.items()},
            }
        )

    # --- Knoten -----------------------------------------------------------------------

    def add_node(
        self,
        label: str,
        node_type: str | NodeType,
        *,
        attributes: dict[str, Any] | None = None,
        notes: str = "",
        merge: bool = True,
    ) -> tuple[Node | None, str]:
        """Legt einen Knoten an.

        Args:
            label: Wie er heißt.
            node_type: Seine Art.
            attributes: Zusatzangaben.
            notes: Freitext.
            merge: Ob ein vorhandener Knoten gleichen Namens und gleicher Art
                ergänzt statt verdoppelt wird. Ohne das entstünde bei
                wiederholter Erwähnung derselben Person eine Kette von
                Doppeln, und der Graph verlöre seinen Zweck.

        Returns:
            Der Knoten und eine Meldung im Klartext.
        """

        cleaned = label.strip()
        if len(cleaned) < 2:
            return None, "Der Name ist zu kurz."

        resolved = node_type if isinstance(node_type, NodeType) else NodeType.parse(str(node_type))
        if resolved is None:
            return None, (
                f"'{node_type}' ist keine bekannte Knotenart. Möglich sind: "
                + ", ".join(member.value for member in NodeType)
            )

        if merge:
            existing = self.find_node(cleaned, resolved)
            if existing is not None:
                if attributes:
                    existing.attributes.update(attributes)
                if notes:
                    existing.notes = (existing.notes + "\n" + notes).strip()
                existing.updated_at = time.time()
                self._save()
                return existing, f"'{cleaned}' war bereits vorhanden und wurde ergänzt."

        node = Node(
            node_id=uuid.uuid4().hex[:12],
            type=resolved,
            label=cleaned,
            attributes=dict(attributes or {}),
            notes=notes.strip(),
        )
        self._nodes[node.node_id] = node
        self._save()
        return node, f"'{cleaned}' als {resolved.value} aufgenommen."

    def find_node(self, label: str, node_type: NodeType | None = None) -> Node | None:
        """Sucht einen Knoten nach Namen, ohne Rücksicht auf Groß- und Kleinschreibung."""

        needle = label.strip().lower()
        for node in self._nodes.values():
            if node.label.lower() == needle and (node_type is None or node.type is node_type):
                return node
        return None

    def get_node(self, node_id: str) -> Node | None:
        """Holt einen Knoten über seine Kennung."""

        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> tuple[bool, str]:
        """Entfernt einen Knoten samt aller Beziehungen daran."""

        node = self._nodes.pop(node_id, None)
        if node is None:
            return False, "Diesen Knoten gibt es nicht."

        touched = list(self._outgoing.get(node_id, set()) | self._incoming.get(node_id, set()))
        for edge_id in touched:
            edge = self._edges.pop(edge_id, None)
            if edge is not None:
                self._unindex(edge)

        self._outgoing.pop(node_id, None)
        self._incoming.pop(node_id, None)
        self._save()
        return True, f"'{node.label}' und {len(touched)} Beziehungen entfernt."

    # --- Beziehungen ---------------------------------------------------------------------

    def connect(
        self,
        source_label: str,
        edge_type: str | EdgeType,
        target_label: str,
        *,
        source_type: str | NodeType = NodeType.NOTE,
        target_type: str | NodeType = NodeType.NOTE,
        evidence: str = "",
        confidence: float = 1.0,
    ) -> tuple[Edge | None, str]:
        """Verbindet zwei Knoten und legt fehlende dabei an.

        Diese Bequemlichkeit ist Absicht: Beim Erfassen einer Beziehung soll
        man nicht erst zwei Knoten anlegen müssen. Wer Genaueres will, legt
        die Knoten vorher mit :meth:`add_node` an.
        """

        resolved = edge_type if isinstance(edge_type, EdgeType) else EdgeType.parse(str(edge_type))
        if resolved is None:
            return None, (
                f"'{edge_type}' ist keine bekannte Beziehung. Möglich sind: "
                + ", ".join(member.value for member in EdgeType)
            )

        source, source_message = self.add_node(source_label, source_type)
        target, target_message = self.add_node(target_label, target_type)

        if source is None:
            return None, f"'{source_label}' ließ sich nicht anlegen: {source_message}"
        if target is None:
            return None, f"'{target_label}' ließ sich nicht anlegen: {target_message}"

        if source.node_id == target.node_id:
            return None, "Ein Knoten kann nicht mit sich selbst verbunden werden."

        # Dieselbe Beziehung nicht doppelt anlegen.
        for edge_id in self._outgoing.get(source.node_id, set()):
            existing = self._edges.get(edge_id)
            if existing and existing.target == target.node_id and existing.type is resolved:
                if evidence and evidence not in existing.evidence:
                    existing.evidence = (existing.evidence + "; " + evidence).strip("; ")
                    self._save()
                return existing, "Diese Beziehung bestand bereits."

        edge = Edge(
            edge_id=uuid.uuid4().hex[:12],
            source=source.node_id,
            target=target.node_id,
            type=resolved,
            evidence=evidence.strip(),
            confidence=max(0.0, min(1.0, confidence)),
        )
        self._edges[edge.edge_id] = edge
        self._index(edge)
        self._save()

        return edge, f"'{source.label}' {resolved.label()} '{target.label}'."

    def disconnect(self, edge_id: str) -> tuple[bool, str]:
        """Entfernt eine Beziehung."""

        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return False, "Diese Beziehung gibt es nicht."
        self._unindex(edge)
        self._save()
        return True, "Die Beziehung wurde entfernt."

    # --- Abfragen ---------------------------------------------------------------------------

    def neighbors(self, node_id: str) -> list[dict[str, Any]]:
        """Alle direkten Nachbarn eines Knotens, mit Richtungsangabe."""

        found: list[dict[str, Any]] = []

        for edge_id in self._outgoing.get(node_id, set()):
            edge = self._edges.get(edge_id)
            other = self._nodes.get(edge.target) if edge else None
            if edge and other:
                found.append(
                    {
                        "edge_id": edge.edge_id,
                        "relation": edge.type.label(),
                        "direction": "ausgehend",
                        "node": other.to_dict(),
                        "evidence": edge.evidence,
                    }
                )

        for edge_id in self._incoming.get(node_id, set()):
            edge = self._edges.get(edge_id)
            other = self._nodes.get(edge.source) if edge else None
            if edge and other:
                found.append(
                    {
                        "edge_id": edge.edge_id,
                        "relation": edge.type.inverse_label(),
                        "direction": "eingehend",
                        "node": other.to_dict(),
                        "evidence": edge.evidence,
                    }
                )

        return found

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Sucht Knoten nach Name, Notizen und Zusatzangaben."""

        needle = query.strip().lower()
        if len(needle) < 2:
            return []

        scored: list[tuple[float, Node]] = []
        for node in self._nodes.values():
            score = 0.0
            if needle == node.label.lower():
                score = 3.0
            elif needle in node.label.lower():
                score = 2.0
            elif needle in node.notes.lower():
                score = 1.0
            elif any(needle in str(value).lower() for value in node.attributes.values()):
                score = 0.8
            if score > 0:
                scored.append((score, node))

        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [node.to_dict() for _, node in scored[:limit]]

    def related(self, label: str, *, depth: int = 2, limit: int = 30) -> list[dict[str, Any]]:
        """Findet alles, was mit einem Knoten zusammenhängt.

        Läuft in die Breite, damit Nahes vor Fernem kommt. Die Tiefe ist
        begrenzt, weil in einem gut gepflegten Graphen ab Tiefe drei fast
        alles mit fast allem verbunden ist – und eine Antwort, die alles
        enthält, sagt nichts.
        """

        start = self.find_node(label)
        if start is None:
            return []

        seen: set[str] = {start.node_id}
        frontier: list[tuple[str, int, str]] = [(start.node_id, 0, "")]
        found: list[dict[str, Any]] = []

        while frontier and len(found) < limit:
            node_id, distance, path = frontier.pop(0)
            if distance >= max(1, min(4, depth)):
                continue

            for neighbor in self.neighbors(node_id):
                other_id = str(neighbor["node"]["node_id"])
                if other_id in seen:
                    continue
                seen.add(other_id)

                trail = f"{path} → {neighbor['relation']}" if path else str(neighbor["relation"])
                found.append(
                    {
                        **neighbor,
                        "distance": distance + 1,
                        "path": trail,
                    }
                )
                frontier.append((other_id, distance + 1, trail))

                if len(found) >= limit:
                    break

        return found

    def contradictions(self) -> list[dict[str, Any]]:
        """Alle Widersprüche im Graphen.

        Für wissenschaftliches Arbeiten der wichtigste Blick: Wo stehen
        Positionen gegeneinander?
        """

        found: list[dict[str, Any]] = []
        for edge in self._edges.values():
            if edge.type is not EdgeType.CONTRADICTS:
                continue
            source = self._nodes.get(edge.source)
            target = self._nodes.get(edge.target)
            if source and target:
                found.append(
                    {
                        "edge_id": edge.edge_id,
                        "left": source.to_dict(),
                        "right": target.to_dict(),
                        "evidence": edge.evidence,
                        "confidence": edge.confidence,
                    }
                )
        return found

    def context_for(self, query: str, *, limit: int = 8, max_characters: int = 2000) -> str:
        """Stellt Graphwissen für eine Modellanfrage zusammen."""

        matches = self.search(query, limit=3)
        if not matches:
            return ""

        lines: list[str] = ["Was du über dieses Thema in deinem Wissensnetz hast:"]
        used = 0

        for match in matches:
            node = self._nodes.get(str(match["node_id"]))
            if node is None:
                continue

            lines.append(f"\n{node.describe()}")
            used += len(lines[-1])

            for neighbor in self.neighbors(node.node_id)[:limit]:
                other = neighbor["node"]
                entry = f"  – {neighbor['relation']}: {other['label']} ({other['type']})"
                if neighbor.get("evidence"):
                    entry += f" [{str(neighbor['evidence'])[:120]}]"
                lines.append(entry)
                used += len(entry)
                if used >= max_characters:
                    break

            if used >= max_characters:
                break

        return "\n".join(lines)

    # --- Verwaltung -------------------------------------------------------------------------

    def nodes(self, node_type: str | NodeType | None = None) -> list[dict[str, Any]]:
        """Alle Knoten, wahlweise einer Art."""

        resolved: NodeType | None = None
        if node_type is not None:
            resolved = node_type if isinstance(node_type, NodeType) else NodeType.parse(str(node_type))

        return [
            node.to_dict()
            for node in sorted(self._nodes.values(), key=lambda item: item.label.lower())
            if resolved is None or node.type is resolved
        ]

    def edges(self) -> list[dict[str, Any]]:
        """Alle Beziehungen."""

        return [edge.to_dict() for edge in self._edges.values()]

    def export(self, path: Path | None = None) -> Path:
        """Schreibt den Graphen in eine Datei zum Mitnehmen.

        Die Vorgabe verlangt, dass der Benutzer seine Daten einsehen,
        löschen **und exportieren** kann.
        """

        target = path or (get_data_dir() / "graph" / f"export-{int(time.time())}.json")
        target.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "exported_at": time.time(),
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "nodes": [node.to_dict() for node in self._nodes.values()],
            "edges": [edge.to_dict() for edge in self._edges.values()],
        }
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        logger.info("Knowledge Graph exportiert nach %s", target)
        return target

    def clear(self) -> int:
        """Leert den Graphen vollständig."""

        count = len(self._nodes)
        self._nodes.clear()
        self._edges.clear()
        self._outgoing.clear()
        self._incoming.clear()
        self._save()
        logger.info("Der Knowledge Graph wurde geleert (%d Knoten).", count)
        return count

    def statistics(self) -> dict[str, Any]:
        """Kennzahlen des Graphen."""

        by_node_type: dict[str, int] = {}
        for node in self._nodes.values():
            by_node_type[node.type.value] = by_node_type.get(node.type.value, 0) + 1

        by_edge_type: dict[str, int] = {}
        for edge in self._edges.values():
            by_edge_type[edge.type.value] = by_edge_type.get(edge.type.value, 0) + 1

        isolated = [
            node.label
            for node in self._nodes.values()
            if not self._outgoing.get(node.node_id) and not self._incoming.get(node.node_id)
        ]

        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "by_node_type": by_node_type,
            "by_edge_type": by_edge_type,
            "isolated": len(isolated),
            "contradictions": len(self.contradictions()),
        }

    def status(self) -> dict[str, Any]:
        """Statusangaben für die Transparenzansicht."""

        return {**self.statistics(), "store": str(self._store.path)}

    def __len__(self) -> int:
        return len(self._nodes)


def node_types() -> list[str]:
    """Die möglichen Knotenarten."""

    return [member.value for member in NodeType]


def edge_types() -> list[str]:
    """Die möglichen Beziehungsarten."""

    return [member.value for member in EdgeType]


def describe_types() -> str:
    """Beschreibt Knoten- und Beziehungsarten für das Sprachmodell."""

    return (
        "Knotenarten: " + ", ".join(node_types()) + ".\n"
        "Beziehungsarten: " + ", ".join(edge_types()) + "."
    )


def parse_iterable(values: Iterable[Any]) -> list[str]:
    """Wandelt eine beliebige Aufzählung in eine Liste von Texten."""

    return [str(value).strip() for value in values if str(value).strip()]
