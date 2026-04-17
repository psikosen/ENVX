from envx.markers import MarkerEngine, iter_jsonpath
from envx.schemas import SchemaLoader


def test_wildcard_walks_array():
    payload = {"a": [{"b": 1}, {"b": 2}, {"b": 3}]}
    vals = [v for _, v, _ in iter_jsonpath(payload, "$.a[*].b")]
    assert vals == [1, 2, 3]


def test_index_picks_single_item():
    payload = {"a": [{"b": 1}, {"b": 2}]}
    vals = [v for _, v, _ in iter_jsonpath(payload, "$.a[1].b")]
    assert vals == [2]


def test_property_disclosure_asbestos_rule_fires():
    rules = SchemaLoader().load("property_disclosure_ct", "v1").marker_rules
    payload = {
        "hazards_disclosed": [
            {"type": "asbestos", "severity": "known", "page_cited": 3},
            {"type": "lead", "severity": "suspected", "page_cited": 4},
        ]
    }
    markers = MarkerEngine(rules).evaluate(payload)
    codes = {m.code for m in markers}
    assert "RISK:ASBESTOS" in codes
    assert "RISK:LEAD" in codes
    asbestos = next(m for m in markers if m.code == "RISK:ASBESTOS")
    # severity=known → confidence 0.95 from the confidence_map
    assert asbestos.confidence == 0.95
    lead = next(m for m in markers if m.code == "RISK:LEAD")
    assert lead.confidence == 0.8


def test_severity_unknown_maps_to_low_confidence():
    rules = SchemaLoader().load("property_disclosure_ct", "v1").marker_rules
    payload = {
        "hazards_disclosed": [
            {"type": "radon", "severity": "unknown", "page_cited": 1},
        ]
    }
    markers = MarkerEngine(rules).evaluate(payload)
    radon = next(m for m in markers if m.code == "RISK:RADON")
    assert radon.confidence == 0.4


def test_environmental_rec_rule_fires_on_exists():
    rules = SchemaLoader().load("environmental_report", "v1").marker_rules
    payload = {
        "recs": [
            {"rec_type": "historical", "condition": "UST", "page_cited": 5},
        ],
        "sampling_results": [
            {"medium": "soil", "analyte": "lead", "exceeds_standard": True, "page_cited": 7},
        ],
        "conclusions": {"has_recs": True, "requires_phase_ii": True},
    }
    markers = MarkerEngine(rules).evaluate(payload)
    codes = {m.code for m in markers}
    assert "FINDING:REC" in codes
    assert "RISK:EXCEEDANCE" in codes
    assert "PROCESS:PHASE_II_REQUIRED" in codes
    assert "RISK:LEAD" in codes


def test_medical_icd10_prefix_rule():
    rules = SchemaLoader().load("medical_record", "v1").marker_rules
    payload = {
        "diagnoses_icd10": [
            {"code": "C45.0", "description": "Mesothelioma of pleura", "page_cited": 2},
            {"code": "J61", "description": "Asbestosis", "page_cited": 3},
        ]
    }
    markers = MarkerEngine(rules).evaluate(payload)
    codes = {m.code for m in markers}
    assert "DIAGNOSIS:MESOTHELIOMA" in codes
    assert "DIAGNOSIS:ASBESTOSIS" in codes


def test_insurance_ror_and_denial_rules():
    rules = SchemaLoader().load("insurance_claim", "v1").marker_rules
    payload = {
        "reservation_of_rights": {"asserted": True, "grounds": ["late notice"]},
        "denial": {"issued": False, "grounds": []},
        "coverage_analysis": {"exclusions_cited": ["mold"]},
    }
    markers = MarkerEngine(rules).evaluate(payload)
    codes = {m.code for m in markers}
    assert "CLAUSE:RESERVATION_OF_RIGHTS" in codes
    assert "CLAUSE:DENIAL" not in codes
    assert "CLAUSE:EXCLUSION_CITED" in codes


def test_dedupe_keeps_highest_confidence_per_code_and_path():
    rules = [
        {
            "code_template": "RISK:X",
            "when": {"field_path": "$.a[*].x", "exists": True},
            "confidence": 0.6,
        },
        {
            "code_template": "RISK:X",
            "when": {"field_path": "$.a[*].x", "exists": True},
            "confidence": 0.9,
        },
    ]
    payload = {"a": [{"x": 1}]}
    markers = MarkerEngine(rules).evaluate(payload)
    assert len(markers) == 1
    assert markers[0].confidence == 0.9
