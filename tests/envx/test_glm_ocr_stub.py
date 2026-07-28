from pathlib import Path

from envx.glm_ocr import GLMOCRClient


def test_stub_extract_kie_returns_parsed_json():
    client = GLMOCRClient()
    assert client.is_stub
    resp = client.extract_kie(
        image_paths=[Path("/nonexistent.png")],
        json_schema={"type": "object"},
        doc_type="property_disclosure",
    )
    assert resp.parse_error is None
    assert resp.parsed is not None
    assert resp.parsed["doc_type"] == "property_disclosure"
    assert resp.parsed["hazards_disclosed"][0]["type"] == "asbestos"


def test_stub_parse_text_returns_markdown():
    client = GLMOCRClient()
    resp = client.parse_text(Path("/tmp/x.png"))
    assert "stub parse" in resp.markdown


def test_stub_layout_returns_one_region(tmp_path):
    client = GLMOCRClient()
    resp = client.layout_regions(tmp_path / "x.png", page_number=3)
    assert len(resp.regions) == 1
    assert resp.regions[0].page_number == 3
