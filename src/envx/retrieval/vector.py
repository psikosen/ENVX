"""Dense vector retrieval (architecture §3.2 Path 2).

Brute-force cosine over an in-memory store, shaped like the eventual
``pgvectorscale`` StreamingDiskANN table. Swapping to DiskANN changes the
backend, not the caller.

The index pins an ``embedding_model_version``. Adding a vector produced by a
different model raises rather than silently poisoning recall — §4.3 requires
re-embedding whenever the model version differs, and a mixed index is the
failure mode that rule exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..embedding import cosine_similarity
from ._common import IndexedChunk, matches_scope


@dataclass(frozen=True)
class VectorResult:
    chunk_id: str
    score: float


class VectorIndex:
    def __init__(self, *, model_id: str, dim: int) -> None:
        self.model_id = model_id
        self.dim = dim
        self._chunks: dict[str, IndexedChunk] = {}
        self._vectors: dict[str, list[float]] = {}

    def __len__(self) -> int:
        return len(self._vectors)

    def get(self, chunk_id: str) -> IndexedChunk | None:
        return self._chunks.get(chunk_id)

    def add(
        self,
        chunk: IndexedChunk,
        vector: list[float],
        *,
        model_id: str | None = None,
    ) -> None:
        if model_id is not None and model_id != self.model_id:
            raise ValueError(
                f"embedding model mismatch: index is {self.model_id!r}, got {model_id!r}"
            )
        if len(vector) != self.dim:
            raise ValueError(f"dim mismatch: got {len(vector)}, index expects {self.dim}")
        self._chunks[chunk.chunk_id] = chunk
        self._vectors[chunk.chunk_id] = vector

    def remove(self, chunk_id: str) -> None:
        self._chunks.pop(chunk_id, None)
        self._vectors.pop(chunk_id, None)

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 50,
        **scope: object,
    ) -> list[VectorResult]:
        if len(query_vector) != self.dim:
            raise ValueError(f"query dim {len(query_vector)} != index dim {self.dim}")
        scored: list[tuple[float, str]] = []
        for chunk_id, vector in self._vectors.items():
            if not matches_scope(self._chunks[chunk_id], **scope):  # type: ignore[arg-type]
                continue
            score = cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append((score, chunk_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [VectorResult(chunk_id=cid, score=s) for s, cid in scored[:top_k]]
