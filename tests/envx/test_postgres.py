"""Postgres round-trip test. Skipped unless ENVX_TEST_DATABASE_URL is set."""
import os, tempfile
from pathlib import Path
import pytest

DSN = os.environ.get("ENVX_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="ENVX_TEST_DATABASE_URL not set")

REPO = Path(__file__).resolve().parents[2]
DOC = b"""RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT

Seller: Jane Roe. Buyer: John Doe.
Property: 123 Elm St, Hartford, CT 06103.

Known hazards: asbestos in the pipe insulation in the basement boiler room.
"""


def _config(tmp):
    from envx.config import EnvxConfig
    return EnvxConfig(
        wet_root=tmp / "wet",
        schemas_root=REPO / "schemas",
        lexicon_path=REPO / "lexicon" / "hazards.yml",
        attestation_key_path=tmp / "k.key",
        glm_ocr_stub=True,
        database_url=DSN,
    )


@pytest.fixture()
def clean_db():
    import psycopg
    with psycopg.connect(DSN) as conn:
        conn.execute("TRUNCATE documents CASCADE")
        conn.commit()
    yield


def test_index_survives_process_restart(clean_db):
    from envx.app import EnvxApp
    from envx.dsl.plan import RetrievalPath, RetrievalPlan, Scope

    tmp = Path(tempfile.mkdtemp())
    writer = EnvxApp(config=_config(tmp))
    result = writer.ingest(
        content=DOC, filename="seller_disclosure_2024.pdf",
        client_id="ACME", matter_id="M1",
    )
    assert result.markers

    # A fresh app instance stands in for a separate process.
    reader = EnvxApp(config=_config(Path(tempfile.mkdtemp())))
    assert len(reader.bm25) > 0, "index was not rehydrated from Postgres"

    plan = RetrievalPlan(
        scope=Scope(client_id="ACME"),
        paths=(
            RetrievalPath(kind="bm25", query="asbestos"),
            RetrievalPath(kind="dense", query="asbestos"),
        ),
    )
    evidence = reader.query(plan).evidence
    assert evidence
    assert "RISK:ASBESTOS" in evidence[0].markers


def test_grounding_status_is_tri_state(clean_db):
    import psycopg
    from envx.app import EnvxApp

    tmp = Path(tempfile.mkdtemp())
    EnvxApp(config=_config(tmp)).ingest(
        content=DOC, filename="seller_disclosure_2024.pdf", client_id="ACME",
    )
    with psycopg.connect(DSN) as conn:
        rows = dict(
            conn.execute(
                "SELECT grounding_status, count(*) FROM extracted_fields GROUP BY 1"
            ).fetchall()
        )
    # doc_type/jurisdiction are schema vocabulary and must not be reported as
    # verification failures.
    assert rows.get("not_applicable", 0) > 0
    assert rows.get("verified", 0) > 0
    with psycopg.connect(DSN) as conn:
        status = conn.execute(
            "SELECT grounding_status FROM extracted_fields WHERE field_path = '$.doc_type'"
        ).fetchone()
    assert status[0] == "not_applicable"


def test_reingest_is_idempotent(clean_db):
    import psycopg
    from envx.app import EnvxApp

    cfg = _config(Path(tempfile.mkdtemp()))
    app = EnvxApp(config=cfg)
    app.ingest(content=DOC, filename="a.pdf", client_id="ACME")
    app.ingest(content=DOC, filename="a.pdf", client_id="ACME")
    with psycopg.connect(DSN) as conn:
        count = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    assert count == 1, "content-addressed ingest must not duplicate"


def test_graph_and_entities_survive_restart(clean_db):
    from envx.app import EnvxApp

    disclosure = DOC
    esa = b"""PHASE I ENVIRONMENTAL SITE ASSESSMENT

Prepared under ASTM E1527.
Property: 123 Elm St, Hartford, CT.

A recognized environmental condition was identified.
"""
    writer = EnvxApp(config=_config(Path(tempfile.mkdtemp())))
    writer.ingest(content=disclosure, filename="seller_disclosure_2024.pdf", client_id="ACME")
    writer.ingest(content=esa, filename="PhaseI_ESA_final.pdf", client_id="ACME")
    nodes, edges = len(writer.graph), len(writer.graph.edges)
    ids_before = sorted(e.canonical_id for e in writer.resolver.all())
    assert nodes and edges

    reader = EnvxApp(config=_config(Path(tempfile.mkdtemp())))
    assert len(reader.graph) == nodes
    assert len(reader.graph.edges) == edges
    # Canonical ids must be stable, or a restart forks one identity into two
    # and cross-document synthesis silently breaks.
    assert sorted(e.canonical_id for e in reader.resolver.all()) == ids_before

    # The shared property links both documents after restore.
    reachable = reader.graph.documents_reachable(start_entity_names=["123 Elm"])
    assert len({doc_id for doc_id, _ in reachable}) == 2


def test_review_queue_survives_restart(clean_db):
    from envx.app import EnvxApp

    hallucinated = DOC.replace(b"Seller: Jane Roe.", b"Seller: Someone Else Entirely.")
    writer = EnvxApp(config=_config(Path(tempfile.mkdtemp())))
    result = writer.ingest(
        content=hallucinated, filename="seller_disclosure_2024.pdf", client_id="ACME"
    )
    assert result.needs_review

    reader = EnvxApp(config=_config(Path(tempfile.mkdtemp())))
    pending = reader.review.pending()
    assert len(pending) == 1
    assert pending[0].doc_id == result.doc_id
    assert pending[0].state is result.review_state


def test_document_id_is_content_addressed(clean_db):
    import psycopg
    from envx.app import EnvxApp
    from envx.wet_storage import doc_id_for, sha256_bytes

    app = EnvxApp(config=_config(Path(tempfile.mkdtemp())))
    result = app.ingest(content=DOC, filename="a.pdf", client_id="ACME")
    # The application id and the database primary key must be the same value;
    # two identity schemes for one document is a foreign key waiting to break.
    assert result.doc_id == doc_id_for(sha256_bytes(DOC))
    with psycopg.connect(DSN) as conn:
        row = conn.execute("SELECT doc_id FROM documents").fetchone()
    assert str(row[0]) == result.doc_id
