"""Runtime configuration for the ENVX preprocessing layer.

Values are read from environment variables so the package works
the same in tests, local dev, and containerized workers.
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


@dataclass(frozen=True)
class EnvxConfig:
    wet_root: Path = field(default_factory=lambda: _env_path("ENVX_WET_ROOT", "./var/wet"))
    schemas_root: Path = field(default_factory=lambda: _env_path("ENVX_SCHEMAS_ROOT", "./schemas"))
    attestation_key_path: Path = field(
        default_factory=lambda: _env_path("ENVX_ATTEST_KEY", "./var/attest.key")
    )
    glm_ocr_url: str = field(default_factory=lambda: os.environ.get("ENVX_GLM_OCR_URL", ""))
    glm_ocr_model: str = field(
        default_factory=lambda: os.environ.get("ENVX_GLM_OCR_MODEL", "glm-ocr")
    )
    glm_ocr_timeout_s: float = field(
        default_factory=lambda: float(os.environ.get("ENVX_GLM_OCR_TIMEOUT", "120"))
    )
    glm_ocr_stub: bool = field(default_factory=lambda: _env_bool("ENVX_GLM_OCR_STUB", False))
    grounding_min_ratio: float = field(
        default_factory=lambda: float(os.environ.get("ENVX_GROUNDING_MIN_RATIO", "0.85"))
    )


def load_config() -> EnvxConfig:
    return EnvxConfig()
