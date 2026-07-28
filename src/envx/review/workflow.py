"""Review and safety workflow (architecture §8).

Four document states, a trigger set that decides which one a document lands
in, and an append-only correction log.

Two rules from §8 are enforced here rather than left to process:

    1. Corrections that change ``RISK:*`` or ``CLAUSE:*`` markers on an
       active matter require two distinct reviewers. Attempting to
       self-approve raises.
    2. The correction log is immutable. Corrections supersede; nothing is
       edited or deleted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class ReviewState(str, Enum):
    TRUSTED = "trusted"
    USABLE_WITH_REVIEW = "usable_with_review"
    NEEDS_REPARSE = "needs_reparse"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class ReviewTrigger(str, Enum):
    LOW_PARSE_SCORE = "low_parse_score"
    MISSING_PROVENANCE = "missing_provenance"
    CONFLICTING_PARSES = "conflicting_parses"
    OCR_NOISE_HAZARD_TERM = "ocr_noise_hazard_term"
    CLIENT_NAME_MISMATCH = "client_name_mismatch"
    KIE_GROUNDING_FAILED = "kie_grounding_failed"
    KIE_TWIN_RUN_DISAGREEMENT = "kie_twin_run_disagreement"
    KIE_SCHEMA_INVALID = "kie_schema_invalid"
    HIGH_SEVERITY_LOW_CONFIDENCE = "high_severity_marker_low_confidence"


# Triggers that mean the parse itself is untrustworthy — re-run the machine
# before spending a human on it.
_REPARSE_TRIGGERS = {
    ReviewTrigger.LOW_PARSE_SCORE,
    ReviewTrigger.KIE_SCHEMA_INVALID,
    ReviewTrigger.CONFLICTING_PARSES,
}

# Triggers where the machine did its job and a human must adjudicate.
_HUMAN_TRIGGERS = {
    ReviewTrigger.KIE_GROUNDING_FAILED,
    ReviewTrigger.KIE_TWIN_RUN_DISAGREEMENT,
    ReviewTrigger.HIGH_SEVERITY_LOW_CONFIDENCE,
    ReviewTrigger.CLIENT_NAME_MISMATCH,
    ReviewTrigger.OCR_NOISE_HAZARD_TERM,
    ReviewTrigger.MISSING_PROVENANCE,
}

HIGH_SEVERITY_PREFIXES = ("RISK:", "CLAUSE:")
HIGH_SEVERITY_CONFIDENCE_FLOOR = 0.85


def evaluate_triggers(
    *,
    validation_report: dict[str, Any] | None = None,
    markers: Iterable[tuple[str, float]] = (),
    parse_score: float | None = None,
    twin_run_disagreement: bool = False,
    client_name_matches: bool = True,
) -> list[ReviewTrigger]:
    """Map pipeline outputs onto review triggers (§8)."""
    triggers: list[ReviewTrigger] = []
    report = validation_report or {}
    reasons = set(report.get("review_reasons") or [])

    if "schema_validation_failed" in reasons or "malformed_json_after_retry" in reasons:
        triggers.append(ReviewTrigger.KIE_SCHEMA_INVALID)
    if "grounding_failed" in reasons:
        triggers.append(ReviewTrigger.KIE_GROUNDING_FAILED)
    if "missing_page_citations" in reasons:
        triggers.append(ReviewTrigger.MISSING_PROVENANCE)
    if twin_run_disagreement:
        triggers.append(ReviewTrigger.KIE_TWIN_RUN_DISAGREEMENT)
    if not client_name_matches:
        triggers.append(ReviewTrigger.CLIENT_NAME_MISMATCH)
    if parse_score is not None and parse_score < 0.60:
        triggers.append(ReviewTrigger.LOW_PARSE_SCORE)

    for code, confidence in markers:
        if code.startswith(HIGH_SEVERITY_PREFIXES) and confidence < HIGH_SEVERITY_CONFIDENCE_FLOOR:
            triggers.append(ReviewTrigger.HIGH_SEVERITY_LOW_CONFIDENCE)
            break
    return triggers


def state_for(triggers: Iterable[ReviewTrigger]) -> ReviewState:
    active = set(triggers)
    if not active:
        return ReviewState.TRUSTED
    if active & _REPARSE_TRIGGERS:
        return ReviewState.NEEDS_REPARSE
    if active & _HUMAN_TRIGGERS:
        return ReviewState.NEEDS_HUMAN_REVIEW
    return ReviewState.USABLE_WITH_REVIEW


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Correction:
    correction_id: str
    doc_id: str
    field_path: str
    old_value: Any
    new_value: Any
    reason: str
    corrected_by: str
    approved_by: str | None
    affects_high_severity: bool
    created_at: datetime = field(default_factory=_utcnow)
    supersedes: str | None = None


@dataclass
class ReviewItem:
    doc_id: str
    state: ReviewState
    triggers: tuple[ReviewTrigger, ...]
    matter_is_active: bool = False
    notes: str = ""
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class TwoPersonReviewRequired(PermissionError):
    pass


class ReviewQueue:
    """In-memory review queue with an append-only correction log."""

    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}
        self._log: list[Correction] = []

    @property
    def corrections(self) -> list[Correction]:
        return list(self._log)

    def pending(self) -> list[ReviewItem]:
        return [i for i in self._items.values() if i.resolved_at is None]

    def get(self, doc_id: str) -> ReviewItem | None:
        return self._items.get(doc_id)

    def enqueue(
        self,
        *,
        doc_id: str,
        triggers: Iterable[ReviewTrigger],
        matter_is_active: bool = False,
        notes: str = "",
    ) -> ReviewItem:
        trigger_tuple = tuple(dict.fromkeys(triggers))
        item = ReviewItem(
            doc_id=doc_id,
            state=state_for(trigger_tuple),
            triggers=trigger_tuple,
            matter_is_active=matter_is_active,
            notes=notes,
        )
        self._items[doc_id] = item
        return item

    def record_correction(
        self,
        *,
        doc_id: str,
        field_path: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        corrected_by: str,
        approved_by: str | None = None,
        marker_code: str | None = None,
        supersedes: str | None = None,
    ) -> Correction:
        item = self._items.get(doc_id)
        matter_active = item.matter_is_active if item else False
        high_severity = bool(
            marker_code and marker_code.startswith(HIGH_SEVERITY_PREFIXES)
        )

        # §8: two-person rule for RISK/CLAUSE changes on active matters.
        if high_severity and matter_active:
            if not approved_by:
                raise TwoPersonReviewRequired(
                    f"changing {marker_code} on an active matter requires a second approver"
                )
            if approved_by == corrected_by:
                raise TwoPersonReviewRequired(
                    "approver must differ from the person making the correction"
                )

        correction = Correction(
            correction_id=str(uuid.uuid4()),
            doc_id=doc_id,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            corrected_by=corrected_by,
            approved_by=approved_by,
            affects_high_severity=high_severity,
            supersedes=supersedes,
        )
        self._log.append(correction)
        return correction

    def resolve(self, *, doc_id: str, resolved_by: str, notes: str = "") -> ReviewItem:
        item = self._items.get(doc_id)
        if item is None:
            raise KeyError(doc_id)
        item.resolved_at = _utcnow()
        item.resolved_by = resolved_by
        item.state = ReviewState.TRUSTED
        if notes:
            item.notes = f"{item.notes}\n{notes}".strip()
        return item

    def history(self, doc_id: str) -> list[Correction]:
        return [c for c in self._log if c.doc_id == doc_id]
