"""Local OpenAI-compatible embeddings and rerank server.

Serves the deterministic hashing embedding over HTTP so the pieces that
speak to real inference endpoints — ``HTTPEmbedding``, ``HTTPReranker``, and
LEANN's ``openai`` embedding mode — can be exercised without a GPU, an API
key, or a model download.

This is not a model. It is a stand-in that makes the *integration* real: the
same request shapes, the same response envelopes, the same failure modes. It
exists so those code paths are tested rather than assumed.

Run it standalone::

    python -m envx.devserver --port 8099

Or embed it in a test::

    with dev_embedding_server() as url:
        ...

Endpoints:
    POST /v1/embeddings   OpenAI-compatible
    POST /rerank          TEI / Cohere-compatible
    GET  /health
"""

from __future__ import annotations

import argparse
import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

from .embedding import HashingEmbedding, cosine_similarity


DEFAULT_DIM = 512


class _Handler(BaseHTTPRequestHandler):
    embedder: HashingEmbedding = HashingEmbedding(DEFAULT_DIM)

    # Silence per-request logging; it drowns test output.
    def log_message(self, *args: object) -> None:  # noqa: A003
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/health", ""):
            self._send(200, {"status": "ok", "dim": self.embedder.dim})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        body = self._read_json()
        if path in ("/v1/embeddings", "/embeddings"):
            self._embeddings(body)
        elif path in ("/rerank", "/v1/rerank"):
            self._rerank(body)
        else:
            self._send(404, {"error": f"unknown path {path}"})

    def _embeddings(self, body: dict) -> None:
        raw = body.get("input")
        if raw is None:
            self._send(400, {"error": "missing 'input'"})
            return
        texts = [raw] if isinstance(raw, str) else list(raw)
        if not all(isinstance(t, str) for t in texts):
            self._send(400, {"error": "'input' must be a string or list of strings"})
            return
        vectors = self.embedder.embed(texts)
        self._send(
            200,
            {
                "object": "list",
                "model": body.get("model", "envx-dev-embedding"),
                "data": [
                    {"object": "embedding", "index": i, "embedding": vec}
                    for i, vec in enumerate(vectors)
                ],
                "usage": {
                    "prompt_tokens": sum(len(t.split()) for t in texts),
                    "total_tokens": sum(len(t.split()) for t in texts),
                },
            },
        )

    def _rerank(self, body: dict) -> None:
        query = body.get("query")
        # A missing 'documents' key is malformed; an explicitly empty list is
        # a valid request that simply ranks nothing.
        if "documents" not in body or not isinstance(query, str) or not query:
            self._send(400, {"error": "'query' and 'documents' are required"})
            return
        documents = body["documents"]
        if not isinstance(documents, list):
            self._send(400, {"error": "'documents' must be a list"})
            return
        if not documents:
            self._send(200, {"results": [], "model": body.get("model", "envx-dev-rerank")})
            return
        vectors = self.embedder.embed([query, *[str(d) for d in documents]])
        query_vec = vectors[0]
        scored = [
            {"index": i, "relevance_score": cosine_similarity(query_vec, vec)}
            for i, vec in enumerate(vectors[1:])
        ]
        scored.sort(key=lambda r: r["relevance_score"], reverse=True)
        top_n = body.get("top_n")
        if isinstance(top_n, int) and top_n > 0:
            scored = scored[:top_n]
        self._send(200, {"results": scored, "model": body.get("model", "envx-dev-rerank")})


def serve(host: str = "127.0.0.1", port: int = 8099, dim: int = DEFAULT_DIM) -> None:
    _Handler.embedder = HashingEmbedding(dim)
    server = ThreadingHTTPServer((host, port), _Handler)
    print(f"envx dev inference server on http://{host}:{port} (dim={dim})")
    server.serve_forever()


@contextlib.contextmanager
def dev_embedding_server(dim: int = DEFAULT_DIM) -> Iterator[str]:
    """Run the server on an ephemeral port for the duration of the block."""
    _Handler.embedder = HashingEmbedding(dim)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="envx.devserver", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, dim=args.dim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
