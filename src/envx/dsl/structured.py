"""Structured metadata filtering — Path 5 (architecture §3.2, §6).

Queries the ``extracted_fields`` table directly. Per §3.2 this is a
*pre-filter*, never fused: "all environmental reports with Phase II required
and property in Fairfield County" is a SQL question, not a retrieval one.
Answering it with embeddings would be both slower and wrong.

The DSL exposes a deliberately small predicate language rather than raw SQL.
Plans are authored by an LLM, and an LLM that can emit arbitrary SQL against
a multi-client legal corpus is a security problem, not a feature. Every
predicate compiles to a parameterised query over a fixed table.

Grammar::

    <path> <op> <value>
    <expr> AND <expr>
    <expr> OR <expr>

    path   JSONPath-ish: $.hazards_disclosed[*].type
    op     = != > >= < <= IN LIKE EXISTS
    value  'quoted string' | number | (a, b, c) | true | false

Examples::

    $.conclusions.requires_phase_ii = true
    $.hazards_disclosed[*].type IN ('asbestos', 'acm')
    $.recs[*] EXISTS
    $.property.address_city = 'Fairfield' AND $.report_type = 'phase_i'

Array wildcards match if *any* element satisfies the predicate, which is the
semantics a lawyer expects from "documents that disclose asbestos".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence


class FilterSyntaxError(ValueError):
    pass


_OPS = ("!=", ">=", "<=", "=", ">", "<")
_TOKEN_RE = re.compile(
    r"""
    (?P<path>\$[A-Za-z0-9_.\[\]*]+)
    \s*
    (?:
        (?P<exists>EXISTS)
      | (?P<in>IN)\s*\((?P<inlist>[^)]*)\)
      | (?P<like>LIKE)\s*(?P<likeval>'[^']*')
      | (?P<op>!=|>=|<=|=|>|<)\s*(?P<value>'[^']*'|[-+]?[0-9]*\.?[0-9]+|true|false|null)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass(frozen=True)
class Predicate:
    field_path: str
    op: str
    value: Any

    @property
    def is_wildcard(self) -> bool:
        return "[*]" in self.field_path


@dataclass(frozen=True)
class CompiledFilter:
    sql: str
    params: list[Any]
    predicates: tuple[Predicate, ...]

    def describe(self) -> str:
        return " AND ".join(f"{p.field_path} {p.op} {p.value!r}" for p in self.predicates)


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    low = text.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null":
        return None
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text


def parse_expression(expression: str) -> tuple[list[Predicate], str]:
    """Parse a filter expression into predicates plus their joining operator.

    Mixing AND and OR in one expression is rejected rather than silently
    picking a precedence. "asbestos AND lead OR mold" means materially
    different things under different groupings, and guessing wrong on a
    hazard query is not an acceptable failure mode.
    """
    if not expression or not expression.strip():
        return [], "AND"

    has_and = re.search(r"\bAND\b", expression, re.IGNORECASE) is not None
    has_or = re.search(r"\bOR\b", expression, re.IGNORECASE) is not None
    if has_and and has_or:
        raise FilterSyntaxError(
            "mixing AND and OR in one expression is ambiguous; "
            "use separate 'where' and 'or' clauses"
        )
    joiner = "OR" if has_or else "AND"

    predicates: list[Predicate] = []
    spans: list[tuple[int, int]] = []
    for match in _TOKEN_RE.finditer(expression):
        spans.append(match.span())
        path = match.group("path")
        if match.group("exists"):
            predicates.append(Predicate(path, "EXISTS", None))
        elif match.group("in"):
            items = [
                _parse_scalar(part)
                for part in match.group("inlist").split(",")
                if part.strip()
            ]
            if not items:
                raise FilterSyntaxError(f"empty IN list for {path}")
            predicates.append(Predicate(path, "IN", items))
        elif match.group("like"):
            predicates.append(Predicate(path, "LIKE", _parse_scalar(match.group("likeval"))))
        else:
            predicates.append(
                Predicate(path, match.group("op"), _parse_scalar(match.group("value")))
            )

    if not predicates:
        raise FilterSyntaxError(f"no valid predicate found in {expression!r}")

    leftover = _unconsumed(expression, spans)
    if leftover:
        # Silently ignoring the remainder would let a malformed or injected
        # expression apply a filter narrower than what was written, which is
        # the "quietly did something else" failure the plan compiler exists
        # to prevent. Reject instead.
        raise FilterSyntaxError(
            f"unparsed content in filter expression: {leftover!r}"
        )
    return predicates, joiner


_NOISE_RE = re.compile(r"\b(AND|OR)\b|[\s]+", re.IGNORECASE)


def _unconsumed(expression: str, spans: Sequence[tuple[int, int]]) -> str:
    """Return anything outside the matched predicates, ignoring joiners."""
    remaining: list[str] = []
    cursor = 0
    for start, end in spans:
        remaining.append(expression[cursor:start])
        cursor = end
    remaining.append(expression[cursor:])
    return _NOISE_RE.sub("", "".join(remaining)).strip()


def _path_condition(predicate: Predicate) -> tuple[str, list[Any]]:
    """Render one predicate as SQL over ``extracted_fields``.

    Wildcard paths are matched with LIKE against the concrete stored path
    ($.recs[0].rec_type), since flattening writes real indexes, not the
    wildcard. The wildcard is escaped so a literal % or _ in a field name
    cannot turn into an unintended pattern.
    """
    if predicate.is_wildcard:
        pattern = re.escape(predicate.field_path).replace(r"\[\*\]", "[%]")
        pattern = pattern.replace("\\", "")
        path_sql = "ef.field_path LIKE %s"
        path_params: list[Any] = [pattern]
    else:
        path_sql = "ef.field_path = %s"
        path_params = [predicate.field_path]

    if predicate.op == "EXISTS":
        return f"({path_sql})", path_params

    value = predicate.value
    if predicate.op == "IN":
        placeholders = ", ".join(["%s"] * len(value))
        return (
            f"({path_sql} AND lower(ef.field_value_text) IN ({placeholders}))",
            path_params + [str(v).lower() for v in value],
        )
    if predicate.op == "LIKE":
        return (
            f"({path_sql} AND ef.field_value_text ILIKE %s)",
            path_params + [value],
        )
    if isinstance(value, bool):
        return (
            f"({path_sql} AND lower(ef.field_value_text) = %s)",
            path_params + ["true" if value else "false"],
        )
    if isinstance(value, (int, float)):
        return (
            f"({path_sql} AND ef.field_value_num {predicate.op} %s)",
            path_params + [value],
        )
    if predicate.op == "=":
        return (
            f"({path_sql} AND lower(ef.field_value_text) = %s)",
            path_params + [str(value).lower()],
        )
    if predicate.op == "!=":
        return (
            f"({path_sql} AND lower(ef.field_value_text) <> %s)",
            path_params + [str(value).lower()],
        )
    return (
        f"({path_sql} AND ef.field_value_text {predicate.op} %s)",
        path_params + [str(value)],
    )


def compile_filter(
    *,
    where: str | None = None,
    or_where: str | None = None,
    client_id: str | None = None,
    matter_id: str | None = None,
    doc_types: Sequence[str] | None = None,
    require_grounded: bool = False,
) -> CompiledFilter:
    """Compile a structured filter into a parameterised doc_id query.

    Returns document ids, not chunks: this is a pre-filter that narrows the
    corpus before the retrieval paths run.
    """
    clauses: list[str] = []
    params: list[Any] = []
    predicates: list[Predicate] = []

    for expression in (where, or_where):
        if not expression:
            continue
        parsed, joiner = parse_expression(expression)
        predicates.extend(parsed)
        rendered: list[str] = []
        for predicate in parsed:
            sql, sql_params = _path_condition(predicate)
            rendered.append(sql)
            params.extend(sql_params)
        if not rendered:
            continue
        if joiner == "AND" and len(rendered) > 1:
            # Each predicate must be satisfied by some row for the same
            # document, so AND becomes an intersection of doc_id sets rather
            # than a single row satisfying every condition at once.
            clauses.append(_intersect(rendered))
        else:
            clauses.append(f"({' OR '.join(rendered)})")

    if not clauses:
        raise FilterSyntaxError("structured filter has no predicates")

    scope: list[str] = []
    if client_id:
        scope.append("d.client_id = %s")
        params.append(client_id)
    if matter_id:
        scope.append("d.matter_id = %s")
        params.append(matter_id)
    if doc_types:
        scope.append("d.doc_type = ANY(%s)")
        params.append(list(doc_types))
    if require_grounded:
        # Exclude values the grounding check could not find in the source.
        scope.append("ef.grounding_status <> 'failed'")

    # OR across the where/or clauses, matching the §6 plan shape where
    # `structured_filter.or` widens rather than narrows.
    body = " OR ".join(clauses) if len(clauses) > 1 else clauses[0]
    sql = (
        "SELECT DISTINCT ef.doc_id"
        "  FROM extracted_fields ef"
        "  JOIN documents d ON d.doc_id = ef.doc_id"
        f" WHERE ({body})"
    )
    if scope:
        sql += " AND " + " AND ".join(scope)
    return CompiledFilter(sql=sql, params=params, predicates=tuple(predicates))


def _intersect(rendered: Sequence[str]) -> str:
    """AND across predicates that each live on different rows.

    Subqueries alias the table separately from the outer query. Reusing the
    outer alias would shadow it, and each predicate would then be evaluated
    against the outer row rather than independently — turning the
    intersection back into the impossible single-row conjunction it exists
    to avoid.
    """
    parts: list[str] = []
    for i, clause in enumerate(rendered):
        alias = f"efi{i}"
        parts.append(
            f"SELECT {alias}.doc_id FROM extracted_fields {alias}"
            f" WHERE {clause.replace('ef.', alias + '.')}"
        )
    return f"ef.doc_id IN ({' INTERSECT '.join(parts)})"
