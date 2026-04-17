from envx.classifier import Classification, DocTypeClassifier, RuleClassifier


def test_rule_classifier_property_disclosure_from_filename():
    c = RuleClassifier().classify(
        filename="seller_disclosure_2024.pdf",
        first_page_text="",
    )
    assert c is not None
    assert c.doc_type == "property_disclosure"
    assert c.source == "rule"
    assert c.confidence >= 0.35


def test_rule_classifier_environmental_from_text():
    text = (
        "PHASE I ENVIRONMENTAL SITE ASSESSMENT prepared by ACME Env. "
        "Scope per ASTM E1527. No recognized environmental condition was identified."
    )
    c = RuleClassifier().classify(filename="ESA.pdf", first_page_text=text)
    assert c is not None
    assert c.doc_type == "environmental_report"


def test_rule_classifier_inspection_report():
    text = "HOME INSPECTION REPORT. Inspector's observations: roof satisfactory."
    c = RuleClassifier().classify(
        filename="building_inspection_04_2024.pdf",
        first_page_text=text,
    )
    assert c is not None
    assert c.doc_type == "inspection_report"


def test_rule_classifier_abstains_on_noise():
    c = RuleClassifier().classify(
        filename="scan_001.pdf",
        first_page_text="Lorem ipsum dolor sit amet.",
    )
    assert c is None


def test_two_stage_falls_back_to_llm_when_rule_abstains():
    class StubLLM:
        def classify(self, *, filename, first_page_text):
            return Classification(
                doc_type="insurance_claim", confidence=0.8, source="llm"
            )

    c = DocTypeClassifier(llm=StubLLM()).classify(
        filename="scan_001.pdf", first_page_text="Lorem"
    )
    assert c.doc_type == "insurance_claim"
    assert c.source == "llm"


def test_two_stage_default_when_both_abstain():
    c = DocTypeClassifier().classify(
        filename="scan_001.pdf", first_page_text="Lorem"
    )
    assert c.doc_type == "unknown"
    assert c.source == "default"
    assert c.confidence == 0.0


def test_two_stage_rule_wins_when_confident():
    class ShouldNotCall:
        def classify(self, *, filename, first_page_text):
            raise AssertionError("rule was confident — LLM should not be called")

    c = DocTypeClassifier(llm=ShouldNotCall()).classify(
        filename="PhaseI_ESA_final.pdf",
        first_page_text=(
            "PHASE I ENVIRONMENTAL SITE ASSESSMENT. ASTM E1527 scope. "
            "No recognized environmental condition."
        ),
    )
    assert c.source == "rule"
    assert c.doc_type == "environmental_report"
