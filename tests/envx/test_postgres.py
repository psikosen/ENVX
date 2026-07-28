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
