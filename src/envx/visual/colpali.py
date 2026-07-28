"""Late-interaction visual retrieval (architecture §3.2 Path 3).

For scanned exhibits, signatures, stamps, redactions, and handwritten
margin notes — evidence that exists as pixels and never becomes good text.
Multi-vector late interaction still beats single-vector multimodal
embeddings on ViDoRe-style benchmarks, so this stays a separate path rather
than folding into the dense path.

Backends worth pointing this at (mid-2026): nemotron-colembed-vl-8b-v2,
Qwen3-VL-Embedding, or jina-embeddings-v4 in multi-vector mode. Token
pooling at factor 3 cuts storage ~67% for ~2% recall loss, which is what
makes multi-vector affordable at corpus scale.

Patch-to-region grounding follows Snappy (arXiv 2512.02660): patch
similarities map back onto OCR bboxes so a visual hit cites coordinates,
not just a page. For legal use that distinction is the whole point — "page
7" is not a citation, "the signature block at these coordinates on page 7"
is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

from ..models import Region


@dataclass(frozen=True)
class PatchMatch:
    doc_id: str
    page_number: int
    score: float
    bbox: tuple[int, int, int, int] | None = None
    region_id: str | None = None
    region_type: str | None = None
    reason: str = ""


class VisualBackend(Protocol):
    model_id: str

    def search(
        self,
        *,
        query: str,
        doc_ids: Iterable[str] | None,
        top_k: int,
    ) -> list[PatchMatch]: ...


@dataclass
class _IndexedPage:
    doc_id: str
    page_number: int
    doc_type: str
    visual_terms: tuple[str, ...]
    regions: tuple[Region, ...] = field(default_factory=tuple)


_WORD_RE = re.compile(r"[a-z0-9']+")


def _terms(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.casefold()))


# Region types that visual retrieval is uniquely good at finding.
_VISUAL_REGION_PRIORITY = ("signature", "stamp", "figure", "form_field", "table")


class StubVisualBackend:
    """Offline stand-in ranking pages by declared visual cues.

    Not a model. It exists so the visual path can be wired, scoped, fused,
    and grounded end-to-end without a GPU — the retrieval plumbing is what
    we're validating here, not recall quality.
    """

    model_id = "envx-stub-visual/1"

    def __init__(self) -> None:
        self._pages: list[_IndexedPage] = []

    def index_page(
        self,
        *,
        doc_id: str,
        page_number: int,
        doc_type: str,
        visual_terms: Iterable[str],
        regions: Sequence[Region] = (),
    ) -> None:
        self._pages.append(
            _IndexedPage(
                doc_id=doc_id,
                page_number=page_number,
                doc_type=doc_type,
                visual_terms=tuple(t.casefold() for t in visual_terms),
                regions=tuple(regions),
            )
        )

    def search(
        self,
        *,
        query: str,
        doc_ids: Iterable[str] | None,
        top_k: int,
    ) -> list[PatchMatch]:
        allowed = set(doc_ids) if doc_ids is not None else None
        query_terms = _terms(query)
        matches: list[PatchMatch] = []
        for page in self._pages:
            if allowed is not None and page.doc_id not in allowed:
                continue
            overlap = query_terms.intersection(page.visual_terms)
            if not overlap:
                continue
            region = _best_region(page.regions, overlap)
            matches.append(
                PatchMatch(
                    doc_id=page.doc_id,
                    page_number=page.page_number,
                    score=len(overlap) / max(len(query_terms), 1),
                    bbox=region.bbox if region else None,
                    region_id=region.region_id if region else None,
                    region_type=region.region_type.value if region else None,
                    reason="visual cues: " + ", ".join(sorted(overlap)),
                )
            )
        matches.sort(key=lambda m: (-m.score, m.doc_id, m.page_number))
        return matches[:top_k]


def _best_region(regions: Sequence[Region], overlap: set[str]) -> Region | None:
    """Ground a page-level hit to a region (Snappy-style, simplified).

    Prefer a region whose type the query actually named, then fall back to
    the most visually distinctive region on the page.
    """
    if not regions:
        return None
    for term in overlap:
        for region in regions:
            if region.region_type.value == term:
                return region
    for wanted in _VISUAL_REGION_PRIORITY:
        for region in regions:
            if region.region_type.value == wanted:
                return region
    return regions[0]


# Doc classes where pixels routinely carry evidence text extraction misses.
DEFAULT_HIGH_RISK_DOC_TYPES = frozenset(
    {"insurance_claim", "inspection_report", "medical_record", "property_disclosure"}
)


class VisualRetriever:
    """Gates the visual path on high-risk doc classes.

    Visual inference is orders of magnitude more expensive than BM25, so it
    runs only where scanned/handwritten evidence is plausible — or when the
    query explicitly asks about visual artifacts.
    """

    _VISUAL_INTENT = frozenset(
        {
            "signature", "signatures", "signed", "initialed", "initials",
            "stamp", "stamped", "seal", "notary", "notarized",
            "handwritten", "handwriting", "annotation", "annotations",
            "margin", "redacted", "redaction", "diagram", "sketch",
            "photo", "photograph", "illegible", "checkbox", "checked",
        }
    )

    def __init__(
        self,
        backend: VisualBackend,
        *,
        high_risk_doc_types: Iterable[str] = DEFAULT_HIGH_RISK_DOC_TYPES,
    ) -> None:
        self.backend = backend
        self.high_risk_doc_types = frozenset(high_risk_doc_types)

    def should_run(self, *, query: str, doc_types: Iterable[str] | None) -> bool:
        if _terms(query).intersection(self._VISUAL_INTENT):
            return True
        if not doc_types:
            return False
        return bool(self.high_risk_doc_types.intersection(doc_types))

    def search(
        self,
        *,
        query: str,
        doc_types: Iterable[str] | None = None,
        doc_ids: Iterable[str] | None = None,
        top_k: int = 20,
        force: bool = False,
    ) -> list[PatchMatch]:
        if not force and not self.should_run(query=query, doc_types=doc_types):
            return []
        return self.backend.search(query=query, doc_ids=doc_ids, top_k=top_k)
