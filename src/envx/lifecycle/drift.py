"""Drift monitoring (architecture §10.18).

Sample 1% of the corpus weekly, re-parse and re-KIE with current models,
and flag any document whose marker set changed. Marker churn is the signal
that matters: if a model upgrade silently drops a ``RISK:ASBESTOS`` off a
document that had one, that is a regression with legal consequences, and
nobody would notice from aggregate accuracy metrics.

Sampling is deterministic given a seed so a run can be reproduced during an
audit — "which documents did the March sample cover" needs an answer.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Sequence


@dataclass(frozen=True)
class DriftFinding:
    doc_id: str
    added_markers: tuple[str, ...]
    removed_markers: tuple[str, ...]
    confidence_shifts: tuple[tuple[str, float, float], ...] = ()

    @property
    def is_regression(self) -> bool:
        """A marker disappearing is worse than one appearing.

        A new marker is a finding to verify. A vanished RISK/CLAUSE marker is
        evidence we used to surface and no longer do.
        """
        return any(m.startswith(("RISK:", "CLAUSE:")) for m in self.removed_markers)

    @property
    def severity(self) -> str:
        if self.is_regression:
            return "regression"
        if self.added_markers or self.removed_markers:
            return "changed"
        return "stable"


def compare_marker_sets(
    *,
    doc_id: str,
    baseline: dict[str, float],
    current: dict[str, float],
    confidence_delta_threshold: float = 0.15,
) -> DriftFinding | None:
    added = tuple(sorted(set(current) - set(baseline)))
    removed = tuple(sorted(set(baseline) - set(current)))
    shifts = tuple(
        (code, baseline[code], current[code])
        for code in sorted(set(baseline) & set(current))
        if abs(current[code] - baseline[code]) >= confidence_delta_threshold
    )
    if not (added or removed or shifts):
        return None
    return DriftFinding(
        doc_id=doc_id,
        added_markers=added,
        removed_markers=removed,
        confidence_shifts=shifts,
    )


@dataclass
class DriftReport:
    sampled_at: datetime
    sample_size: int
    findings: list[DriftFinding] = field(default_factory=list)

    @property
    def regressions(self) -> list[DriftFinding]:
        return [f for f in self.findings if f.is_regression]

    @property
    def drift_rate(self) -> float:
        return len(self.findings) / self.sample_size if self.sample_size else 0.0

    def summary(self) -> dict[str, object]:
        return {
            "sampled_at": self.sampled_at.isoformat(),
            "sample_size": self.sample_size,
            "changed": len(self.findings),
            "regressions": len(self.regressions),
            "drift_rate": round(self.drift_rate, 4),
        }


class DriftSampler:
    def __init__(self, *, sample_rate: float = 0.01, seed: int | None = None) -> None:
        if not 0 < sample_rate <= 1:
            raise ValueError("sample_rate must be in (0, 1]")
        self.sample_rate = sample_rate
        self.seed = seed

    def select(self, doc_ids: Sequence[str], *, period: str = "") -> list[str]:
        """Deterministically pick the sample for a period.

        Seeding from (seed, period) means re-running the same week's sample
        reproduces it exactly, while consecutive weeks cover different docs.
        """
        if not doc_ids:
            return []
        target = max(1, round(len(doc_ids) * self.sample_rate))
        digest = hashlib.blake2s(f"{self.seed}:{period}".encode(), digest_size=8).digest()
        rng = random.Random(int.from_bytes(digest, "big"))
        return sorted(rng.sample(sorted(doc_ids), min(target, len(doc_ids))))

    def run(
        self,
        *,
        doc_ids: Sequence[str],
        baseline: dict[str, dict[str, float]],
        reprocess: "callable",  # type: ignore[valid-type]
        period: str = "",
        now: datetime | None = None,
    ) -> DriftReport:
        """Re-process the sample and diff marker sets against the baseline.

        ``reprocess(doc_id) -> dict[marker_code, confidence]`` is injected so
        this module stays independent of how re-parsing is wired.
        """
        selected = self.select(doc_ids, period=period)
        report = DriftReport(
            sampled_at=now or datetime.now(timezone.utc),
            sample_size=len(selected),
        )
        for doc_id in selected:
            finding = compare_marker_sets(
                doc_id=doc_id,
                baseline=baseline.get(doc_id, {}),
                current=reprocess(doc_id),
            )
            if finding is not None:
                report.findings.append(finding)
        return report
