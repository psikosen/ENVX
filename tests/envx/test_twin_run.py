"""Twin-run agreement checking (§2.5.4)."""

import tempfile
from pathlib import Path

from envx.app import EnvxApp
from envx.config import EnvxConfig
from envx.kie import CRITICAL_PREFIXES, compare_runs

REPO = Path(__file__).resolve().parents[2]

BASE = {
    "doc_type": "property_disclosure",
    "seller": {"name": "ACME Housing LLC"},
    "hazards_disclosed": [
        {"type": "asbestos", "severity": "known", "page_cited": 3},
        {"type": "lead", "severity": "suspected", "page_cited": 4},
    ],
}


def test_identical_runs_fully_agree():
    report = compare_runs(BASE, BASE)
    assert report.agreement_rate == 1.0
    assert not report.has_disagreement


def test_array_reordering_is_not_disagreement():
    # Extraction order of a hazards array carries no meaning.
    reordered = {**BASE, "hazards_disclosed": list(reversed(BASE["hazards_disclosed"]))}
    assert not compare_runs(BASE, reordered).has_disagreement


def test_cosmetic_string_variance_is_not_disagreement():
    cosmetic = {**BASE, "seller": {"name": "ACME  Housing, LLC"}}
    assert not compare_runs(BASE, cosmetic).has_disagreement


def test_numeric_tolerance():
    a = {"sampling_results": [{"analyte": "lead", "concentration": 100.0}]}
    b = {"sampling_results": [{"analyte": "lead", "concentration": 100.5}]}
    assert not compare_runs(a, b).has_disagreement
    c = {"sampling_results": [{"analyte": "lead", "concentration": 400.0}]}
    assert compare_runs(a, c).has_disagreement


def test_flipped_hazard_severity_is_critical():
    flipped = {
        **BASE,
        "hazards_disclosed": [
            {"type": "asbestos", "severity": "suspected", "page_cited": 3},
            {"type": "lead", "severity": "suspected", "page_cited": 4},
        ],
    }
    report = compare_runs(BASE, flipped)
    critical = report.high_severity_paths(critical_prefixes=CRITICAL_PREFIXES)
    assert "$.hazards_disclosed[0].severity" in critical


def test_dropped_hazard_is_reported_with_direction():
    dropped = {**BASE, "hazards_disclosed": [BASE["hazards_disclosed"][1]]}
    report = compare_runs(BASE, dropped)
    assert report.has_disagreement
    assert any(d.kind == "only_in_a" for d in report.disagreements)


def test_noncritical_wobble_is_not_escalated():
    a = {**BASE, "property": {"year_built": "1960"}}
    b = {**BASE, "property": {"year_built": "1961"}}
    report = compare_runs(a, b)
    assert report.has_disagreement
    # Noise on year_built must not route a document to human review.
    assert report.high_severity_paths(critical_prefixes=CRITICAL_PREFIXES) == []


def test_app_escalates_twin_run_disagreement():
    """A KIE client whose second call differs must trigger review."""

    class FlakyKIE:
        """Wraps the stub, perturbing a hazard severity on the second call."""

        def __init__(self, inner):
            self.inner = inner
            self.calls = 0

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def extract_kie(self, **kwargs):
            self.calls += 1
            response = self.inner.extract_kie(**kwargs)
            if self.calls >= 2 and response.parsed:
                payload = dict(response.parsed)
                hazards = [dict(h) for h in payload.get("hazards_disclosed", [])]
                if hazards:
                    hazards[0]["severity"] = "unknown"
                    payload["hazards_disclosed"] = hazards
                return type(response)(
                    raw_text=response.raw_text, parsed=payload, parse_error=None
                )
            return response

    from envx.glm_ocr import GLMOCRClient

    tmp = Path(tempfile.mkdtemp())
    config = EnvxConfig(
        wet_root=tmp / "wet",
        schemas_root=REPO / "schemas",
        lexicon_path=REPO / "lexicon" / "hazards.yml",
        attestation_key_path=tmp / "k.key",
        glm_ocr_stub=True,
        twin_run_high_stakes=True,
    )
    app = EnvxApp(config=config, glm=FlakyKIE(GLMOCRClient(config=config)))
    result = app.ingest(
        content=(
            b"RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT\n\n"
            b"Seller: Jane Roe. Buyer: John Doe.\n"
            b"Property: 123 Elm St, Hartford, CT 06103.\n\n"
            b"Known hazards: asbestos in the pipe insulation.\n"
        ),
        filename="seller_disclosure_2024.pdf",
        client_id="ACME",
        matter_id="M1",
        matter_is_active=True,
    )
    twin = result.validation_report.get("twin_run")
    assert twin is not None, "twin run should execute on an active matter"
    assert twin["critical_disagreements"], "severity flip must be flagged critical"
    assert result.needs_review


def test_twin_run_skipped_when_matter_inactive():
    tmp = Path(tempfile.mkdtemp())
    config = EnvxConfig(
        wet_root=tmp / "wet",
        schemas_root=REPO / "schemas",
        lexicon_path=REPO / "lexicon" / "hazards.yml",
        attestation_key_path=tmp / "k.key",
        glm_ocr_stub=True,
        twin_run_high_stakes=True,
    )
    result = EnvxApp(config=config).ingest(
        content=b"RESIDENTIAL PROPERTY CONDITION DISCLOSURE REPORT\n\nSeller: Jane Roe.\n",
        filename="seller_disclosure_2024.pdf",
        client_id="ACME",
        matter_is_active=False,
    )
    # Doubling KIE cost is only justified on active matters.
    assert "twin_run" not in result.validation_report
