"""Retrieval plan DSL (architecture §6).

The planning LLM emits YAML; we compile it to typed objects before anything
executes. Compilation is deliberately strict — unknown path kinds, unknown
fusion methods, and missing queries all raise rather than degrading
silently. A plan that quietly did something other than what it said would
be worse than useless in a setting where the output gets cited.

The LLM plans and reads. It never fetches (§12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


class PlanValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Scope:
    client_id: str | None = None
    matter_id: str | None = None
    jurisdiction: str | None = None
    doc_types: tuple[str, ...] | None = None
    markers_any_of: tuple[str, ...] | None = None
    storage_tier: tuple[str, ...] = ("hot", "warm")
    confidence_gte: float | None = None


@dataclass(frozen=True)
class StructuredFilter:
    """Path 5 — SQL over ``extracted_fields``. Pre-filter, never fused."""

    where: str | None = None
    or_where: str | None = None


@dataclass(frozen=True)
class RetrievalPath:
    kind: str
    query: str
    weight: float = 1.0
    query_expansions: tuple[str, ...] = ()
    model: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class GraphPath:
    start_entities: tuple[str, ...]
    relations: tuple[str, ...] = ()
    max_hops: int = 2
    weight: float = 0.5
    enabled: bool = True


@dataclass(frozen=True)
class RerankSpec:
    model: str
    top_k: int = 15


@dataclass(frozen=True)
class ResponseSpec:
    mode: str = "legal_citation_required"
    require_block_ids: bool = True
    require_page_numbers: bool = True
    require_region_ids: bool = False
    min_confidence: float = 0.0


@dataclass(frozen=True)
class RetrievalPlan:
    scope: Scope = field(default_factory=Scope)
    structured_filter: StructuredFilter | None = None
    paths: tuple[RetrievalPath, ...] = ()
    graph: GraphPath | None = None
    fusion: str = "rrf"
    top_k: int = 100
    rerank: RerankSpec | None = None
    response: ResponseSpec = field(default_factory=ResponseSpec)
    soft_boost_markers: dict[str, float] = field(default_factory=dict)

    def path(self, kind: str) -> RetrievalPath | None:
        for p in self.paths:
            if p.kind == kind and p.enabled:
                return p
        return None


_SCORED_PATHS = {"bm25", "dense", "visual"}


def plan_from_yaml(text: str) -> RetrievalPlan:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise PlanValidationError("plan must be a YAML mapping")
    return load_plan(raw)


def load_plan(raw: dict[str, Any]) -> RetrievalPlan:
    scope = _scope(raw.get("scope") or {})
    structured = _structured_filter(raw.get("structured_filter"))
    retrieval = raw.get("retrieval") or {}
    if not isinstance(retrieval, dict):
        raise PlanValidationError("retrieval must be a mapping")

    paths, graph = _paths(retrieval.get("paths") or [])
    if not paths and graph is None:
        raise PlanValidationError("retrieval.paths must define at least one enabled path")

    fusion = str(retrieval.get("fusion", "rrf")).lower()
    if fusion != "rrf":
        raise PlanValidationError(f"unsupported fusion {fusion!r}; only 'rrf' is implemented")

    top_k = retrieval.get("top_k", 100)
    if not isinstance(top_k, int) or top_k <= 0:
        raise PlanValidationError("retrieval.top_k must be a positive integer")

    return RetrievalPlan(
        scope=scope,
        structured_filter=structured,
        paths=paths,
        graph=graph,
        fusion=fusion,
        top_k=top_k,
        rerank=_rerank(raw.get("rerank")),
        response=_response(raw.get("response") or {}),
        soft_boost_markers=_boosts(retrieval.get("soft_boost_markers")),
    )


def _scope(raw: Any) -> Scope:
    if not isinstance(raw, dict):
        raise PlanValidationError("scope must be a mapping")
    return Scope(
        client_id=raw.get("client_id"),
        matter_id=raw.get("matter_id"),
        jurisdiction=raw.get("jurisdiction"),
        doc_types=_tuple(raw.get("doc_types")),
        markers_any_of=_tuple(raw.get("markers_any_of")),
        storage_tier=_tuple(raw.get("storage_tier")) or ("hot", "warm"),
        confidence_gte=_float(raw.get("confidence_gte")),
    )


def _structured_filter(raw: Any) -> StructuredFilter | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlanValidationError("structured_filter must be a mapping")
    return StructuredFilter(where=raw.get("where"), or_where=raw.get("or"))


def _paths(raw: Any) -> tuple[tuple[RetrievalPath, ...], GraphPath | None]:
    if not isinstance(raw, list):
        raise PlanValidationError("retrieval.paths must be a list")
    paths: list[RetrievalPath] = []
    graph: GraphPath | None = None
    for entry in raw:
        if not isinstance(entry, dict):
            raise PlanValidationError("each retrieval path must be a mapping")
        kind = entry.get("kind")
        enabled = bool(entry.get("enabled", True))
        if kind == "graph":
            starts = _tuple(entry.get("start_entities")) or ()
            if enabled and not starts:
                raise PlanValidationError("graph path requires start_entities")
            graph = GraphPath(
                start_entities=starts,
                relations=_tuple(entry.get("relations")) or (),
                max_hops=int(entry.get("max_hops", 2)),
                weight=_float(entry.get("weight")) or 0.5,
                enabled=enabled,
            )
            continue
        if kind not in _SCORED_PATHS:
            raise PlanValidationError(
                f"unknown path kind {kind!r}; expected one of "
                f"{sorted(_SCORED_PATHS | {'graph'})}"
            )
        query = entry.get("query")
        if not isinstance(query, str) or not query.strip():
            raise PlanValidationError(f"path {kind!r} requires a non-empty query")
        paths.append(
            RetrievalPath(
                kind=kind,
                query=query.strip(),
                weight=_float(entry.get("weight")) or 1.0,
                query_expansions=_tuple(entry.get("query_expansions")) or (),
                model=entry.get("model"),
                enabled=enabled,
            )
        )
    return tuple(p for p in paths if p.enabled), (graph if graph and graph.enabled else None)


def _rerank(raw: Any) -> RerankSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlanValidationError("rerank must be a mapping")
    model = raw.get("model")
    if not isinstance(model, str) or not model.strip():
        raise PlanValidationError("rerank.model is required")
    top_k = raw.get("top_k", 15)
    if not isinstance(top_k, int) or top_k <= 0:
        raise PlanValidationError("rerank.top_k must be a positive integer")
    return RerankSpec(model=model.strip(), top_k=top_k)


def _response(raw: Any) -> ResponseSpec:
    if not isinstance(raw, dict):
        raise PlanValidationError("response must be a mapping")
    return ResponseSpec(
        mode=str(raw.get("mode", "legal_citation_required")),
        require_block_ids=bool(raw.get("require_block_ids", True)),
        require_page_numbers=bool(raw.get("require_page_numbers", True)),
        require_region_ids=bool(raw.get("require_region_ids", False)),
        min_confidence=_float(raw.get("min_confidence")) or 0.0,
    )


def _boosts(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        weight = _float(value)
        if isinstance(key, str) and weight is not None:
            out[key] = weight
    return out


def _tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    raise PlanValidationError(f"expected string or list, got {type(value).__name__}")


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
