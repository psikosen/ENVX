"""Plan executor (architecture §6).

Compiles a ``RetrievalPlan`` into path invocations, fuses, reranks, and
enforces the response contract. Returns evidence carrying block ids, page
numbers, and region ids so citation enforcement is structural rather than a
prompt request (§6, §12).

If the plan demands provenance the evidence can't supply — ``require_region_ids``
against chunks with no region — the executor drops those items and reports
the count rather than handing the LLM uncitable text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ..graph import KnowledgeGraph
from ..retrieval import (
    HybridRetriever,
    PathResult,
    Reranker,
    RetrievalScope,
    ScoredChunk,
)
from ..visual import VisualRetriever
from .plan import RetrievalPlan


@dataclass(frozen=True)
class EvidenceItem:
    chunk_id: str
    doc_id: str
    page_number: int
    region_id: str | None
    region_type: str | None
    text_raw: str
    score: float
    markers: tuple[str, ...]
    paths: tuple[str, ...]

    def as_citation(self) -> dict[str, Any]:
        return {
            "block_id": self.chunk_id,
            "doc_id": self.doc_id,
            "page": self.page_number,
            "region_id": self.region_id,
        }


@dataclass
class ExecutionResult:
    plan: RetrievalPlan
    evidence: list[EvidenceItem]
    path_hit_counts: dict[str, int] = field(default_factory=dict)
    dropped_low_confidence: int = 0
    dropped_missing_provenance: int = 0
    reranked: bool = False

    @property
    def citations(self) -> list[dict[str, Any]]:
        return [item.as_citation() for item in self.evidence]


class PlanExecutor:
    def __init__(
        self,
        *,
        retriever: HybridRetriever,
        reranker: Reranker | None = None,
        graph: KnowledgeGraph | None = None,
        visual: VisualRetriever | None = None,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.graph = graph
        self.visual = visual

    def execute(self, plan: RetrievalPlan) -> ExecutionResult:
        bm25_path = plan.path("bm25")
        dense_path = plan.path("dense")
        visual_path = plan.path("visual")

        # Every scored path needs a query string; fall back across paths so a
        # plan specifying only one still drives the others.
        query = next(
            (p.query for p in (bm25_path, dense_path, visual_path) if p is not None),
            "",
        )
        if not query:
            return ExecutionResult(plan=plan, evidence=[])

        weights: dict[str, float] = {
            "bm25": bm25_path.weight if bm25_path else 0.0,
            "dense": dense_path.weight if dense_path else 0.0,
        }

        extra: list[PathResult] = []
        if plan.graph is not None and self.graph is not None:
            extra.append(self._graph_path(plan))
        if visual_path is not None and self.visual is not None:
            extra.append(self._visual_path(plan, visual_path.query, visual_path.weight))

        scope = RetrievalScope(
            client_id=plan.scope.client_id,
            matter_id=plan.scope.matter_id,
            jurisdiction=plan.scope.jurisdiction,
            doc_types=plan.scope.doc_types,
            markers_any_of=plan.scope.markers_any_of,
            storage_tier=plan.scope.storage_tier,
            confidence_gte=plan.scope.confidence_gte,
        )

        hits = self.retriever.retrieve(
            query=bm25_path.query if bm25_path else query,
            dense_query=dense_path.query if dense_path else None,
            scope=scope,
            top_k=plan.top_k,
            query_expansions=bm25_path.query_expansions if bm25_path else (),
            weights=weights,
            extra_paths=extra,
            soft_boost_markers=plan.soft_boost_markers,
        )

        path_hits = {
            name: sum(1 for h in hits if name in h.per_path)
            for name in ("bm25", "dense", "graph", "visual")
        }

        reranked = False
        if self.reranker is not None and plan.rerank is not None:
            hits = self.reranker.rerank(
                query=query, candidates=hits, top_k=plan.rerank.top_k
            )
            reranked = True

        hits, dropped_conf = self._filter_confidence(hits, plan.response.min_confidence)
        evidence, dropped_prov = self._to_evidence(hits, plan)

        return ExecutionResult(
            plan=plan,
            evidence=evidence,
            path_hit_counts={k: v for k, v in path_hits.items() if v},
            dropped_low_confidence=dropped_conf,
            dropped_missing_provenance=dropped_prov,
            reranked=reranked,
        )

    def _graph_path(self, plan: RetrievalPlan) -> PathResult:
        assert plan.graph is not None and self.graph is not None
        reachable = self.graph.documents_reachable(
            start_entity_names=plan.graph.start_entities,
            relations=plan.graph.relations or None,
            max_hops=plan.graph.max_hops,
        )
        doc_scores = {doc_id: 1.0 / hops for doc_id, hops in reachable if hops > 0}
        # Graph works at document granularity; project onto the chunks of
        # those documents so fusion stays chunk-level.
        ranking: list[tuple[str, float]] = []
        for chunk_id, chunk in self.retriever.bm25._chunks.items():
            score = doc_scores.get(chunk.doc_id)
            if score is not None:
                ranking.append((chunk_id, score))
        ranking.sort(key=lambda pair: (-pair[1], pair[0]))
        return PathResult(name="graph", ranking=tuple(ranking), weight=plan.graph.weight)

    def _visual_path(self, plan: RetrievalPlan, query: str, weight: float) -> PathResult:
        assert self.visual is not None
        matches = self.visual.search(
            query=query,
            doc_types=plan.scope.doc_types,
            top_k=plan.top_k,
            force=True,
        )
        # Map (doc_id, page) hits onto chunks on that page.
        page_scores = {(m.doc_id, m.page_number): m.score for m in matches}
        ranking: list[tuple[str, float]] = []
        for chunk_id, chunk in self.retriever.bm25._chunks.items():
            score = page_scores.get((chunk.doc_id, chunk.page_number))
            if score is not None:
                ranking.append((chunk_id, score))
        ranking.sort(key=lambda pair: (-pair[1], pair[0]))
        return PathResult(name="visual", ranking=tuple(ranking), weight=weight)

    @staticmethod
    def _filter_confidence(
        hits: Sequence[ScoredChunk], minimum: float
    ) -> tuple[list[ScoredChunk], int]:
        if minimum <= 0:
            return list(hits), 0
        kept = [h for h in hits if h.chunk.confidence >= minimum]
        return kept, len(hits) - len(kept)

    @staticmethod
    def _to_evidence(
        hits: Sequence[ScoredChunk], plan: RetrievalPlan
    ) -> tuple[list[EvidenceItem], int]:
        evidence: list[EvidenceItem] = []
        dropped = 0
        for hit in hits:
            chunk = hit.chunk
            if plan.response.require_region_ids and not chunk.region_id:
                dropped += 1
                continue
            evidence.append(
                EvidenceItem(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    page_number=chunk.page_number,
                    region_id=chunk.region_id,
                    region_type=chunk.region_type,
                    text_raw=chunk.text_raw,
                    score=hit.final_score,
                    markers=tuple(chunk.marker_array),
                    paths=tuple(sorted(hit.per_path)),
                )
            )
        return evidence, dropped
