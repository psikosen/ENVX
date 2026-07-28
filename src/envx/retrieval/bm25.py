"""BM25 lexical retrieval (architecture §3.2 Path 1).

Real Okapi BM25 over ``text_contextual``, not ``ts_rank`` — §12 is explicit
that tsvector ranking is not BM25 and shouldn't be pretended into one.
Production swaps this for ``pg_search`` (ParadeDB/Tantivy) or
``pg_textsearch``; the method surface here matches what those adapters will
expose so callers don't change.

This path is what catches policy numbers, parcel IDs, case citations, and
hazard-lexicon terms that dense retrieval blurs away.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from ._common import IndexedChunk, matches_scope


_WORD_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.casefold())


@dataclass(frozen=True)
class BM25Result:
    chunk_id: str
    score: float


class BM25Index:
    """In-memory Okapi BM25. Defaults match pg_search (k1=1.2, b=0.75)."""

    def __init__(self, *, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._chunks: dict[str, IndexedChunk] = {}
        self._tokens: dict[str, list[str]] = {}
        self._tf: dict[str, dict[str, int]] = {}
        self._df: dict[str, int] = {}
        self._total_tokens = 0

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def avgdl(self) -> float:
        return self._total_tokens / len(self._chunks) if self._chunks else 0.0

    def get(self, chunk_id: str) -> IndexedChunk | None:
        return self._chunks.get(chunk_id)

    def add(self, chunk: IndexedChunk) -> None:
        if chunk.chunk_id in self._chunks:
            self.remove(chunk.chunk_id)
        tokens = tokenize(chunk.text_contextual)
        tf: dict[str, int] = {}
        for tok in tokens:
            tf[tok] = tf.get(tok, 0) + 1
        self._chunks[chunk.chunk_id] = chunk
        self._tokens[chunk.chunk_id] = tokens
        self._tf[chunk.chunk_id] = tf
        self._total_tokens += len(tokens)
        for tok in tf:
            self._df[tok] = self._df.get(tok, 0) + 1

    def remove(self, chunk_id: str) -> None:
        tokens = self._tokens.pop(chunk_id, None)
        if tokens is None:
            return
        self._chunks.pop(chunk_id, None)
        tf = self._tf.pop(chunk_id, {})
        self._total_tokens -= len(tokens)
        for tok in tf:
            remaining = self._df.get(tok, 0) - 1
            if remaining <= 0:
                self._df.pop(tok, None)
            else:
                self._df[tok] = remaining

    def remove_document(self, doc_id: str) -> int:
        """Evict every chunk of a document. Returns the count removed.

        Called before re-indexing so a re-parse that yields fewer chunks
        cannot leave orphans behind, retrievable but no longer backed by the
        current parse.
        """
        stale = [cid for cid, chunk in self._chunks.items() if chunk.doc_id == doc_id]
        for chunk_id in stale:
            self.remove(chunk_id)
        return len(stale)

    def search(
        self,
        query: str,
        *,
        top_k: int = 50,
        query_expansions: Iterable[str] = (),
        **scope: object,
    ) -> list[BM25Result]:
        terms = set(tokenize(query))
        for expansion in query_expansions:
            terms.update(tokenize(expansion))
        if not terms or not self._chunks:
            return []

        n = len(self._chunks)
        avgdl = max(self.avgdl, 1.0)
        scored: list[tuple[float, str]] = []
        for chunk_id, chunk in self._chunks.items():
            if not matches_scope(chunk, **scope):  # type: ignore[arg-type]
                continue
            dl = len(self._tokens[chunk_id])
            if not dl:
                continue
            tf = self._tf[chunk_id]
            score = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                df = self._df.get(term, 0)
                if not df:
                    continue
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = freq + self.k1 * (1 - self.b + self.b * dl / avgdl)
                score += idf * (freq * (self.k1 + 1)) / denom
            if score > 0:
                scored.append((score, chunk_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [BM25Result(chunk_id=cid, score=s) for s, cid in scored[:top_k]]
