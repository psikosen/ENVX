import copy

from envx.kie import KIEValidator, flatten_extracted_fields
from envx.schemas import SchemaLoader


VALID_PD = {
    "doc_type": "property_disclosure",
    "jurisdiction": "CT",
    "property": {
        "address_street": "123 Elm St",
        "address_city": "Hartford",
        "address_zip": "06103",
    },
    "seller": {"name": "Jane Roe"},
    "buyer": {"name": "John Doe"},
    "hazards_disclosed": [
        {"type": "asbestos", "severity": "known", "page_cited": 3},
    ],
}

SOURCE_TEXT = (
    "PROPERTY DISCLOSURE. 123 Elm St, Hartford, CT 06103. "
    "Seller: Jane Roe. Buyer: John Doe. "
    "Known hazards: asbestos in pipe insulation."
)


def _schema():
    return SchemaLoader().load("property_disclosure_ct", "v1")


def test_valid_payload_passes_and_grounds():
    outcome = KIEValidator().validate(VALID_PD, _schema(), SOURCE_TEXT)
    assert outcome.schema_errors == []
    assert outcome.result.needs_review is False
    assert outcome.grounding is not None
    assert outcome.grounding.ungrounded_paths == []


def test_schema_violation_flags_review():
    bad = copy.deepcopy(VALID_PD)
    bad["hazards_disclosed"][0]["severity"] = "totally-wrong"  # not in enum
    outcome = KIEValidator().validate(bad, _schema(), SOURCE_TEXT)
    assert outcome.schema_errors, "expected enum violation"
    assert outcome.result.needs_review is True
    assert "schema_validation_failed" in outcome.result.review_reasons


def test_missing_required_field_flags_review():
    bad = copy.deepcopy(VALID_PD)
    del bad["seller"]
    outcome = KIEValidator().validate(bad, _schema(), SOURCE_TEXT)
    assert outcome.result.needs_review is True
    assert outcome.schema_errors


def test_hallucinated_seller_name_caught_by_grounding():
    payload = copy.deepcopy(VALID_PD)
    payload["seller"]["name"] = "Person Not In Document"
    outcome = KIEValidator().validate(payload, _schema(), SOURCE_TEXT)
    assert outcome.grounding is not None
    assert "$.seller.name" in outcome.grounding.ungrounded_paths
    assert "grounding_failed" in outcome.result.review_reasons
    assert outcome.result.needs_review is True


def test_flatten_walks_arrays_and_propagates_page_cited():
    rows = flatten_extracted_fields(VALID_PD)
    by_path = {r.field_path: r for r in rows}
    assert by_path["$.hazards_disclosed[0].type"].value == "asbestos"
    assert by_path["$.hazards_disclosed[0].type"].page_cited == 3
    assert by_path["$.seller.name"].value == "Jane Roe"


def test_validation_report_is_json_serializable():
    import json

    outcome = KIEValidator().validate(VALID_PD, _schema(), SOURCE_TEXT)
    json.dumps(outcome.as_report())
