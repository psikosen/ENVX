"""KIE output validation.

Pipeline:
    1. Strict JSON Schema validation (Draft 2020-12).
    2. Flatten to ``ExtractedField`` rows keyed by JSONPath-ish paths
       (``$.hazards_disclosed[0].type``).
    3. Field grounding — every string value must appear in the source text.
    4. Cite-or-degrade — if a fact is missing ``page_cited`` where the schema
       requires it, the top-level KIE result is flagged ``needs_review``.
    5. Fallback cascade — if JSON is malformed, the caller retries once;
       after that it degrades to regex/NER (out of scope for this branch).

The outcome is the object written to ``kie_runs/{id}/validation_report.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from ..config import EnvxConfig, load_config
from ..models import ExtractedField, KIEResult
from ..schemas import DocSchema
from .grounding import GroundingReport, ground_fields


def _primitive(x: Any) -> bool:
    return isinstance(x, (str, int, float, bool)) or x is None


def flatten_extracted_fields(
    payload: dict[str, Any],
    *,
    prefix: str = "$",
) -> list[ExtractedField]:
    """Walk a KIE JSON payload into ``ExtractedField`` rows.

    Primitive leaves become one row each. Objects and arrays are walked;
    objects inside arrays inherit a ``page_cited`` if one is present.
    """
    rows: list[ExtractedField] = []
    _walk(payload, prefix, None, rows)
    return rows


def _walk(
    node: Any,
    path: str,
    page_cited: int | None,
    rows: list[ExtractedField],
) -> None:
    if isinstance(node, dict):
        local_page = page_cited
        pc = node.get("page_cited")
        if isinstance(pc, int):
            local_page = pc
        for k, v in node.items():
            _walk(v, f"{path}.{k}", local_page, rows)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _walk(v, f"{path}[{i}]", page_cited, rows)
    elif _primitive(node):
        rows.append(
            ExtractedField(
                field_path=path,
                value=node,
                page_cited=page_cited,
            )
        )


@dataclass
class KIEValidationOutcome:
    result: KIEResult
    grounding: GroundingReport | None
    schema_errors: list[str] = field(default_factory=list)
    missing_page_citations: list[str] = field(default_factory=list)

    def as_report(self) -> dict[str, Any]:
        return {
            "schema_id": self.result.schema_id,
            "schema_version": self.result.schema_version,
            "schema_content_hash": self.result.schema_content_hash,
            "needs_review": self.result.needs_review,
            "review_reasons": list(self.result.review_reasons),
            "schema_errors": list(self.schema_errors),
            "missing_page_citations": list(self.missing_page_citations),
            "grounding": (
                {
                    "total_checked": self.grounding.total_checked,
                    "grounded": self.grounding.grounded,
                    "ungrounded_paths": list(self.grounding.ungrounded_paths),
                }
                if self.grounding
                else None
            ),
            "field_count": len(self.result.fields),
        }


class KIEValidator:
    def __init__(self, config: EnvxConfig | None = None) -> None:
        self.config = config or load_config()

    def validate(
        self,
        raw_json: dict[str, Any],
        schema: DocSchema,
        source_text: str,
        *,
        require_grounding: bool = True,
    ) -> KIEValidationOutcome:
        validator = Draft202012Validator(schema.json_schema)
        schema_errors = [
            f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(raw_json), key=lambda e: list(e.absolute_path))
        ]

        fields = flatten_extracted_fields(raw_json)

        grounding_report: GroundingReport | None = None
        if require_grounding and source_text:
            fields, grounding_report = ground_fields(
                fields,
                source_text,
                min_ratio=self.config.grounding_min_ratio,
            )

        missing_citations = _missing_page_citations(raw_json, schema.json_schema)

        review_reasons: list[str] = []
        if schema_errors:
            review_reasons.append("schema_validation_failed")
        if grounding_report and grounding_report.ungrounded_paths:
            review_reasons.append("grounding_failed")
        if missing_citations:
            review_reasons.append("missing_page_citations")

        result = KIEResult(
            doc_type=raw_json.get("doc_type", ""),
            schema_id=schema.schema_id,
            schema_version=schema.version,
            schema_content_hash=schema.content_hash,
            raw_json=raw_json,
            fields=fields,
            validation_errors=schema_errors,
            needs_review=bool(review_reasons),
            review_reasons=review_reasons,
        )
        return KIEValidationOutcome(
            result=result,
            grounding=grounding_report,
            schema_errors=schema_errors,
            missing_page_citations=missing_citations,
        )


def _missing_page_citations(payload: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Walk items in arrays whose schema requires ``page_cited`` — flag missing ones."""
    missing: list[str] = []
    _scan_page_cited(payload, schema, "$", missing)
    return missing


def _scan_page_cited(
    node: Any,
    schema: dict[str, Any] | None,
    path: str,
    out: list[str],
) -> None:
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object" and isinstance(node, dict):
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        if "page_cited" in required and "page_cited" not in node:
            out.append(f"{path}.page_cited")
        for k, v in node.items():
            _scan_page_cited(v, props.get(k), f"{path}.{k}", out)
    elif schema.get("type") == "array" and isinstance(node, list):
        item_schema = schema.get("items") or {}
        for i, v in enumerate(node):
            _scan_page_cited(v, item_schema, f"{path}[{i}]", out)
