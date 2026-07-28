"""Structural chunker (architecture §2.5.3).

Chunk boundaries come from the GLM-OCR region map, not character windows.
A table is one chunk. A titled section is one chunk. A signature block is
its own chunk. This is the whole point of running layout detection on every
page: naive windowing splits tables mid-row and severs signatures from the
clauses they execute.

Algorithm:
    1. Assign each LiteParse text block to a region by bbox overlap (IoU,
       then center-containment fallback).
    2. Emit one chunk per region, text joined in reading order.
    3. Regions that are structurally meaningful but textless (signature,
       stamp, form_field) still emit a chunk — their *existence* is evidence.
    4. Blocks that land in no region become orphan chunks rather than being
       dropped. Losing source text here would be a correctness bug.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Iterable

from ..liteparse import LiteParseResult, PageBlock
from ..models import Region, RegionType


# Regions that carry meaning even with no extractable text.
_STRUCTURAL_EMPTY_OK = {
    RegionType.SIGNATURE,
    RegionType.STAMP,
    RegionType.FORM_FIELD,
}

# Regions we don't index — running headers/footers/page numbers are noise
# that dilutes BM25 and wastes embedding budget.
_SKIP_REGIONS = {
    RegionType.HEADER,
    RegionType.FOOTER,
    RegionType.PAGE_NUMBER,
}


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    page_number: int
    region_id: str | None
    region_type: str
    bbox: tuple[int, int, int, int] | None
    text: str
    content_hash: str


def _hash(text: str, bbox: tuple[int, int, int, int] | None) -> str:
    norm = re.sub(r"\s+", " ", text).strip().casefold()
    return hashlib.sha256(f"{bbox}|{norm}".encode()).hexdigest()


def _containment(block: tuple[int, int, int, int], region: tuple[int, int, int, int]) -> float:
    """Fraction of ``block``'s area that falls inside ``region``.

    Deliberately not IoU: a one-line text block sitting inside a full-page
    table region should score 1.0, but IoU would score it near zero and hand
    the block to whichever tiny region happened to clip its edge.
    """
    ix0, iy0 = max(block[0], region[0]), max(block[1], region[1])
    ix1, iy1 = min(block[2], region[2]), min(block[3], region[3])
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    if inter == 0:
        return 0.0
    block_area = max(0, block[2] - block[0]) * max(0, block[3] - block[1])
    return inter / block_area if block_area > 0 else 0.0


def _center_inside(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")


def _split_long(text: str, max_chars: int) -> list[str]:
    """Sentence-aware split for regions that blow past the size ceiling.

    Tables are exempt from this at the call site — splitting a table mid-row
    defeats the purpose of structural chunking.
    """
    if len(text) <= max_chars:
        return [text] if text else []
    out: list[str] = []
    buf: list[str] = []
    length = 0
    for sentence in _SENTENCE_SPLIT.split(text):
        if length + len(sentence) + 1 > max_chars and buf:
            out.append(" ".join(buf).strip())
            buf, length = [sentence], len(sentence)
        else:
            buf.append(sentence)
            length += len(sentence) + 1
    if buf:
        out.append(" ".join(buf).strip())
    return [c for c in out if c]


class StructuralChunker:
    def __init__(self, *, max_chars: int = 2400) -> None:
        self.max_chars = max_chars

    def chunk(
        self,
        *,
        doc_id: str,
        liteparse: LiteParseResult,
        regions: Iterable[Region],
    ) -> list[Chunk]:
        stamped = [_ensure_id(r) for r in regions]
        by_page: dict[int, list[Region]] = {}
        for r in stamped:
            by_page.setdefault(r.page_number, []).append(r)

        chunks: list[Chunk] = []
        for page in liteparse.pages:
            page_regions = by_page.get(page.page_number, [])
            buckets: dict[str | None, list[PageBlock]] = {}
            for block in page.blocks:
                buckets.setdefault(self._assign(block, page_regions), []).append(block)

            for region in page_regions:
                if region.region_type in _SKIP_REGIONS:
                    continue
                blocks = buckets.get(region.region_id, [])
                text = "\n\n".join(b.text for b in blocks).strip()
                if not text and region.region_type not in _STRUCTURAL_EMPTY_OK:
                    continue
                # Tables stay whole regardless of length.
                pieces = (
                    [text]
                    if region.region_type is RegionType.TABLE
                    else (_split_long(text, self.max_chars) or [text])
                )
                for piece in pieces:
                    chunks.append(
                        self._make(doc_id, page.page_number, region, piece)
                    )

            for piece in _split_long(
                "\n\n".join(b.text for b in buckets.get(None, [])).strip(),
                self.max_chars,
            ):
                chunks.append(self._make(doc_id, page.page_number, None, piece))
        return chunks

    def _make(
        self,
        doc_id: str,
        page_number: int,
        region: Region | None,
        text: str,
    ) -> Chunk:
        bbox = region.bbox if region else None
        rtype = region.region_type.value if region else RegionType.PARAGRAPH.value
        return Chunk(
            chunk_id=str(uuid.uuid4()),
            doc_id=doc_id,
            page_number=page_number,
            region_id=region.region_id if region else None,
            region_type=rtype,
            bbox=bbox,
            text=text,
            content_hash=_hash(text, bbox),
        )

    def _assign(self, block: PageBlock, regions: list[Region]) -> str | None:
        best: tuple[float, Region] | None = None
        for r in regions:
            score = _containment(block.bbox, r.bbox)
            if score > 0 and (best is None or score > best[0]):
                best = (score, r)
        # Majority of the block must sit in the region to claim it.
        if best is not None and best[0] >= 0.5:
            return best[1].region_id
        for r in regions:
            if _center_inside(r.bbox, block.bbox):
                return r.region_id
        return None


def _ensure_id(r: Region) -> Region:
    if r.region_id is not None:
        return r
    return Region(
        page_number=r.page_number,
        bbox=r.bbox,
        region_type=r.region_type,
        label_confidence=r.label_confidence,
        region_id=str(uuid.uuid4()),
    )
