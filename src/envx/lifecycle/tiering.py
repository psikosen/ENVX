"""Hot / warm / cold tiering (architecture §4.2).

    HOT:  matter.is_active, or last_queried < 30d, or marker_severity >= HIGH,
          or a scheduled proceeding within 60d
    WARM: !is_active AND last_queried < 365d
    COLD: matter closed > 1y AND no queries in 365d
    WET:  everything, forever, separate storage class

Cold drops the embedding column and archives vectors to Parquet. Rehydration
(§4.3) always re-embeds with the *current* model when the stored model
version differs — stale vectors in a live index are silent recall loss.

Note the ordering: an upcoming proceeding pins a document HOT regardless of
query history. Discovery deadlines don't care how recently anyone searched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class StorageTier(str, Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


HOT_QUERY_WINDOW = timedelta(days=30)
WARM_QUERY_WINDOW = timedelta(days=365)
PROCEEDING_HORIZON = timedelta(days=60)
CLOSED_MATTER_AGE = timedelta(days=365)

HIGH_SEVERITY_PREFIXES = ("RISK:", "CLAUSE:")


@dataclass(frozen=True)
class DocumentLifecycle:
    doc_id: str
    matter_is_active: bool
    last_queried_at: datetime | None = None
    matter_closed_at: datetime | None = None
    next_proceeding_at: datetime | None = None
    markers: tuple[str, ...] = ()
    embedding_model_version: str | None = None


@dataclass(frozen=True)
class TierDecision:
    doc_id: str
    tier: StorageTier
    reason: str
    drop_embeddings: bool = False
    needs_reembed: bool = False


def _age(now: datetime, then: datetime | None) -> timedelta | None:
    return None if then is None else now - then


def evaluate_tier(
    doc: DocumentLifecycle,
    *,
    now: datetime | None = None,
    current_embedding_model: str | None = None,
) -> TierDecision:
    now = now or datetime.now(timezone.utc)

    if doc.matter_is_active:
        return _hot(doc, "matter is active", current_embedding_model)

    if doc.next_proceeding_at is not None:
        until = doc.next_proceeding_at - now
        if timedelta(0) <= until <= PROCEEDING_HORIZON:
            return _hot(doc, "proceeding scheduled within 60d", current_embedding_model)

    if any(m.startswith(HIGH_SEVERITY_PREFIXES) for m in doc.markers):
        return _hot(doc, "high-severity marker present", current_embedding_model)

    since_query = _age(now, doc.last_queried_at)
    if since_query is not None and since_query < HOT_QUERY_WINDOW:
        return _hot(doc, "queried within 30d", current_embedding_model)

    closed_for = _age(now, doc.matter_closed_at)
    cold_by_age = closed_for is not None and closed_for > CLOSED_MATTER_AGE
    cold_by_disuse = since_query is None or since_query > WARM_QUERY_WINDOW
    if cold_by_age and cold_by_disuse:
        return TierDecision(
            doc_id=doc.doc_id,
            tier=StorageTier.COLD,
            reason="matter closed >1y and no queries in 365d",
            drop_embeddings=True,
        )

    return TierDecision(
        doc_id=doc.doc_id,
        tier=StorageTier.WARM,
        reason="inactive matter, still within the 365d query window",
        needs_reembed=_stale(doc, current_embedding_model),
    )


def _hot(
    doc: DocumentLifecycle,
    reason: str,
    current_model: str | None,
) -> TierDecision:
    return TierDecision(
        doc_id=doc.doc_id,
        tier=StorageTier.HOT,
        reason=reason,
        needs_reembed=_stale(doc, current_model),
    )


def _stale(doc: DocumentLifecycle, current_model: str | None) -> bool:
    if current_model is None:
        return False
    if doc.embedding_model_version is None:
        return True
    return doc.embedding_model_version != current_model
