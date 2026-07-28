"""Cross-encoder reranking (architecture §3.3).

§12: don't skip the reranker. Published gains are 15-25pp Hit@1 and it is
the single highest-leverage component after contextual enrichment.

``HTTPReranker`` targets a local text-embeddings-inference or vLLM ``/rerank``
endpoint (BGE-reranker-v2-m3, Qwen3-Reranker, Jina) and also speaks the
Cohere/Voyage rerank JSON shape. ``HashCrossEncoderReranker`` is the offline
fallback so the pipeline runs end-to-end without a GPU.
"""

from __future__ import annotations

from typing import Protocol, Sequence

import httpx

from ..embedding import HashingEmbedding, cosine_similarity
from .hybrid import ScoredChunk


class Reranker(Protocol):
    model_id: str

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]: ...


def _reordered(
    candidates: Sequence[ScoredChunk],
    scores: Sequence[float],
    top_k: int,
) -> list[ScoredChunk]:
    ranked = [
        ScoredChunk(
            chunk=cand.chunk,
            score=cand.score,
            per_path=dict(cand.per_path),
            boost=cand.boost,
            rerank_score=score,
        )
        for cand, score in zip(candidates, scores)
    ]
    ranked.sort(key=lambda sc: (-(sc.rerank_score or 0.0), sc.chunk.chunk_id))
    return ranked[:top_k]


class HashCrossEncoderReranker:
    """Offline stand-in: lexical similarity between query and full chunk text.

    Reranks against ``text_raw`` rather than ``text_contextual`` — the
    contextual prefix is identical across every chunk in a document, so
    scoring it would wash out exactly the distinctions reranking exists to
    make.
    """

    model_id = "envx-hash-rerank/1"

    def __init__(self, *, dim: int = 512) -> None:
        self._embedder = HashingEmbedding(dim=dim)

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        vectors = self._embedder.embed([query] + [c.chunk.text_raw for c in candidates])
        query_vec = vectors[0]
        scores = [cosine_similarity(query_vec, v) for v in vectors[1:]]
        return _reordered(candidates, scores, top_k)


class HTTPReranker:
    """Cross-encoder over HTTP.

    Tries the TEI/vLLM ``/rerank`` shape first and falls back to the
    Cohere-style ``results``/``relevance_score`` shape, since local servers
    and hosted APIs disagree on the response envelope.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        path: str = "/rerank",
    ) -> None:
        self.model_id = model
        self._url = base_url.rstrip("/") + path
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[ScoredChunk],
        top_k: int,
    ) -> list[ScoredChunk]:
        if not candidates:
            return []
        documents = [c.chunk.text_raw for c in candidates]
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                self._url,
                headers=self._headers,
                json={
                    "model": self.model_id,
                    "query": query,
                    "documents": documents,
                    "top_n": len(documents),
                },
            )
        resp.raise_for_status()
        scores = _parse_rerank_scores(resp.json(), len(documents))
        return _reordered(candidates, scores, top_k)


def _parse_rerank_scores(payload: object, count: int) -> list[float]:
    scores = [0.0] * count
    rows: list[dict] = []
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
    elif isinstance(payload, dict):
        raw = payload.get("results") or payload.get("data") or []
        rows = [r for r in raw if isinstance(r, dict)]
    for row in rows:
        idx = row.get("index")
        score = row.get("relevance_score", row.get("score"))
        if isinstance(idx, int) and 0 <= idx < count and isinstance(score, (int, float)):
            scores[idx] = float(score)
    return scores
