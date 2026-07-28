"""Twin-run agreement checking (architecture §2.5.4 item 3).

Run KIE twice on high-stakes documents and compare field by field. Where the
two runs disagree, the extraction is not trustworthy regardless of how
confident either run looked on its own.

This catches a failure mode grounding cannot. Grounding asks "does this value
appear in the document" — a model that consistently misreads the *same*
plausible-but-wrong value passes. Twin runs ask "is this value stable", which
catches extraction that is guessing even when the guess is present in the text
somewhere.

Expensive by design: it doubles KIE cost, so §2.5.4 scopes it to active-matter
ingestion rather than the whole corpus.

Comparison is value-aware rather than exact:
    - Strings compare normalized (case, whitespace, punctuation).
    - Numbers compare within a relative tolerance.
    - Lists of objects compare as multisets keyed on their identifying
      fields, since ordering of extracted arrays is not meaningful.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .validator import flatten_extracted_fields


_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).casefold()
        return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip()
    return value


def values_agree(a: Any, b: Any, *, numeric_tolerance: float = 0.01) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return True
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) / scale <= numeric_tolerance
    return normalize_value(a) == normalize_value(b)


@dataclass(frozen=True)
class FieldDisagreement:
    field_path: str
    run_a: Any
    run_b: Any

    @property
    def kind(self) -> str:
        if self.run_a is None:
            return "only_in_b"
        if self.run_b is None:
            return "only_in_a"
        return "conflicting"


@dataclass
class TwinRunReport:
    compared: int = 0
    agreed: int = 0
    disagreements: list[FieldDisagreement] = field(default_factory=list)

    @property
    def agreement_rate(self) -> float:
        return self.agreed / self.compared if self.compared else 1.0

    @property
    def has_disagreement(self) -> bool:
        return bool(self.disagreements)

    def high_severity_paths(self, *, critical_prefixes: tuple[str, ...] = ()) -> list[str]:
        """Disagreements on paths the caller considers critical.

        A wobble on ``$.property.year_built`` is noise. A wobble on
        ``$.hazards_disclosed[0].type`` changes what markers fire and which
        matters surface the document.
        """
        if not critical_prefixes:
            return [d.field_path for d in self.disagreements]
        return [
            d.field_path
            for d in self.disagreements
            if any(d.field_path.startswith(p) for p in critical_prefixes)
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "compared": self.compared,
            "agreed": self.agreed,
            "agreement_rate": round(self.agreement_rate, 4),
            "disagreements": [
                {
                    "field_path": d.field_path,
                    "kind": d.kind,
                    "run_a": d.run_a,
                    "run_b": d.run_b,
                }
                for d in self.disagreements
            ],
        }


# Paths whose instability actually matters for downstream markers and routing.
CRITICAL_PREFIXES = (
    "$.hazards_disclosed",
    "$.hazmat_observed",
    "$.recs",
    "$.sampling_results",
    "$.conclusions",
    "$.denial",
    "$.reservation_of_rights",
    "$.diagnoses_icd10",
    "$.exposure_history_mentioned",
    "$.seller",
    "$.buyer",
    "$.insured",
    "$.insurer",
    "$.claim_number",
    "$.policy_number",
)


def compare_runs(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    *,
    ignore_paths: tuple[str, ...] = ("$.doc_type", "$.jurisdiction"),
) -> TwinRunReport:
    """Compare two KIE payloads field by field.

    Array element paths are compared positionally after sorting each array by
    a stable key, so a model emitting the same two hazards in a different
    order is not reported as disagreeing.
    """
    a_fields = {
        f.field_path: f.value
        for f in flatten_extracted_fields(_canonicalize(run_a))
    }
    b_fields = {
        f.field_path: f.value
        for f in flatten_extracted_fields(_canonicalize(run_b))
    }

    report = TwinRunReport()
    for path in sorted(set(a_fields) | set(b_fields)):
        if any(path.startswith(p) for p in ignore_paths):
            continue
        a_value = a_fields.get(path)
        b_value = b_fields.get(path)
        report.compared += 1
        if path in a_fields and path in b_fields and values_agree(a_value, b_value):
            report.agreed += 1
        elif path not in a_fields or path not in b_fields:
            report.disagreements.append(FieldDisagreement(path, a_value, b_value))
        else:
            report.disagreements.append(FieldDisagreement(path, a_value, b_value))
    return report


def _canonicalize(payload: Any) -> Any:
    """Sort arrays of objects so element ordering doesn't create false diffs."""
    if isinstance(payload, dict):
        return {k: _canonicalize(v) for k, v in payload.items()}
    if isinstance(payload, list):
        items = [_canonicalize(v) for v in payload]
        return sorted(items, key=_sort_key)
    return payload


def _sort_key(item: Any) -> str:
    if isinstance(item, dict):
        # Prefer identifying fields; fall back to the whole item so the sort
        # stays deterministic for shapes we don't recognise.
        for key in ("type", "code", "analyte", "system", "rec_type", "category"):
            if isinstance(item.get(key), str):
                return f"{key}={normalize_value(item[key])}"
        return repr(sorted((str(k), str(v)) for k, v in item.items()))
    return repr(normalize_value(item))
