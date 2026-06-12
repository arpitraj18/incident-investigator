"""Tests for the Drain template extractor."""
from app.processing.template_extractor import TemplateExtractor


def test_similar_logs_share_template() -> None:
    extractor = TemplateExtractor()
    m1 = extractor.add_log("connection timeout on node 42")
    m2 = extractor.add_log("connection timeout on node 99")
    # Same event, different number -> same template.
    assert m1.template_id == m2.template_id
    # Drain generalizes only after seeing the second example: the template
    # on the SECOND match should contain the wildcard, not the first.
    assert "<*>" in m2.template

def test_different_logs_get_different_templates() -> None:
    extractor = TemplateExtractor()
    m1 = extractor.add_log("connection timeout on node 42")
    m2 = extractor.add_log("disk failure detected on drive sda")
    assert m1.template_id != m2.template_id


def test_parameter_extraction() -> None:
    extractor = TemplateExtractor()
    extractor.add_log("memory error at address 0x1000")
    match = extractor.add_log("memory error at address 0x2000")
    # The varying part should be captured as a parameter.
    assert any("0x2000" in p for p in match.parameters)


def test_match_only_does_not_learn() -> None:
    extractor = TemplateExtractor()
    extractor.add_log("known event type alpha")
    count_before = extractor.template_count

    # Matching an unknown message should NOT create a new template.
    result = extractor.match_only("completely unrelated novel message xyz")
    assert result is None
    assert extractor.template_count == count_before


def test_template_count_grows() -> None:
    extractor = TemplateExtractor()
    assert extractor.template_count == 0
    extractor.add_log("event type one")
    extractor.add_log("event type two completely different")
    assert extractor.template_count >= 2