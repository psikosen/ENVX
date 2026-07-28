"""LiteParse Tier A adapter.

LiteParse (run-llama) is a TS/Node tool. We bridge to it as a subprocess when
the ``liteparse`` CLI is on PATH; otherwise a deterministic stub synthesizes
equivalent structure from text so the rest of the pipeline runs without Node.

Tier A gives us, per architecture §2:
    - native text with per-block bboxes
    - page dimensions and optional rendered screenshots
    - quality signals that drive Tier B rescue: ``native_text_coverage``,
      ``roundtrip_score``, ``garbled_rate``

The trust signals matter more than the text: they're what decides whether a
page goes to GLM-OCR for rescue.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PageBlock:
    bbox: tuple[int, int, int, int]
    text: str


@dataclass(frozen=True)
class LiteParsePage:
    page_number: int
    width_px: int
    height_px: int
    text: str
    blocks: list[PageBlock]
    native_text_coverage: float
    roundtrip_score: float
    garbled_rate: float = 0.0
    image_path: Path | None = None

    @property
    def needs_rescue(self) -> bool:
        """Tier B trigger (§2 Tier B).

        Sparse native text or high garbling means LiteParse didn't really read
        the page — send it to GLM-OCR.
        """
        return self.native_text_coverage < 0.60 or self.garbled_rate > 0.25


@dataclass(frozen=True)
class LiteParseResult:
    pages: list[LiteParsePage]
    parser_version: str

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def rescue_pages(self) -> list[int]:
        return [p.page_number for p in self.pages if p.needs_rescue]


class LiteParseAdapter(Protocol):
    def parse(self, pdf_path: Path, *, workdir: Path) -> LiteParseResult: ...


def liteparse_on_path() -> bool:
    return shutil.which("liteparse") is not None


class SubprocessLiteParse:
    """Bridge to the real ``liteparse`` CLI."""

    def __init__(self, binary: str = "liteparse", extra_args: list[str] | None = None) -> None:
        self.binary = binary
        self.extra_args = extra_args or []

    def parse(self, pdf_path: Path, *, workdir: Path) -> LiteParseResult:
        workdir.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                self.binary,
                "--json",
                "--emit-images",
                str(workdir),
                *self.extra_args,
                str(pdf_path),
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        return payload_to_result(json.loads(proc.stdout))


def payload_to_result(payload: dict) -> LiteParseResult:
    pages: list[LiteParsePage] = []
    for p in payload.get("pages", []):
        blocks = [
            PageBlock(bbox=tuple(b["bbox"]), text=b.get("text", ""))  # type: ignore[arg-type]
            for b in p.get("blocks", [])
            if len(b.get("bbox", [])) == 4
        ]
        text = p.get("text") or "\n\n".join(b.text for b in blocks)
        pages.append(
            LiteParsePage(
                page_number=int(p["page_number"]),
                width_px=int(p.get("width_px", 0)),
                height_px=int(p.get("height_px", 0)),
                text=text,
                blocks=blocks,
                native_text_coverage=float(p.get("native_text_coverage", 0.0)),
                roundtrip_score=float(p.get("roundtrip_score", 0.0)),
                garbled_rate=float(p.get("garbled_rate", 0.0)),
                image_path=Path(p["image_path"]) if p.get("image_path") else None,
            )
        )
    return LiteParseResult(pages=pages, parser_version=str(payload.get("version", "unknown")))


_PAGE_SEP = re.compile(r"\n?\f\n?|\n\s*---+ ?page ?\d* ?---+\s*\n", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z]{2,}")
# Runs of consonants or symbol soup that signal OCR garbling.
_GARBLE_RE = re.compile(r"[bcdfghjklmnpqrstvwxz]{5,}|[^\w\s]{4,}", re.IGNORECASE)


def _garbled_rate(text: str) -> float:
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    bad = sum(1 for w in words if _GARBLE_RE.search(w))
    return bad / len(words)


class StubLiteParse:
    """Deterministic stand-in used when LiteParse isn't installed.

    Accepts text directly (``parse_text``) or reads a UTF-8 file. Produces
    plausible bboxes and real quality signals computed from the text, so
    Tier B rescue decisions still exercise meaningful logic.
    """

    def __init__(self, *, default_page_text: str | None = None) -> None:
        self.default_page_text = default_page_text

    def parse(self, pdf_path: Path, *, workdir: Path) -> LiteParseResult:
        if self.default_page_text is not None:
            text = self.default_page_text
        elif pdf_path.exists():
            text = pdf_path.read_text(errors="replace")
        else:
            text = ""
        return self.parse_text(text)

    def parse_text(self, text: str) -> LiteParseResult:
        raw_pages = _split_pages(text) or [text]
        pages: list[LiteParsePage] = []
        for i, page_text in enumerate(raw_pages, start=1):
            blocks = _synthesize_blocks(page_text)
            coverage = 1.0 if page_text.strip() else 0.0
            garbled = _garbled_rate(page_text)
            pages.append(
                LiteParsePage(
                    page_number=i,
                    width_px=612,
                    height_px=792,
                    text=page_text,
                    blocks=blocks,
                    native_text_coverage=coverage,
                    roundtrip_score=max(0.0, coverage - garbled),
                    garbled_rate=garbled,
                )
            )
        return LiteParseResult(pages=pages, parser_version="stub/0.1")


def _split_pages(text: str) -> list[str]:
    if not text:
        return []
    parts = [p for p in _PAGE_SEP.split(text) if p.strip()]
    return parts if parts else [text]


def _synthesize_blocks(page_text: str) -> list[PageBlock]:
    """One block per paragraph, stacked top-to-bottom on a Letter-size page.

    Exact coordinates don't matter downstream — the structural chunker keys
    off region overlap, and regions come from GLM-OCR — but they must be
    ordered and non-overlapping so overlap math behaves.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page_text) if p.strip()]
    blocks: list[PageBlock] = []
    y = 40
    for para in paragraphs:
        height = 20 + 12 * para.count("\n")
        blocks.append(PageBlock(bbox=(50, y, 562, y + height), text=para))
        y += height + 10
    return blocks
