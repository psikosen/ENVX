"""Structured filter (Path 5) parsing and compilation.

Execution against a live database is covered in test_postgres.py.
"""

import pytest

from envx.dsl.structured import FilterSyntaxError, compile_filter, parse_expression


def test_parses_scalar_types():
    preds, _ = parse_expression("$.conclusions.requires_phase_ii = true")
    assert preds[0].value is True
    preds, _ = parse_expression("$.sampling_results[*].concentration > 50")
    assert preds[0].value == 50
    assert preds[0].op == ">"
    preds, _ = parse_expression("$.report_type = 'phase_i'")
    assert preds[0].value == "phase_i"


def test_parses_in_and_exists_and_like():
    preds, _ = parse_expression("$.hazards_disclosed[*].type IN ('asbestos', 'acm')")
    assert preds[0].op == "IN"
    assert preds[0].value == ["asbestos", "acm"]
    preds, _ = parse_expression("$.recs[*] EXISTS")
    assert preds[0].op == "EXISTS"
    preds, _ = parse_expression("$.seller.name LIKE '%Housing%'")
    assert preds[0].op == "LIKE"


def test_wildcard_paths_are_detected():
    preds, _ = parse_expression("$.hazards_disclosed[*].type = 'asbestos'")
    assert preds[0].is_wildcard
    preds, _ = parse_expression("$.seller.name = 'Jane Roe'")
    assert not preds[0].is_wildcard


def test_mixing_and_or_is_rejected():
    # Grouping changes the meaning, and guessing wrong on a hazard query is
    # not an acceptable failure mode.
    with pytest.raises(FilterSyntaxError):
        parse_expression("$.a = 1 AND $.b = 2 OR $.c = 3")


def test_unparseable_expression_is_rejected():
    with pytest.raises(FilterSyntaxError):
        parse_expression("delete from documents")
    with pytest.raises(FilterSyntaxError):
        compile_filter(where="")


def test_values_are_parameterised_not_interpolated():
    # An LLM authors these plans; a value must reach the database as a
    # parameter, never as SQL text.
    compiled = compile_filter(where="$.seller.name = 'Roe; DROP TABLE x'", client_id="ACME")
    assert "DROP TABLE" not in compiled.sql
    assert compiled.sql.count("%s") == len(compiled.params)
    assert any("drop table" in str(p).lower() for p in compiled.params)


def test_trailing_content_is_rejected_not_ignored():
    # Applying only the parseable prefix would silently narrow the filter to
    # something other than what was written.
    with pytest.raises(FilterSyntaxError):
        parse_expression("$.seller.name = 'x' ; DROP TABLE documents; --")
    with pytest.raises(FilterSyntaxError):
        parse_expression("$.a = 1 unexpected trailing words")


def test_and_compiles_to_intersection_with_distinct_aliases():
    compiled = compile_filter(
        where="$.hazards_disclosed[*].type = 'asbestos'"
        " AND $.hazards_disclosed[*].severity = 'known'"
    )
    # Each predicate must match some row for the same document, not one row
    # satisfying both at once.
    assert "INTERSECT" in compiled.sql
    assert "efi0." in compiled.sql and "efi1." in compiled.sql


def test_scope_is_applied():
    compiled = compile_filter(
        where="$.recs[*] EXISTS",
        client_id="ACME",
        matter_id="M1",
        doc_types=["environmental_report"],
    )
    assert "d.client_id = %s" in compiled.sql
    assert "d.matter_id = %s" in compiled.sql
    assert "ACME" in compiled.params and "M1" in compiled.params
