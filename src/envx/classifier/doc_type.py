"""Doc-type classification.

Two-stage per §2.5.2 of the architecture:

    1. A fast rule-based pass over filename + first-page text. Cheap,
       catches the vast majority of intake.
    2. An LLM fallback for the residual. Kept behind a Protocol so callers
       can inject their Claude/Ollama/GLM-OCR classify-prompt implementation
       without dragging a network dependency into this module.

The classifier returns the winning ``schema_id`` plus a confidence that the
intake writer stores on ``documents.doc_type_confidence``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Protocol


@dataclass(frozen=True)
class Classification:
    doc_type: str
    confidence: float
    source: str  # "rule" | "llm" | "default"
    matched_signals: tuple[str, ...] = ()


# Per-doc-type signal bundles. Order matters: the first rule that accumulates
# enough evidence wins. Keep signals short and high-precision; false positives
# here send the wrong schema to KIE.
RULES: list[tuple[str, dict[str, list[str]]]] = [
    (
        "environmental_report",
        {
            "filename_any": [
                "phase1", "phase_i", "phase-i", "esa", "environmental",
                "phase2", "phase_ii", "phase-ii", "phase3", "phase_iii",
            ],
            "text_any": [
                "phase i environmental site assessment",
                "phase ii environmental site assessment",
                "recognized environmental condition",
                "rec ",
                "astm e1527",
                "ctdeep",
            ],
        },
    ),
    (
        "property_disclosure",
        {
            "filename_any": [
                "disclosure", "seller_disclosure", "property_disclosure",
                "residential_disclosure",
            ],
            "text_any": [
                "residential property condition disclosure",
                "seller's disclosure",
                "property condition disclosure report",
                "known defects",
                "ct residential property disclosure",
            ],
        },
    ),
    (
        "inspection_report",
        {
            "filename_any": ["inspection", "home_inspection", "building_inspection"],
            "text_any": [
                "home inspection report",
                "building inspection report",
                "inspector's observations",
                "systems evaluated",
            ],
        },
    ),
    (
        "insurance_claim",
        {
            "filename_any": ["claim", "policy", "coverage", "ror", "reservation_of_rights"],
            "text_any": [
                "reservation of rights",
                "claim number",
                "notice of loss",
                "coverage analysis",
                "policy period",
            ],
        },
    ),
    (
        "medical_record",
        {
            "filename_any": ["medical", "clinical", "chart", "phi", "health"],
            "text_any": [
                "patient history",
                "chief complaint",
                "icd-10",
                "progress note",
                "attending physician",
            ],
        },
    ),
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold())


def _count_hits(hay: str, needles: Iterable[str]) -> tuple[int, list[str]]:
    hits: list[str] = []
    for n in needles:
        if n in hay:
            hits.append(n)
    return len(hits), hits


class RuleClassifier:
    """Filename + first-page text heuristics. High precision, moderate recall."""

    def classify(
        self,
        *,
        filename: str,
        first_page_text: str,
    ) -> Classification | None:
        fname = filename.casefold()
        text = _normalize(first_page_text)
        best: tuple[float, str, list[str]] | None = None
        for doc_type, signals in RULES:
            fn_hits, fn_matched = _count_hits(fname, signals.get("filename_any", []))
            tx_hits, tx_matched = _count_hits(text, signals.get("text_any", []))
            # Heuristic scoring: filename hits are strong (~0.35 each, capped),
            # text hits are additive (~0.15 each, capped). 2+ signals or any
            # filename hit crosses 0.55 which is our "trust it" threshold.
            score = min(0.7, fn_hits * 0.35) + min(0.3, tx_hits * 0.15)
            if score >= 0.35:
                candidate = (score, doc_type, fn_matched + tx_matched)
                if best is None or candidate[0] > best[0]:
                    best = candidate
        if best is None:
            return None
        score, doc_type, matched = best
        return Classification(
            doc_type=doc_type,
            confidence=min(0.95, score),
            source="rule",
            matched_signals=tuple(matched),
        )


class LLMClassifier(Protocol):
    def classify(self, *, filename: str, first_page_text: str) -> Classification | None: ...


class DocTypeClassifier:
    """Two-stage classifier: rules first, LLM fallback if rules abstain."""

    def __init__(
        self,
        rule: RuleClassifier | None = None,
        llm: LLMClassifier | None = None,
        *,
        rule_confidence_threshold: float = 0.55,
        default_doc_type: str = "unknown",
    ) -> None:
        self.rule = rule or RuleClassifier()
        self.llm = llm
        self.threshold = rule_confidence_threshold
        self.default_doc_type = default_doc_type

    def classify(
        self,
        *,
        filename: str,
        first_page_text: str,
    ) -> Classification:
        rule_hit = self.rule.classify(filename=filename, first_page_text=first_page_text)
        if rule_hit is not None and rule_hit.confidence >= self.threshold:
            return rule_hit
        if self.llm is not None:
            llm_hit = self.llm.classify(filename=filename, first_page_text=first_page_text)
            if llm_hit is not None:
                return llm_hit
        if rule_hit is not None:
            return rule_hit
        return Classification(
            doc_type=self.default_doc_type,
            confidence=0.0,
            source="default",
        )
