"""Cold-tier vector store backed by LEANN.

The original §4.2/§4.4 design sends cold documents to Parquet with their
embedding column nulled — which means a cold document is *not searchable*
until someone rehydrates it. That is a real capability gap: the matter
closed two years ago is often exactly the one a new conflict check or a
recurring-defect pattern needs to surface, and you cannot rehydrate what
you cannot find.

LEANN (https://github.com/StarTrail-org/LEANN, MIT) closes that gap. It
stores a pruned proximity graph and *recomputes* embeddings during
traversal rather than storing them, reporting ~97% storage reduction
(60M documents in ~6GB vs ~201GB for a conventional flat index) at
comparable recall.

The tradeoff is precisely inverted from the hot tier's needs, which is why
it belongs here and nowhere else:

    HOT   pgvector HNSW      vectors resident, p95 < 100ms
    WARM  pgvector HNSW      vectors resident, relaxed latency
    COLD  LEANN              ~3% storage, recompute cost per query

Cold queries are rare and tolerate seconds. Hot queries are not and do not.

LEANN is an optional dependency. Without it installed the store degrades to
``NullColdStore``, which reports cold documents as unsearchable rather than
silently returning nothing — a query that quietly skips the cold tier would
be worse than one that says it did.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence


def leann_available() -> bool:
    try:
        import leann  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class ColdSearchResult:
    chunk_id: str
    doc_id: str
    score: float
    text: str = ""


@dataclass(frozen=True)
class ColdChunk:
    chunk_id: str
    doc_id: str
    text: str
    client_id: str
    matter_id: str | None = None


class ColdVectorStore(Protocol):
    backend: str
    searchable: bool

    def add(self, chunks: Sequence[ColdChunk]) -> None: ...

    def build(self) -> None: ...

    def search(self, query: str, *, top_k: int = 20) -> list[ColdSearchResult]: ...


class NullColdStore:
    """Fallback when LEANN isn't installed.

    Retains the chunk inventory so callers can still report *what* is in the
    cold tier and rehydrate by doc_id; it just cannot rank by similarity.
    """

    backend = "null"
    searchable = False

    def __init__(self) -> None:
        self._chunks: dict[str, ColdChunk] = {}

    def __len__(self) -> int:
        return len(self._chunks)

    def add(self, chunks: Sequence[ColdChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def build(self) -> None:
        return None

    def search(self, query: str, *, top_k: int = 20) -> list[ColdSearchResult]:
        return []

    def doc_ids(self) -> set[str]:
        return {c.doc_id for c in self._chunks.values()}


class LeannColdStore:
    """LEANN-backed cold tier.

    Index construction is deferred until ``build()`` because LEANN builds the
    pruned graph in one pass; tiering demotes documents in batches, so this
    matches how it is actually used.
    """

    backend = "leann"
    searchable = True

    def __init__(
        self,
        index_path: Path,
        *,
        backend_name: str = "hnsw",
        embedding_model: str | None = None,
    ) -> None:
        if not leann_available():
            raise ImportError("leann is not installed; use build_cold_store() instead")
        self.index_path = Path(index_path)
        self.backend_name = backend_name
        self.embedding_model = embedding_model
        self.searchable = True
        self.build_error: str | None = None
        self._pending: list[ColdChunk] = []
        self._meta: dict[str, ColdChunk] = {}
        self._searcher = None
        self._built = self.index_path.exists()

    def __len__(self) -> int:
        return len(self._meta)

    def add(self, chunks: Sequence[ColdChunk]) -> None:
        for chunk in chunks:
            if chunk.chunk_id in self._meta:
                continue
            self._meta[chunk.chunk_id] = chunk
            self._pending.append(chunk)

    def build(self) -> None:
        """Build the pruned graph over everything added so far.

        LEANN downloads its embedding model on first build. If that fails —
        air-gapped host, no model cache — we surface ``build_error`` and mark
        the tier unsearchable rather than raising, because a cold-tier build
        failure must not take down ingestion. The chunk inventory survives,
        so documents remain enumerable and rehydratable by doc_id.
        """
        if not self._pending:
            return
        from leann import LeannBuilder

        kwargs: dict[str, object] = {"backend_name": self.backend_name}
        if self.embedding_model:
            kwargs["embedding_model"] = self.embedding_model
        try:
            builder = LeannBuilder(**kwargs)  # type: ignore[arg-type]
            for chunk in self._meta.values():
                # Metadata rides along so hits carry provenance without a
                # second lookup — a cold hit still has to cite a document —
                # and so client/matter filters can apply during traversal.
                builder.add_text(
                    chunk.text,
                    metadata={
                        "chunk_id": chunk.chunk_id,
                        "doc_id": chunk.doc_id,
                        "client_id": chunk.client_id,
                        "matter_id": chunk.matter_id or "",
                    },
                )
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            builder.build_index(str(self.index_path))
        except Exception as exc:  # noqa: BLE001 - degrade, never block ingest
            self.build_error = f"{type(exc).__name__}: {exc}"
            self.searchable = False
            return
        self.build_error = None
        self.searchable = True
        self._pending.clear()
        self._searcher = None
        self._built = True

    def search(
        self,
        query: str,
        *,
        top_k: int = 20,
        client_id: str | None = None,
        matter_id: str | None = None,
    ) -> list[ColdSearchResult]:
        """Search the cold tier.

        Client and matter isolation is pushed into LEANN's metadata filters
        so it applies during traversal. Cold storage does not get to be a
        loophole in tenant isolation.
        """
        if not self._built:
            self.build()
        if not self._built:
            return []
        if self._searcher is None:
            from leann import LeannSearcher

            self._searcher = LeannSearcher(str(self.index_path))

        filters: dict[str, dict[str, object]] = {}
        if client_id is not None:
            filters["client_id"] = {"==": client_id}
        if matter_id is not None:
            filters["matter_id"] = {"==": matter_id}

        raw = self._searcher.search(
            query,
            top_k=top_k,
            metadata_filters=filters or None,
        )
        results = [r for r in (self._to_result(item) for item in raw) if r is not None]
        # Defense in depth: if a backend ever ignores metadata_filters, drop
        # anything out of scope rather than leaking it to the caller.
        if client_id is not None:
            results = [
                r for r in results
                if self._meta.get(r.chunk_id) is None
                or self._meta[r.chunk_id].client_id == client_id
            ]
        return results

    def _to_result(self, item: object) -> ColdSearchResult | None:
        meta = getattr(item, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        chunk_id = meta.get("chunk_id")
        if chunk_id is None:
            return None
        known = self._meta.get(chunk_id)
        return ColdSearchResult(
            chunk_id=str(chunk_id),
            doc_id=str(meta.get("doc_id") or (known.doc_id if known else "")),
            score=float(getattr(item, "score", 0.0) or 0.0),
            text=str(getattr(item, "text", "") or "") or (known.text if known else ""),
        )

    def doc_ids(self) -> set[str]:
        return {c.doc_id for c in self._meta.values()}


def build_cold_store(
    index_path: Path | str = "./var/cold/envx.leann",
    *,
    backend_name: str = "hnsw",
    embedding_model: str | None = None,
) -> ColdVectorStore:
    """Return a LEANN store when available, else the null fallback."""
    if leann_available():
        return LeannColdStore(
            Path(index_path),
            backend_name=backend_name,
            embedding_model=embedding_model,
        )
    return NullColdStore()


def demote_to_cold(
    *,
    store: ColdVectorStore,
    chunks: Iterable[ColdChunk],
    build_now: bool = True,
) -> int:
    """Move chunks into the cold store. Returns the count accepted.

    Callers drop the hot-tier vectors only after this succeeds — losing the
    hot copy before the cold copy exists would make the document
    unrecoverable without a full re-parse.
    """
    batch = list(chunks)
    store.add(batch)
    if build_now:
        store.build()
    return len(batch)
