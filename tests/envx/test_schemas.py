import pytest
from jsonschema import Draft202012Validator

from envx.schemas import SchemaLoader, SchemaNotFound, load_default_library


EXPECTED = {
    "property_disclosure_ct",
    "environmental_report",
    "inspection_report",
    "insurance_claim",
    "medical_record",
}


def test_all_starter_schemas_load():
    loader = SchemaLoader()
    ids = set(loader.list_ids())
    assert EXPECTED.issubset(ids), f"missing: {EXPECTED - ids}"


def test_library_loads_and_hashes_are_stable():
    lib = load_default_library()
    assert len(lib) == len(EXPECTED)
    lib2 = load_default_library()
    for key, schema in lib.items():
        assert schema.content_hash == lib2[key].content_hash
        assert len(schema.content_hash) == 64


def test_json_schemas_validate_as_draft_2020_12():
    for schema in load_default_library().values():
        Draft202012Validator.check_schema(schema.json_schema)


def test_schema_not_found_raises():
    loader = SchemaLoader()
    with pytest.raises(SchemaNotFound):
        loader.load("does_not_exist", "v1")


def test_latest_version_picks_highest():
    loader = SchemaLoader()
    # All starter schemas ship v1 only; load_latest must return it.
    for sid in EXPECTED:
        assert loader.load_latest(sid).version == "v1"


def test_marker_rules_present_per_schema():
    lib = load_default_library()
    for key, schema in lib.items():
        assert isinstance(schema.marker_rules, list)
        assert schema.marker_rules, f"{key} has no marker_rules"
        for rule in schema.marker_rules:
            assert "code_template" in rule
            assert "when" in rule
            assert "field_path" in rule["when"]
