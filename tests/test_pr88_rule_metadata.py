import pytest

from moughorai.rule_sdk import (
    RuleAuthoringError,
    RuleCatalog,
    RuleMetadata,
    RuleSeverity,
    metadata_for,
    rule_metadata,
)


class LegacyRule:
    rule_id = "LEGACY"
    default_severity = RuleSeverity.MEDIUM

    def analyze(self, context, reporter):
        pass


def metadata(rule_id="SEC-1", **values):
    return RuleMetadata(
        rule_id,
        values.pop("title", "Secure rule"),
        values.pop("description", "Detects insecure code."),
        values.pop("default_severity", RuleSeverity.HIGH),
        **values,
    )


def test_metadata_serialization_is_complete_and_deterministic() -> None:
    item = metadata(
        tags=("security", "taint"),
        languages=("java", "python"),
        documentation_url="https://example.test/rule",
        references=("https://example.test/a",),
    )
    value = item.to_dict()
    assert value["rule_id"] == "SEC-1"
    assert value["default_severity"] == "high"
    assert value["tags"] == ["security", "taint"]
    assert value["languages"] == ["java", "python"]


def test_decorator_attaches_metadata() -> None:
    item = metadata()

    @rule_metadata(item)
    class SecureRule:
        rule_id = "SEC-1"
        default_severity = RuleSeverity.HIGH
        def analyze(self, context, reporter): pass

    assert metadata_for(SecureRule()) is item


def test_decorator_rejects_id_mismatch() -> None:
    with pytest.raises(RuleAuthoringError, match="does not match"):
        rule_metadata(metadata())(LegacyRule)


def test_legacy_rule_gets_backward_compatible_metadata() -> None:
    item = metadata_for(LegacyRule())
    assert item.rule_id == item.title == "LEGACY"
    assert item.default_severity is RuleSeverity.MEDIUM


def test_metadata_id_and_severity_must_match_rule() -> None:
    class Bad(LegacyRule):
        metadata = metadata("OTHER", default_severity=RuleSeverity.MEDIUM)
    with pytest.raises(RuleAuthoringError, match="id mismatch"):
        metadata_for(Bad())

    class BadSeverity(LegacyRule):
        metadata = metadata("LEGACY", default_severity=RuleSeverity.HIGH)
    with pytest.raises(RuleAuthoringError, match="severity mismatch"):
        metadata_for(BadSeverity())


@pytest.mark.parametrize("field", ["rule_id", "title", "description", "category"])
def test_required_text_fields(field: str) -> None:
    values = {field: ""}
    with pytest.raises(RuleAuthoringError, match=field):
        metadata(**values)


def test_collections_must_be_sorted_unique_and_nonempty() -> None:
    with pytest.raises(RuleAuthoringError, match="tags"):
        metadata(tags=("z", "a"))
    with pytest.raises(RuleAuthoringError, match="languages"):
        metadata(languages=("java", "java"))
    with pytest.raises(RuleAuthoringError, match="references"):
        metadata(references=("",))


def test_urls_are_validated() -> None:
    with pytest.raises(RuleAuthoringError, match="documentation_url"):
        metadata(documentation_url="file:///x")
    with pytest.raises(RuleAuthoringError, match="references"):
        metadata(references=("not-a-url",))


def test_replacement_requires_deprecation_and_cannot_self_reference() -> None:
    with pytest.raises(RuleAuthoringError, match="requires deprecated"):
        metadata(replaced_by="SEC-2")
    with pytest.raises(RuleAuthoringError, match="replace itself"):
        metadata(deprecated=True, replaced_by="SEC-1")


def rules():
    @rule_metadata(metadata("A", category="security", tags=("taint",), languages=("java",)))
    class A:
        rule_id = "A"; default_severity = RuleSeverity.HIGH
        def analyze(self, context, reporter): pass

    @rule_metadata(metadata("B", category="style", default_severity=RuleSeverity.LOW, deprecated=True))
    class B:
        rule_id = "B"; default_severity = RuleSeverity.LOW
        def analyze(self, context, reporter): pass
    return B(), A(), LegacyRule()


def test_catalog_is_sorted_and_queryable() -> None:
    catalog = RuleCatalog(rules())
    assert [item.rule_id for item in catalog.entries()] == ["A", "B", "LEGACY"]
    assert catalog.get("A").category == "security"
    with pytest.raises(KeyError, match="unknown rule metadata"):
        catalog.get("missing")


def test_catalog_filters_and_hides_deprecated_by_default() -> None:
    catalog = RuleCatalog(rules())
    assert [item.rule_id for item in catalog.select(tag="taint")] == ["A"]
    assert [item.rule_id for item in catalog.select(language="python")] == ["LEGACY"]
    assert [item.rule_id for item in catalog.select(include_deprecated=True)] == ["A", "B", "LEGACY"]


def test_catalog_serialization() -> None:
    assert [item["rule_id"] for item in RuleCatalog(rules()).to_dict()["rules"]] == ["A", "B", "LEGACY"]


def test_catalog_rejects_duplicate_ids() -> None:
    with pytest.raises(RuleAuthoringError, match="duplicate"):
        RuleCatalog((LegacyRule(), LegacyRule()))
