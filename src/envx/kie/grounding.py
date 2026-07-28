"""Field-grounding check for KIE output.

Every extracted string value must appear (fuzzy-matched, normalized) in the
LiteParse text of the document. If it doesn't, the field is flagged
``needs_review`` — this catches hallucinated parties, addresses, dates.

Numbers, booleans, enum-ish short values, and page references are
skipped — they're either structural (page_cited) or not the kind of fact
that benefits from substring verification.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..models import ExtractedField

_MULTI_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_for_match(text: str) -> str:
    if not text:
        return ""
    n = unicodedata.normalize("NFKC", text).casefold()
    n = _NON_ALNUM.sub(" ", n)
    return _MULTI_WS.sub(" ", n).strip()


_SKIP_FIELD_SUFFIXES = (
    ".page_cited",
    ".region_id",
    ".exceeds_standard",
    ".signature_present",
    ".testing_recommended",
    ".has_recs",
    ".requires_phase_ii",
    ".asserted",
    ".issued",
)


def _should_check(field_path: str, value: object) -> bool:
    if not isinstance(value, str):
        return False
    if len(value.strip()) < 3:
        return False
    for suffix in _SKIP_FIELD_SUFFIXES:
        if field_path.endswith(suffix):
            return False
    return True


@dataclass(frozen=True)
class GroundingReport:
    total_checked: int
    grounded: int
    ungrounded_paths: list[str]


def ground_fields(
    fields: list[ExtractedField],
    source_text: str,
    *,
    min_ratio: float = 0.85,
    skip_paths: set[str] | None = None,
) -> tuple[list[ExtractedField], GroundingReport]:
    """Verify extracted string values appear in the source text.

    ``skip_paths`` exempts fields whose value comes from schema-controlled
    vocabulary rather than the document — see
    ``kie.validator.controlled_vocabulary_paths``.
    """
    haystack = normalize_for_match(source_text)
    skip = skip_paths or set()
    out: list[ExtractedField] = []
    checked = 0
    grounded = 0
    ungrounded: list[str] = []
    for f in fields:
        if f.field_path in skip or not _should_check(f.field_path, f.value):
            out.append(f)
            continue
        checked += 1
        needle = normalize_for_match(str(f.value))
        if not needle:
            out.append(f)
            continue
        score = 0.0
        if needle in haystack:
            score = 1.0
        else:
            # partial_ratio tolerates line breaks, minor OCR noise, casing.
            score = fuzz.partial_ratio(needle, haystack) / 100.0
        verified = score >= min_ratio
        if verified:
            grounded += 1
        else:
            ungrounded.append(f.field_path)
        out.append(
            ExtractedField(
                field_path=f.field_path,
                value=f.value,
                page_cited=f.page_cited,
                region_id=f.region_id,
                grounding_verified=verified,
                verification_score=round(score, 4),
            )
        )
    return out, GroundingReport(
        total_checked=checked,
        grounded=grounded,
        ungrounded_paths=ungrounded,
    )
