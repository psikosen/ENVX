"""Retrieval metrics.

Standard IR measures, computed at the document level rather than the chunk
level: a lawyer asks "which documents say this", and two chunks from the
same document are one answer, not two.

Which metric matters depends on the question being asked:

    Recall@k   did we surface it at all? The one that matters for
               discovery — a missed responsive document is the expensive
               kind of error.
    MRR        how far down was the first correct answer?
    nDCG@k     rank-weighted, credits getting several right ones high.
    P@k        precision, the cost of reading noise.

No external dependency; the corpus is small enough that clarity beats
speed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable, Sequence


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 1.0
    return len(relevant_set & set(ranked[:k])) / len(relevant_set)


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(relevant) & set(ranked[:k])) / k


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    relevant_set = set(relevant)
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant_set:
            return 1.0 / position
    return 0.0


def average_precision(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 1.0
    hits = 0
    total = 0.0
    for position, doc in enumerate(ranked, start=1):
        if doc in relevant_set:
            hits += 1
            total += hits / position
    return total / len(relevant_set)


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary-relevance nDCG."""
    relevant_set = set(relevant)
    if not relevant_set:
        return 1.0
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, doc in enumerate(ranked[:k], start=1)
        if doc in relevant_set
    )
    ideal = sum(
        1.0 / math.log2(position + 1)
        for position in range(1, min(len(relevant_set), k) + 1)
    )
    return dcg / ideal if ideal else 0.0


@dataclass
class QueryResult:
    query_id: str
    ranked: list[str]
    relevant: tuple[str, ...]
    tags: tuple[str, ...] = ()

    def metrics(self, ks: Sequence[int] = (1, 3, 5, 10)) -> dict[str, float]:
        out: dict[str, float] = {}
        for k in ks:
            out[f"recall@{k}"] = recall_at_k(self.ranked, self.relevant, k)
            out[f"p@{k}"] = precision_at_k(self.ranked, self.relevant, k)
        out["mrr"] = reciprocal_rank(self.ranked, self.relevant)
        out["map"] = average_precision(self.ranked, self.relevant)
        out["ndcg@10"] = ndcg_at_k(self.ranked, self.relevant, 10)
        return out

    @property
    def found_any(self) -> bool:
        return bool(set(self.ranked) & set(self.relevant))


@dataclass
class RunMetrics:
    label: str
    per_query: list[QueryResult] = field(default_factory=list)

    def aggregate(self, ks: Sequence[int] = (1, 3, 5, 10)) -> dict[str, float]:
        if not self.per_query:
            return {}
        rows = [q.metrics(ks) for q in self.per_query]
        return {key: mean(row[key] for row in rows) for key in rows[0]}

    @property
    def total_failures(self) -> list[str]:
        """Queries that surfaced nothing relevant at any rank.

        Called out separately because a mean hides them, and in a legal
        setting a query that returns nothing responsive is a different
        class of problem from one that ranks poorly.
        """
        return [q.query_id for q in self.per_query if not q.found_any]

    def by_tag(self, ks: Sequence[int] = (5,)) -> dict[str, dict[str, float]]:
        tags: dict[str, list[QueryResult]] = {}
        for q in self.per_query:
            for tag in q.tags:
                tags.setdefault(tag, []).append(q)
        return {
            tag: RunMetrics(label=tag, per_query=qs).aggregate(ks)
            for tag, qs in sorted(tags.items())
        }


def summarize(runs: Sequence[RunMetrics], ks: Sequence[int] = (1, 3, 5, 10)) -> str:
    """Render a comparison table across configurations."""
    if not runs:
        return "no runs"
    columns = ["recall@1", "recall@5", "recall@10", "mrr", "ndcg@10", "map"]
    width = max(len(r.label) for r in runs) + 2
    header = "configuration".ljust(width) + "".join(c.rjust(11) for c in columns)
    lines = [header, "-" * len(header)]
    for run in runs:
        agg = run.aggregate(ks)
        row = run.label.ljust(width)
        row += "".join(f"{agg.get(c, 0.0):11.3f}" for c in columns)
        misses = len(run.total_failures)
        if misses:
            row += f"   ({misses} total miss{'es' if misses > 1 else ''})"
        lines.append(row)
    return "\n".join(lines)
