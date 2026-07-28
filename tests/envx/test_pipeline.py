import json
from pathlib import Path

from envx.config import EnvxConfig
from envx.pipeline import PreprocessPipeline
from envx.wet_storage import WetStore


SOURCE_TEXT = (
    "RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT\n"
    "Seller's Disclosure. 123 Elm St, Hartford, CT 06103. "
    "Seller: Jane Roe. Buyer: John Doe. "
    "Known hazards: asbestos in pipe insulation."
)


def _config(tmp_path: Path) -> EnvxConfig:
    schemas_root = Path(__file__).resolve().parents[2] / "schemas"
    return EnvxConfig(
        wet_root=tmp_path / "wet",
        schemas_root=schemas_root,
        attestation_key_path=tmp_path / "attest.key",
        glm_ocr_url="",
        glm_ocr_model="glm-ocr",
        glm_ocr_timeout_s=30,
        glm_ocr_stub=True,
        grounding_min_ratio=0.85,
    )


def test_pipeline_end_to_end_happy_path(tmp_path):
    config = _config(tmp_path)
    store = WetStore(base=config.wet_root, attestation_key_path=config.attestation_key_path)
    blob = store.ingest_bytes(b"pretend pdf", "pdf", {"client_id": "ACME"})
    pipe = PreprocessPipeline(config=config, wet_store=store)

    result = pipe.run(
        blob=blob,
        filename="seller_disclosure_2024.pdf",
        first_page_text=(
            "RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT — Seller's Disclosure"
        ),
        source_text=SOURCE_TEXT,
        page_image_paths=[tmp_path / "page1.png", tmp_path / "page2.png"],
    )

    assert result.doc_type.doc_type == "property_disclosure"
    assert result.kie_run_id is not None
    assert result.validation_report is not None
    codes = {m.code for m in result.markers}
    assert "RISK:ASBESTOS" in codes
    # KIE artifacts landed in wet storage.
    kie_dirs = list(blob.kie_runs_dir.iterdir())
    assert len(kie_dirs) == 1
    assert (kie_dirs[0] / "validation_report.json").exists()
    # Markers written to markers.jsonl.
    assert (blob.root / "markers.jsonl").exists()


def test_pipeline_unknown_doc_type_emits_needs_review(tmp_path):
    config = _config(tmp_path)
    store = WetStore(base=config.wet_root, attestation_key_path=config.attestation_key_path)
    blob = store.ingest_bytes(b"other", "pdf", {"client_id": "ACME"})
    pipe = PreprocessPipeline(config=config, wet_store=store)

    result = pipe.run(
        blob=blob,
        filename="random_scan.pdf",
        first_page_text="Lorem ipsum",
        source_text="Lorem ipsum",
        page_image_paths=[tmp_path / "p1.png"],
    )
    assert result.doc_type.doc_type == "unknown"
    assert result.needs_review is True
    assert result.kie_run_id is None
    assert result.markers == []
