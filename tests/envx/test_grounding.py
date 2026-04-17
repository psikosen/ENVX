from envx.kie.grounding import ground_fields, normalize_for_match
from envx.models import ExtractedField


SOURCE = (
    "PROPERTY DISCLOSURE\n"
    "Property: 123 Elm Street, Hartford, CT 06103.\n"
    "Seller: Jane Roe. Buyer: John Doe.\n"
    "Known hazards: asbestos in pipe insulation (known).\n"
)


def test_normalize_collapses_whitespace_and_casefolds():
    assert normalize_for_match("  Hello   WORLD!\n") == "hello world"


def test_exact_string_is_grounded():
    fields = [
        ExtractedField(field_path="$.seller.name", value="Jane Roe", page_cited=1),
    ]
    out, report = ground_fields(fields, SOURCE)
    assert out[0].grounding_verified is True
    assert out[0].verification_score == 1.0
    assert report.grounded == 1
    assert report.ungrounded_paths == []


def test_fuzzy_case_whitespace_tolerated():
    fields = [
        ExtractedField(
            field_path="$.property.address_street",
            value="123 ELM ST",
            page_cited=1,
        ),
    ]
    out, report = ground_fields(fields, SOURCE)
    assert out[0].grounding_verified is True
    assert report.grounded == 1


def test_hallucinated_value_flagged_ungrounded():
    fields = [
        ExtractedField(
            field_path="$.seller.name",
            value="Totally Made Up Person",
            page_cited=1,
        ),
    ]
    out, report = ground_fields(fields, SOURCE)
    assert out[0].grounding_verified is False
    assert "$.seller.name" in report.ungrounded_paths


def test_page_cited_skipped():
    fields = [
        ExtractedField(
            field_path="$.hazards_disclosed[0].page_cited",
            value=42,
            page_cited=42,
        ),
    ]
    out, report = ground_fields(fields, SOURCE)
    assert report.total_checked == 0
    assert out[0].grounding_verified is False  # default unchanged; not flagged


def test_short_and_non_string_values_skipped():
    fields = [
        ExtractedField(field_path="$.seller.signature_present", value=True, page_cited=1),
        ExtractedField(field_path="$.property.year_built", value="", page_cited=1),
    ]
    _, report = ground_fields(fields, SOURCE)
    assert report.total_checked == 0
