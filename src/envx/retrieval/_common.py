"""Shared retrieval types and scope filtering.

``IndexedChunk`` is the denormalized row every retrieval path sees. It
mirrors the ``blocks`` table columns used as hard filters (§3.4) so the
in-memory backends and the eventual Postgres backends apply identical
predicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    doc_id: str
    text_raw: str
    text_contextual: str
    client_id: str
    page_number: int
    matter_id: str | None = None
    doc_type: str | None = None
    jurisdiction: str | None = None
    region_id: str | None = None
    region_type: str | None = None
    storage_tier: str = "hot"
    confidence: float = 1.0
    marker_array: tuple[str, ...] = field(default_factory=tuple)


def matches_scope(
    chunk: IndexedChunk,
    *,
    client_id: str | None = None,
    matter_id: str | None = None,
    jurisdiction: str | None = None,
    doc_types: Iterable[str] | None = None,
    markers_any_of: Iterable[str] | None = None,
    storage_tier: Iterable[str] | None = None,
    confidence_gte: float | None = None,
) -> bool:
    """Hard pre-retrieval filters (§3.4).

    Client and matter isolation are non-negotiable: a missing matter_id on
    the chunk never satisfies a matter-scoped query.
    """
    if client_id is not None and chunk.client_id != client_id:
        return False
    if matter_id is not None and chunk.matter_id != matter_id:
        return False
    if jurisdiction is not None and chunk.jurisdiction != jurisdiction:
        return False
    if doc_types and chunk.doc_type not in set(doc_types):
        return False
    if storage_tier and chunk.storage_tier not in set(storage_tier):
        return False
    if confidence_gte is not None and chunk.confidence < confidence_gte:
        return False
    if markers_any_of and not set(markers_any_of).intersection(chunk.marker_array):
        return False
    return True
