"""HTTP-backed inference paths, exercised against a real local endpoint.

These cover the code that talks to embedding and rerank servers. Before the
dev server existed those paths were written but never executed, which is a
poor place to discover a wrong request shape.
"""

import tempfile
from pathlib import Path

import pytest

from envx.app import EnvxApp
from envx.config import EnvxConfig
from envx.devserver import dev_embedding_server
from envx.dsl.plan import RerankSpec, RetrievalPath, RetrievalPlan, Scope
from envx.embedding import HTTPEmbedding, cosine_similarity
from envx.retrieval import HTTPReranker, IndexedChunk, ScoredChunk

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def endpoint():
    with dev_embedding_server(dim=512) as url:
        yield url


def test_http_embedding_round_trip(endpoint):
    embedder = HTTPEmbedding(base_url=endpoint, model="envx-dev-embedding", dim=512)
    vectors = embedder.embed(["asbestos pipe insulation", "roof satisfactory"])
    assert len(vectors) == 2
    assert all(len(v) == 512 for v in vectors)
    # Deterministic backend: the same text must embed identically, or the
    # index and the query would disagree.
    assert embedder.embed(["asbestos pipe insulation"])[0] == vectors[0]


def test_http_embedding_rejects_dim_mismatch(endpoint):
    # A silent dim mismatch would poison the index rather than fail loudly.
    embedder = HTTPEmbedding(base_url=endpoint, model="m", dim=1024)
    with pytest.raises(ValueError, match="dim"):
        embedder.embed(["x"])


def test_http_embedding_preserves_input_order(endpoint):
    embedder = HTTPEmbedding(base_url=endpoint, model="envx-dev-embedding", dim=512)
    texts = [f"document number {i} about asbestos" for i in range(8)]
    batch = embedder.embed(texts)
    for text, vector in zip(texts, batch):
        assert cosine_similarity(embedder.embed([text])[0], vector) > 0.999


def test_http_reranker_reorders_by_relevance(endpoint):
    def candidate(chunk_id: str, text: str) -> ScoredChunk:
        return ScoredChunk(
            chunk=IndexedChunk(
                chunk_id=chunk_id,
                doc_id="d",
                text_raw=text,
                text_contextual=text,
                client_id="ACME",
                page_number=1,
            ),
            score=0.5,
        )

    reranker = HTTPReranker(base_url=endpoint, model="envx-dev-rerank")
    ranked = reranker.rerank(
        query="asbestos insulation",
        candidates=[
            candidate("c1", "The roof was found satisfactory."),
            candidate("c2", "Asbestos was found in the pipe insulation."),
        ],
        top_k=2,
    )
    assert ranked[0].chunk.chunk_id == "c2"
    assert ranked[0].rerank_score > ranked[1].rerank_score


def test_app_runs_on_live_http_backends(endpoint):
    tmp = Path(tempfile.mkdtemp())
    config = EnvxConfig(
        wet_root=tmp / "wet",
        schemas_root=REPO / "schemas",
        lexicon_path=REPO / "lexicon" / "hazards.yml",
        attestation_key_path=tmp / "k.key",
        glm_ocr_stub=True,
        embedding_url=endpoint,
        embedding_model="envx-dev-embedding",
        embedding_dim=512,
        rerank_url=endpoint,
        rerank_model="envx-dev-rerank",
    )
    assert not config.offline

    app = EnvxApp(config=config)
    assert app.embedder.model_id == "envx-dev-embedding"
    app.ingest(
        content=(
            b"RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT\n\n"
            b"Seller: Jane Roe.\nProperty: 123 Elm St, Hartford, CT 06103.\n\n"
            b"Known hazards: asbestos in the pipe insulation.\n"
        ),
        filename="seller_disclosure_2024.pdf",
        client_id="ACME",
    )
    app.ingest(
        content=b"HOME INSPECTION REPORT\n\nRoof satisfactory, no defects noted.\n",
        filename="home_inspection.pdf",
        client_id="ACME",
    )
    result = app.query(
        RetrievalPlan(
            scope=Scope(client_id="ACME"),
            paths=(
                RetrievalPath(kind="bm25", query="asbestos insulation"),
                RetrievalPath(kind="dense", query="asbestos insulation"),
            ),
            rerank=RerankSpec(model="envx-dev-rerank", top_k=2),
            top_k=10,
        )
    )
    assert result.reranked
    assert result.evidence
    assert "asbestos" in result.evidence[0].text_raw.lower()


def test_devserver_rejects_malformed_requests(endpoint):
    import httpx

    with httpx.Client(timeout=10) as client:
        assert client.post(f"{endpoint}/v1/embeddings", json={}).status_code == 400
        assert client.post(f"{endpoint}/rerank", json={"query": "x"}).status_code == 400
        # An explicitly empty document list is valid, just empty.
        empty = client.post(f"{endpoint}/rerank", json={"query": "x", "documents": []})
        assert empty.status_code == 200 and empty.json()["results"] == []
        assert client.get(f"{endpoint}/health").json()["status"] == "ok"


def test_reranker_parses_every_server_envelope():
    """Real servers disagree on the response shape; all must work.

    TEI returns a bare list, Cohere/Voyage wrap in 'results', some wrap in
    'data'. Getting this wrong silently zeroes every score and the reranker
    becomes a no-op that still reports success.
    """
    from envx.retrieval.rerank import _parse_rerank_scores

    expected = [0.1, 0.9]
    assert _parse_rerank_scores(
        [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}], 2
    ) == expected
    assert _parse_rerank_scores(
        {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]},
        2,
    ) == expected
    assert _parse_rerank_scores(
        {"data": [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.1}]}, 2
    ) == expected
    # Out-of-range indices must not raise or corrupt neighbours.
    assert _parse_rerank_scores([{"index": 99, "score": 1.0}], 2) == [0.0, 0.0]
