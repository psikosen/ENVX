"""Local embedding backends that need no model download.

``LSAEmbedding`` fits TF-IDF followed by truncated SVD over the corpus —
classical Latent Semantic Analysis. It is genuinely distributional: terms
that co-occur across documents end up with correlated dimensions, so it
picks up some synonymy that pure token matching misses. It is not a neural
sentence encoder and will not match one, but it is a real semantic method
and a far more honest offline default than token hashing.

Two properties matter for using it correctly:

  - **It must be fitted before use.** The vector space is derived from the
    corpus, so queries must be embedded by the same fitted model that
    embedded the documents. Calling ``embed`` before ``fit`` raises rather
    than silently returning zeros.
  - **Refitting changes the space.** Adding documents and refitting
    invalidates every stored vector, exactly like changing embedding model
    versions. The ``model_id`` carries a fingerprint of the fitted corpus so
    a mismatched index is detectable.

For production, point ``HTTPEmbedding`` at a served neural model. This is
for offline development, CI, and evaluating the retrieval architecture
without a GPU.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from .backends import Vector, normalize


class NotFittedError(RuntimeError):
    pass


class LSAEmbedding:
    """TF-IDF + truncated SVD. Requires scikit-learn."""

    def __init__(self, dim: int = 256, *, min_df: int = 1) -> None:
        try:
            from sklearn.decomposition import TruncatedSVD  # noqa: F401
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "LSAEmbedding requires scikit-learn: pip install scikit-learn"
            ) from exc
        self.dim = dim
        self.min_df = min_df
        self.model_id = f"envx-lsa-{dim}/unfitted"
        self._vectorizer = None
        self._svd = None

    @property
    def fitted(self) -> bool:
        return self._svd is not None

    def fit(self, corpus: Sequence[str]) -> "LSAEmbedding":
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        if not corpus:
            raise ValueError("cannot fit on an empty corpus")

        self._vectorizer = TfidfVectorizer(
            lowercase=True,
            sublinear_tf=True,
            min_df=self.min_df,
            # Word bigrams catch multi-word legal terms — "pipe lagging",
            # "reservation of rights" — that unigrams shatter.
            ngram_range=(1, 2),
            strip_accents="unicode",
        )
        matrix = self._vectorizer.fit_transform(corpus)

        # SVD cannot produce more components than the smaller matrix
        # dimension, and needs at least one.
        components = max(1, min(self.dim, min(matrix.shape) - 1))
        self._svd = TruncatedSVD(n_components=components, random_state=0)
        self._svd.fit(matrix)
        self.dim = components

        # Delimit with a record separator so two different corpora cannot
        # concatenate into the same fingerprint.
        fingerprint = hashlib.blake2s(
            "\x1e".join(corpus).encode(), digest_size=6
        ).hexdigest()
        self.model_id = f"envx-lsa-{components}/{fingerprint}"
        return self

    def embed(self, texts: Sequence[str]) -> list[Vector]:
        if not self.fitted:
            raise NotFittedError(
                "LSAEmbedding must be fitted on the corpus before embedding; "
                "an unfitted model has no vector space to project into"
            )
        if not texts:
            return []
        matrix = self._vectorizer.transform(texts)  # type: ignore[union-attr]
        reduced = self._svd.transform(matrix)  # type: ignore[union-attr]
        return [normalize([float(x) for x in row]) for row in reduced]
