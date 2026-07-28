"""Domain models for the preprocessing layer.

Intentionally small — these are the types that cross module boundaries
(client → validator → markers → storage). Database rows are defined
by the SQL DDL in db/migrations; these are the Python-side shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RegionType(str, Enum):
    TITLE = "title"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    SIGNATURE = "signature"
    STAMP = "stamp"
    FORM_FIELD = "form_field"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"


@dataclass(frozen=True)
class Region:
    page_number: int
    bbox: tuple[int, int, int, int]
    region_type: RegionType
    label_confidence: float
    region_id: str | None = None


class GroundingStatus(str, Enum):
    """Outcome of the field-grounding check.

    ``NOT_APPLICABLE`` is distinct from ``FAILED`` on purpose. Schema
    controlled vocabulary (doc_type, severity enums), booleans, and page
    references are never checked against source text. Collapsing that into
    "not verified" would make a reviewer unable to tell an untested field
    from a hallucinated party, which is the exact judgement this column
    exists to support.
    """

    VERIFIED = "verified"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ExtractedField:
    field_path: str
    value: Any
    page_cited: int | None
    region_id: str | None = None
    grounding_verified: bool = False
    verification_score: float = 0.0
    grounding_status: GroundingStatus = GroundingStatus.NOT_APPLICABLE


@dataclass(frozen=True)
class KIEResult:
    doc_type: str
    schema_id: str
    schema_version: str
    schema_content_hash: str
    raw_json: dict[str, Any]
    fields: list[ExtractedField] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Marker:
    code: str
    confidence: float
    source_field_path: str | None
    extracted_by: str = "kie_rule"
    evidence: dict[str, Any] = field(default_factory=dict)
