"""Hybrid retrieval with RRF fusion (architecture §3.2, §3.3, §3.4).

Runs the lexical and dense paths, optionally accepts externally-computed
graph and visual path rankings, and fuses everything with Reciprocal Rank
Fusion. Marker soft-boosts are applied post-fusion (§3.4).

RRF is used rather than score normalization because the paths produce
incomparable scales — BM25 is unbounded, cosine is [-1,1], and graph hops
are ordinal. Rank is the only thing they agree on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ..embedding import EmbeddingBackend
from ._common import IndexedChunk
from .bm25 import BM25Index
from .vector import VectorIndex


@dataclass(frozen=True)
class RetrievalScope:
    client_id: str | None = None
    matter_id: str | None = None
    jurisdiction: str | None = None
    doc_types: tuple[str, ...] | None = None
    markers_any_of: tuple[str, ...] | None = None
    storage_tier: tuple[str, ...] = ("hot", "warm")
    confidence_gte: float | None = None

    def as_filters(self) -> dict[str, object]:
        return {
            "client_id": self.client_id,
            "matter_id": self.matter_id,
            "jurisdiction": self.jurisdiction,
            "doc_types": self.doc_types,
            "markers_any_of": self.markers_any_of,
            "storage_tier": self.storage_tier,
            "confidence_gte": self.confidence_gte,
        }


@dataclass(frozen=True)
class PathResult:
    """A ranking contributed by a path computed outside the retriever."""

    name: str
    ranking: tuple[tuple[str, float], ...]
    weight: float = 1.0


@dataclass
class ScoredChunk:
    chunk: IndexedChunk
    score: float
    per_path: dict[str, float] = field(default_factory=dict)
    rerank_score: float | None = None
    boost: float = 0.0

    @property
    def final_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.score


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[tuple[str, float]]],
    *,
    k: float = 60.0,
    weights: dict[str, float] | None = None,
) -> list[tuple[str, float, dict[str, float]]]:
    """Weighted RRF: ``sum over paths of weight / (k + rank)``.

    ``k=60`` is the value from the original Cormack et al. formulation and is
    what ParadeDB and most production stacks default to. It damps the tail so
    a single path can't dominate on rank-1 alone.
    """
    weights = weights or {}
    fused: dict[str, float] = {}
    per_path: dict[str, dict[str, float]] = {}
    for path_name, entries in rankings.items():
        weight = weights.get(path_name, 1.0)
        if weight == 0:
            continue
        for rank, (chunk_id, raw_score) in enumerate(entries, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + weight / (k + rank)
            per_path.setdefault(chunk_id, {})[path_name] = raw_score
    ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(cid, score, per_path.get(cid, {})) for cid, score in ordered]


class HybridRetriever:
    def __init__(
        self,
        *,
        bm25: BM25Index,
        vector: VectorIndex,
        embedder: EmbeddingBackend,
    ) -> None:
        if vector.model_id != embedder.model_id:
            raise ValueError(
                f"embedder {embedder.model_id!r} does not match vector index "
                f"{vector.model_id!r} — retrieval would compare incompatible vectors"
            )
        self.bm25 = bm25
        self.vector = vector
        self.embedder = embedder

    def lookup(self, chunk_id: str) -> IndexedChunk | None:
        return self.bm25.get(chunk_id) or self.vector.get(chunk_id)

    def retrieve(
        self,
        *,
        query: str,
        scope: RetrievalScope | None = None,
        top_k: int = 100,
        dense_query: str | None = None,
        query_expansions: Iterable[str] = (),
        weights: dict[str, float] | None = None,
        extra_paths: Sequence[PathResult] = (),
        soft_boost_markers: dict[str, float] | None = None,
    ) -> list[ScoredChunk]:
        scope = scope or RetrievalScope()
        filters = scope.as_filters()
        weights = dict(weights or {})

        rankings: dict[str, Sequence[tuple[str, float]]] = {}

        if weights.get("bm25", 1.0) != 0:
            hits = self.bm25.search(
                query,
                top_k=top_k,
                query_expansions=query_expansions,
                **filters,
            )
            rankings["bm25"] = [(h.chunk_id, h.score) for h in hits]

        if weights.get("dense", 1.0) != 0:
            vec = self.embedder.embed([dense_query or query])[0]
            hits_v = self.vector.search(vec, top_k=top_k, **filters)
            rankings["dense"] = [(h.chunk_id, h.score) for h in hits_v]

        for path in extra_paths:
            rankings[path.name] = path.ranking
            weights.setdefault(path.name, path.weight)

        boosts = soft_boost_markers or {}
        results: list[ScoredChunk] = []
        for chunk_id, fused_score, per_path in reciprocal_rank_fusion(
            rankings, weights=weights
        )[:top_k]:
            chunk = self.lookup(chunk_id)
            if chunk is None:
                continue
            boost = sum(bump for m, bump in boosts.items() if m in chunk.marker_array)
            results.append(
                ScoredChunk(
                    chunk=chunk,
                    score=fused_score + boost,
                    per_path=per_path,
                    boost=boost,
                )
            )
        results.sort(key=lambda sc: (-sc.score, sc.chunk.chunk_id))
        return results
