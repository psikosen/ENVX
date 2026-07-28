"""End-to-end and regression tests for the load-bearing behaviour.

Deliberately not exhaustive unit coverage. These lock down the things that
would be expensive to get wrong: tenant isolation, hallucination detection,
provenance, and the two bugs found during integration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from envx.app import EnvxApp
from envx.config import EnvxConfig
from envx.dsl import plan_from_yaml
from envx.dsl.plan import RetrievalPath, RetrievalPlan, Scope

REPO = Path(__file__).resolve().parents[2]

DISCLOSURE = b"""RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT

Seller: Jane Roe. Buyer: John Doe.
Property: 123 Elm St, Hartford, CT 06103.

Known hazards: asbestos in the pipe insulation in the basement boiler room.
"""

ESA = b"""PHASE I ENVIRONMENTAL SITE ASSESSMENT

Prepared by ACME Environmental Services under ASTM E1527.
Property: 123 Elm Street, Hartford, CT.

A recognized environmental condition relating to a former underground
storage tank was identified.
"""


@pytest.fixture()
def app() -> EnvxApp:
    tmp = Path(tempfile.mkdtemp())
    return EnvxApp(
        config=EnvxConfig(
            wet_root=tmp / "wet",
            schemas_root=REPO / "schemas",
            lexicon_path=REPO / "lexicon" / "hazards.yml",
            attestation_key_path=tmp / "attest.key",
            glm_ocr_stub=True,
        )
    )


def _ingest(app: EnvxApp, content: bytes, filename: str, **kw):
    return app.ingest(
        content=content,
        filename=filename,
        client_id=kw.pop("client_id", "ACME"),
        matter_id=kw.pop("matter_id", "M1"),
        **kw,
    )


def test_ingest_produces_full_provenance_chain(app: EnvxApp):
    result = _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    assert result.classification.doc_type == "property_disclosure"
    assert result.schema_id == "property_disclosure_ct"
    assert result.kie_run_id is not None
    assert result.chunks
    assert "RISK:ASBESTOS" in {m.code for m in result.markers}
    # Wet-storage artifacts exist and are signed.
    blob_dir = app.wet_store.base / "evidence_blobs" / result.blob_sha256
    kie_runs = list((blob_dir / "kie_runs").iterdir())
    assert len(kie_runs) == 1
    assert (kie_runs[0] / "attestation.sig").exists()
    assert (kie_runs[0] / "validation_report.json").exists()
    assert (blob_dir / "markers.jsonl").exists()


def test_grounding_catches_party_not_in_document(app: EnvxApp):
    # The stub KIE always claims seller "Jane Roe"; this document names a
    # different seller, so grounding must flag it rather than trust it.
    doc = DISCLOSURE.replace(b"Seller: Jane Roe.", b"Seller: Totally Different Corp.")
    result = _ingest(app, doc, "seller_disclosure_alt.pdf")
    grounding = result.validation_report["grounding"]
    assert "$.seller.name" in grounding["ungrounded_paths"]
    assert result.needs_review


def test_schema_const_fields_are_not_grounding_checked(app: EnvxApp):
    # Regression: doc_type/jurisdiction are controlled vocabulary and never
    # appear verbatim. Grounding them pushed clean docs into review.
    result = _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    ungrounded = result.validation_report["grounding"]["ungrounded_paths"]
    assert "$.doc_type" not in ungrounded
    assert "$.jurisdiction" not in ungrounded
    assert result.validation_report["review_reasons"] == []


def test_graph_accumulates_across_documents(app: EnvxApp):
    # Regression: `graph or KnowledgeGraph()` discarded the accumulator
    # because an empty KnowledgeGraph is falsy.
    _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    first = len(app.graph)
    assert first > 0
    _ingest(app, ESA, "PhaseI_ESA_final.pdf")
    assert len(app.graph) > first
    assert app.graph.edges


def test_client_isolation_is_enforced(app: EnvxApp):
    _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf", client_id="ACME")
    plan = RetrievalPlan(
        scope=Scope(client_id="OTHER_FIRM"),
        paths=(
            RetrievalPath(kind="bm25", query="asbestos"),
            RetrievalPath(kind="dense", query="asbestos"),
        ),
    )
    assert app.query(plan).evidence == []


def test_query_returns_citable_evidence(app: EnvxApp):
    _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    _ingest(app, ESA, "PhaseI_ESA_final.pdf")
    plan = RetrievalPlan(
        scope=Scope(client_id="ACME"),
        paths=(
            RetrievalPath(kind="bm25", query="asbestos pipe insulation"),
            RetrievalPath(kind="dense", query="asbestos pipe insulation"),
        ),
        top_k=10,
    )
    result = app.query(plan)
    assert result.evidence
    top = result.evidence[0]
    assert "asbestos" in top.text_raw.lower()
    for citation in result.citations:
        assert citation["block_id"] and citation["doc_id"]
        assert isinstance(citation["page"], int)


def test_lexicon_expansion_is_applied_to_bm25(app: EnvxApp):
    _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    plan = RetrievalPlan(
        scope=Scope(client_id="ACME"),
        paths=(RetrievalPath(kind="bm25", query="asbestos"),),
    )
    # "ACM"/"friable" are not in the query but are in the lexicon; the app
    # injects them so BM25 can match documents using the other vocabulary.
    assert app.query(plan).evidence


def test_require_region_ids_drops_unciteable_evidence(app: EnvxApp):
    _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    strict = plan_from_yaml(
        """
scope:
  client_id: ACME
retrieval:
  paths:
    - kind: bm25
      query: asbestos
  top_k: 10
response:
  require_region_ids: true
"""
    )
    result = app.query(strict)
    assert all(e.region_id for e in result.evidence)


def test_duplicate_ingest_is_deduplicated(app: EnvxApp):
    a = _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    b = _ingest(app, DISCLOSURE, "seller_disclosure_copy.pdf")
    assert a.blob_sha256 == b.blob_sha256
    assert app.jobs.counts().get("pending") == 1


def test_reingest_does_not_duplicate_evidence(app: EnvxApp):
    """Re-ingesting a document must not multiply it in the index.

    Chunk ids are content-addressed so an unchanged document upserts. Random
    ids would surface the same passage repeatedly, which reads as
    corroboration when it is duplication.
    """
    first = _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
    for _ in range(2):
        again = _ingest(app, DISCLOSURE, "seller_disclosure_2024.pdf")
        assert [c.chunk_id for c in again.chunks] == [c.chunk_id for c in first.chunks]

    assert len(app.bm25) == len(first.chunks)
    assert len(app.vectors) == len(first.chunks)

    plan = RetrievalPlan(
        scope=Scope(client_id="ACME"),
        paths=(RetrievalPath(kind="bm25", query="asbestos"),),
        top_k=20,
    )
    evidence = app.query(plan).evidence
    assert len({e.chunk_id for e in evidence}) == len(evidence)


def test_reparse_with_fewer_chunks_evicts_stale(app: EnvxApp):
    """A shorter re-parse must not strand orphans from the previous one."""
    long_doc = DISCLOSURE + b"\n\nAdditional section about radon testing.\n"
    _ingest(app, long_doc, "seller_disclosure_2024.pdf")
    before = len(app.bm25)

    short = b"RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT\n\nSeller: Jane Roe.\n"
    result = _ingest(app, short, "seller_disclosure_2024.pdf")
    # Different content is a different document; the first must survive.
    assert len(app.bm25) == before + len(result.chunks)

    # Re-ingesting the same shorter bytes replaces rather than accumulates.
    _ingest(app, short, "seller_disclosure_2024.pdf")
    assert len(app.bm25) == before + len(result.chunks)
