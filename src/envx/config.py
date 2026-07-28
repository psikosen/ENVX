"""Runtime configuration.

Everything is environment-driven so the package behaves identically in
tests, local dev, and containerized workers. Defaults are chosen so that a
checkout with no environment set runs end-to-end in stub mode.

Model defaults reflect mid-2026 benchmarks:

  Parsing   PaddleOCR-VL-1.6 leads OmniDocBench v1.6 (96.34) over GLM-OCR
            (95.22); the gap is concentrated in the Hard subset — nested
            tables and dense formulas, which is what legal exhibits look
            like. Parsing and KIE are configured separately for this reason.
  KIE       GLM-OCR still leads open-weights schema-aware extraction.
  Embedding Voyage 4 family, Qwen3-Embedding-8B (best open general), or
            zembed-1 (open weights, strongest reported legal-domain NDCG@10).
  Rerank    zerank-2 or Qwen3-Reranker-4B. Note jina-reranker-v3 is
            CC BY-NC and cannot be used commercially.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class EnvxConfig:
    # --- storage -------------------------------------------------------
    wet_root: Path = field(default_factory=lambda: _env_path("ENVX_WET_ROOT", "./var/wet"))
    schemas_root: Path = field(
        default_factory=lambda: _env_path("ENVX_SCHEMAS_ROOT", "./schemas")
    )
    lexicon_path: Path = field(
        default_factory=lambda: _env_path("ENVX_LEXICON_PATH", "./lexicon/hazards.yml")
    )
    attestation_key_path: Path = field(
        default_factory=lambda: _env_path("ENVX_ATTEST_KEY", "./var/attest.key")
    )

    # --- GLM-OCR (KIE + rescue parsing) --------------------------------
    glm_ocr_url: str = field(default_factory=lambda: os.environ.get("ENVX_GLM_OCR_URL", ""))
    glm_ocr_model: str = field(
        default_factory=lambda: os.environ.get("ENVX_GLM_OCR_MODEL", "glm-ocr")
    )
    glm_ocr_timeout_s: float = field(
        default_factory=lambda: _env_float("ENVX_GLM_OCR_TIMEOUT", 120.0)
    )
    glm_ocr_stub: bool = field(default_factory=lambda: _env_bool("ENVX_GLM_OCR_STUB", False))

    # Parsing may target a different server than KIE — PaddleOCR-VL-1.6
    # outperforms GLM-OCR on parsing while GLM-OCR still wins KIE. Empty
    # means "reuse the GLM-OCR endpoint".
    parse_url: str = field(default_factory=lambda: os.environ.get("ENVX_PARSE_URL", ""))
    parse_model: str = field(
        default_factory=lambda: os.environ.get("ENVX_PARSE_MODEL", "paddleocr-vl")
    )

    # --- validation ----------------------------------------------------
    grounding_min_ratio: float = field(
        default_factory=lambda: _env_float("ENVX_GROUNDING_MIN_RATIO", 0.85)
    )
    twin_run_high_stakes: bool = field(
        default_factory=lambda: _env_bool("ENVX_TWIN_RUN", False)
    )

    # --- embeddings ----------------------------------------------------
    embedding_url: str = field(default_factory=lambda: os.environ.get("ENVX_EMBEDDING_URL", ""))
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("ENVX_EMBEDDING_MODEL", "voyage-4")
    )
    embedding_dim: int = field(default_factory=lambda: _env_int("ENVX_EMBEDDING_DIM", 1024))
    embedding_api_key: str = field(
        default_factory=lambda: os.environ.get("ENVX_EMBEDDING_API_KEY", "")
    )

    # --- reranker ------------------------------------------------------
    rerank_url: str = field(default_factory=lambda: os.environ.get("ENVX_RERANK_URL", ""))
    rerank_model: str = field(
        default_factory=lambda: os.environ.get("ENVX_RERANK_MODEL", "zerank-2")
    )
    rerank_api_key: str = field(
        default_factory=lambda: os.environ.get("ENVX_RERANK_API_KEY", "")
    )
    rerank_top_k: int = field(default_factory=lambda: _env_int("ENVX_RERANK_TOP_K", 15))

    # --- retrieval -----------------------------------------------------
    retrieval_top_k: int = field(default_factory=lambda: _env_int("ENVX_RETRIEVAL_TOP_K", 100))

    # --- database ------------------------------------------------------
    database_url: str = field(default_factory=lambda: os.environ.get("ENVX_DATABASE_URL", ""))

    @property
    def offline(self) -> bool:
        """True when no external inference endpoints are configured."""
        return not (self.glm_ocr_url or self.embedding_url or self.rerank_url)

    @property
    def effective_parse_url(self) -> str:
        return self.parse_url or self.glm_ocr_url


def load_config() -> EnvxConfig:
    return EnvxConfig()
