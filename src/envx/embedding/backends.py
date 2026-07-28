"""Embedding backends.

Production points ``HTTPEmbedding`` at an OpenAI-compatible embeddings
endpoint — that covers Voyage, OpenAI, and a locally served bge-m3 or
Qwen3-Embedding behind vLLM/TEI. The model name and dimensionality are
config, not code.

``HashingEmbedding`` is a deterministic offline stand-in: token hashing with
sublinear TF weighting and L2 normalization. It is emphatically *not* a
semantic model — it captures lexical overlap only — but it makes the whole
retrieval path runnable and debuggable with no GPU and no API key. Every
vector carries its ``model_id`` so a mismatched index fails loudly instead
of silently returning garbage.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

import httpx


Vector = list[float]


class EmbeddingBackend(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: Sequence[str]) -> list[Vector]: ...


_WORD_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.casefold())


def normalize(vec: Vector) -> Vector:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def cosine_similarity(a: Vector, b: Vector) -> float:
    if not a or not b:
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(x * x for x in b))
    return num / (da * db) if da and db else 0.0


class HashingEmbedding:
    """Offline deterministic embedding. Lexical, not semantic."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.model_id = f"envx-hashing-{dim}/1"

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        out: list[Vector] = []
        for text in texts:
            vec = [0.0] * self.dim
            counts: dict[int, int] = {}
            for tok in _tokens(text):
                idx = (
                    int.from_bytes(hashlib.blake2s(tok.encode(), digest_size=4).digest(), "big")
                    % self.dim
                )
                counts[idx] = counts.get(idx, 0) + 1
            for idx, count in counts.items():
                vec[idx] = math.log1p(count)
            out.append(normalize(vec))
        return out


class HTTPEmbedding:
    """OpenAI-compatible ``/v1/embeddings`` client.

    Works against Voyage, OpenAI, and self-hosted vLLM / text-embeddings-
    inference servers. Batches are the caller's responsibility to size; most
    providers cap request payloads well below our chunk volumes.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        api_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self.model_id = model
        self.dim = dim
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout_s

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        if not texts:
            return []
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._base_url}/v1/embeddings",
                headers=self._headers,
                json={"model": self.model_id, "input": list(texts)},
            )
        resp.raise_for_status()
        payload = resp.json()
        # Providers don't guarantee ordering; sort by index defensively.
        rows = sorted(payload["data"], key=lambda d: d.get("index", 0))
        vectors = [row["embedding"] for row in rows]
        for vec in vectors:
            if len(vec) != self.dim:
                raise ValueError(
                    f"{self.model_id} returned dim {len(vec)}, index expects {self.dim}"
                )
        return vectors
