"""Knowledge graph layer (architecture §3.2 Path 4).

LightRAG-style entity graph built from canonicalized KIE entities. Answers
the multi-hop questions the other paths can't: "claims filed by entities
related to ACME on properties flagged for asbestos".

Nodes are entities, documents, and risks. Edges carry the ``doc_id`` that
justified them, so every graph-derived assertion traces back to a source
document — a graph edge with no provenance is not admissible.

Graph hits are returned as a ranking that feeds the hybrid retriever as an
``extra_path``, keeping fusion in one place.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..entities import EntityResolver, extract_entities_from_kie


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_type: str  # entity | document | risk
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    doc_id: str


# KIE role -> edge relation.
_ROLE_RELATIONS: dict[str, str] = {
    "seller": "sold",
    "buyer": "purchased",
    "insured": "insured_party_of",
    "insurer": "insurer_of",
    "inspector": "inspected",
    "inspector_firm": "inspected",
    "preparer_firm": "prepared",
    "provider": "treated_in",
    "property": "subject_of",
}


class KnowledgeGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._out: dict[str, list[GraphEdge]] = {}
        self._in: dict[str, list[GraphEdge]] = {}

    def __len__(self) -> int:
        return len(self._nodes)

    @property
    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[GraphEdge]:
        return [e for edges in self._out.values() for e in edges]

    def node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def add_node(self, node: GraphNode) -> GraphNode:
        existing = self._nodes.get(node.node_id)
        if existing is not None:
            return existing
        self._nodes[node.node_id] = node
        self._out.setdefault(node.node_id, [])
        self._in.setdefault(node.node_id, [])
        return node

    def add_edge(self, edge: GraphEdge) -> None:
        if edge.source not in self._nodes or edge.target not in self._nodes:
            raise KeyError("both endpoints must be added as nodes first")
        if edge in self._out[edge.source]:
            return
        self._out[edge.source].append(edge)
        self._in[edge.target].append(edge)

    def incident(
        self,
        node_id: str,
        *,
        relations: Iterable[str] | None = None,
        direction: str = "both",
    ) -> list[GraphEdge]:
        if direction == "out":
            edges = list(self._out.get(node_id, []))
        elif direction == "in":
            edges = list(self._in.get(node_id, []))
        else:
            edges = list(self._out.get(node_id, [])) + list(self._in.get(node_id, []))
        if relations is not None:
            wanted = set(relations)
            edges = [e for e in edges if e.relation in wanted]
        return edges

    def traverse(
        self,
        start_node_ids: Iterable[str],
        *,
        relations: Iterable[str] | None = None,
        max_hops: int = 2,
    ) -> list[tuple[GraphNode, int]]:
        """BFS from the seeds, returning ``(node, hop_distance)`` pairs.

        Seeds are excluded from the output; only what they reach is
        interesting. Relation filtering applies at every hop.
        """
        seen = set(start_node_ids)
        queue: deque[tuple[str, int]] = deque((s, 0) for s in seen)
        reached: list[tuple[GraphNode, int]] = []
        while queue:
            node_id, depth = queue.popleft()
            if depth >= max_hops:
                continue
            for edge in self.incident(node_id, relations=relations):
                other = edge.target if edge.source == node_id else edge.source
                if other in seen:
                    continue
                seen.add(other)
                node = self._nodes.get(other)
                if node is not None:
                    reached.append((node, depth + 1))
                queue.append((other, depth + 1))
        return reached

    def find_entities(self, *, name: str) -> list[GraphNode]:
        needle = name.casefold().strip()
        return [
            n for n in self._nodes.values()
            if n.node_type == "entity" and needle in n.label.casefold()
        ]

    def documents_reachable(
        self,
        *,
        start_entity_names: Iterable[str],
        relations: Iterable[str] | None = None,
        max_hops: int = 2,
    ) -> list[tuple[str, int]]:
        """Doc ids reachable from named entities, with hop distance.

        This is the graph path's contribution to retrieval: closer documents
        rank higher, and the hop count is the raw score handed to RRF.
        """
        seeds = [n.node_id for name in start_entity_names for n in self.find_entities(name=name)]
        if not seeds:
            return []
        out: list[tuple[str, int]] = []
        for node, hops in self.traverse(seeds, relations=relations, max_hops=max_hops):
            if node.node_type == "document":
                out.append((node.attributes.get("doc_id", node.node_id), hops))
        out.sort(key=lambda pair: (pair[1], pair[0]))
        return out


def build_graph_from_kie(
    *,
    doc_id: str,
    kie_payload: dict[str, Any],
    resolver: EntityResolver,
    graph: KnowledgeGraph | None = None,
) -> KnowledgeGraph:
    graph = graph or KnowledgeGraph()

    doc_node_id = f"doc:{doc_id}"
    graph.add_node(
        GraphNode(
            node_id=doc_node_id,
            node_type="document",
            label=str(kie_payload.get("doc_type", "document")),
            attributes={
                "doc_id": doc_id,
                "jurisdiction": kie_payload.get("jurisdiction"),
            },
        )
    )

    resolved: dict[str, str] = {}
    for mention in extract_entities_from_kie(kie_payload, doc_id=doc_id):
        entity = resolver.resolve(mention).entity
        node_id = f"entity:{entity.canonical_id}"
        graph.add_node(
            GraphNode(
                node_id=node_id,
                node_type="entity",
                label=entity.display_name,
                attributes={"entity_type": entity.entity_type},
            )
        )
        resolved[mention.entity_type] = node_id
        relation = _ROLE_RELATIONS.get(mention.entity_type)
        if relation:
            graph.add_edge(
                GraphEdge(
                    source=node_id,
                    target=doc_node_id,
                    relation=relation,
                    doc_id=doc_id,
                )
            )

    # flagged_for: attach the property to each hazard so "every property with
    # an asbestos finding" is a one-hop query.
    hazards: list[str] = []
    for key in ("hazards_disclosed", "hazmat_observed"):
        for item in kie_payload.get(key) or []:
            if isinstance(item, dict) and isinstance(item.get("type"), str):
                if item["type"].strip():
                    hazards.append(item["type"].strip().casefold())
    for sample in kie_payload.get("sampling_results") or []:
        if isinstance(sample, dict) and sample.get("exceeds_standard"):
            analyte = sample.get("analyte")
            if isinstance(analyte, str) and analyte.strip():
                hazards.append(analyte.strip().casefold())

    property_node = resolved.get("property")
    for hazard in sorted(set(hazards)):
        risk_id = f"risk:{hazard}"
        graph.add_node(GraphNode(node_id=risk_id, node_type="risk", label=hazard))
        graph.add_edge(
            GraphEdge(source=doc_node_id, target=risk_id, relation="reports", doc_id=doc_id)
        )
        if property_node:
            graph.add_edge(
                GraphEdge(
                    source=property_node,
                    target=risk_id,
                    relation="flagged_for",
                    doc_id=doc_id,
                )
            )
    return graph
