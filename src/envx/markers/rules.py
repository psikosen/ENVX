"""Marker-rule engine.

Schemas carry ``marker_rules``: small declarative rules that turn KIE output
into ``Marker`` rows. Supported operators:

    exists           the path yields any value
    equals           the value equals a literal (scalar)
    equals_any       the value is in a list
    starts_with_any  string value starts with any of the listed prefixes
    matches_any      normalized string value equals any in a list
                     (case-insensitive, whitespace-collapsed)

Confidence:
    - A static ``confidence`` field on the rule, OR
    - A ``confidence_map`` keyed by the value of a sibling ``severity_field``
      (used for property-disclosure severity → confidence mapping).

Paths are a tiny JSONPath-like subset:
    $.a.b          object traversal
    $.a[0].b       fixed index
    $.a[*].b       wildcard across array items
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator

from ..models import Marker


_TOKEN_RE = re.compile(r"(?:\.([A-Za-z0-9_]+))|(?:\[(\*|\d+)\])")


@dataclass(frozen=True)
class _Step:
    kind: str  # "key" | "index" | "wildcard"
    value: str | int | None


def _parse_path(path: str) -> list[_Step]:
    if not path.startswith("$"):
        raise ValueError(f"path must start with '$': {path!r}")
    steps: list[_Step] = []
    pos = 1
    while pos < len(path):
        m = _TOKEN_RE.match(path, pos)
        if not m:
            raise ValueError(f"bad path token in {path!r} at {pos}")
        if m.group(1) is not None:
            steps.append(_Step("key", m.group(1)))
        else:
            tok = m.group(2)
            if tok == "*":
                steps.append(_Step("wildcard", None))
            else:
                steps.append(_Step("index", int(tok)))
        pos = m.end()
    return steps


def iter_jsonpath(
    root: Any,
    path: str,
) -> Iterator[tuple[str, Any, dict[str, Any] | None]]:
    """Yield ``(concrete_path, value, parent_object)`` for each match.

    ``parent_object`` is the dict containing ``value`` when the final step is a
    key; it's the array-item dict when walking ``[*]`` into an object; ``None``
    when the value is a bare scalar at the top. We return the parent so rules
    can read sibling fields (``severity_field``).
    """
    steps = _parse_path(path)
    yield from _walk(root, steps, "$", None)


def _walk(
    node: Any,
    steps: list[_Step],
    current_path: str,
    parent: dict[str, Any] | None,
) -> Iterator[tuple[str, Any, dict[str, Any] | None]]:
    if not steps:
        yield current_path, node, parent
        return
    step, rest = steps[0], steps[1:]
    if step.kind == "key":
        if isinstance(node, dict) and step.value in node:
            yield from _walk(
                node[step.value],
                rest,
                f"{current_path}.{step.value}",
                node,
            )
    elif step.kind == "index":
        if isinstance(node, list) and isinstance(step.value, int) and 0 <= step.value < len(node):
            item = node[step.value]
            yield from _walk(
                item,
                rest,
                f"{current_path}[{step.value}]",
                item if isinstance(item, dict) else parent,
            )
    elif step.kind == "wildcard":
        if isinstance(node, list):
            for i, item in enumerate(node):
                yield from _walk(
                    item,
                    rest,
                    f"{current_path}[{i}]",
                    item if isinstance(item, dict) else parent,
                )


def _norm(x: Any) -> str:
    if not isinstance(x, str):
        return ""
    return re.sub(r"\s+", " ", x.casefold()).strip()


def _match_condition(value: Any, parent: dict[str, Any] | None, cond: dict[str, Any]) -> bool:
    if "exists" in cond:
        return bool(cond["exists"])  # any yielded value means it exists
    if "equals" in cond:
        return value == cond["equals"]
    if "equals_any" in cond:
        return value in cond["equals_any"]
    if "starts_with_any" in cond:
        return isinstance(value, str) and any(value.startswith(p) for p in cond["starts_with_any"])
    if "matches_any" in cond:
        normed = _norm(value)
        return normed in {_norm(x) for x in cond["matches_any"]}
    return False


def _rule_confidence(
    rule: dict[str, Any],
    parent: dict[str, Any] | None,
) -> float:
    if "confidence_map" in rule and parent is not None:
        severity_field = rule.get("severity_field", "severity")
        key = parent.get(severity_field)
        if isinstance(key, str):
            cm = rule["confidence_map"]
            if key in cm:
                return float(cm[key])
    if "confidence" in rule:
        return float(rule["confidence"])
    return 0.5


def apply_marker_rules(
    raw_json: dict[str, Any],
    marker_rules: list[dict[str, Any]],
) -> list[Marker]:
    out: list[Marker] = []
    for rule in marker_rules:
        code = rule.get("code_template")
        when = rule.get("when")
        if not isinstance(code, str) or not isinstance(when, dict):
            continue
        path = when.get("field_path")
        if not isinstance(path, str):
            continue
        condition = {k: v for k, v in when.items() if k != "field_path"}
        for concrete_path, value, parent in iter_jsonpath(raw_json, path):
            if not _match_condition(value, parent, condition):
                continue
            conf = _rule_confidence(rule, parent)
            if conf <= 0:
                continue
            out.append(
                Marker(
                    code=code,
                    confidence=conf,
                    source_field_path=concrete_path,
                    extracted_by="kie_rule",
                    evidence={"value": value},
                )
            )
    return _dedupe(out)


def _dedupe(markers: list[Marker]) -> list[Marker]:
    """Collapse duplicates — same (code, source_field_path) pairs. Keep the highest confidence."""
    best: dict[tuple[str, str | None], Marker] = {}
    for m in markers:
        key = (m.code, m.source_field_path)
        cur = best.get(key)
        if cur is None or m.confidence > cur.confidence:
            best[key] = m
    return list(best.values())


class MarkerEngine:
    def __init__(self, rules: list[dict[str, Any]]) -> None:
        self.rules = rules

    def evaluate(self, raw_json: dict[str, Any]) -> list[Marker]:
        return apply_marker_rules(raw_json, self.rules)
