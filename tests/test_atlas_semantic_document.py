import pytest

from moughorai.semantic import (
    Diagnostic,
    DiagnosticSeverity,
    SemanticDocument,
    semantic_document_to_dict,
)


def make_document():
    return SemanticDocument(language="java", source="{}", syntax_tree={"node": "block"})


def test_document_is_language_neutral_and_immutable():
    document = make_document()
    assert document.language == "java"
    with pytest.raises(TypeError):
        document.artifacts["types"] = {}


def test_with_artifact_returns_new_document():
    original = make_document()
    enriched = original.with_artifact("symbols", ("x",))
    assert "symbols" not in original.artifacts
    assert enriched.require_artifact("symbols") == ("x",)


def test_artifact_can_be_removed_without_mutation():
    original = make_document().with_artifact("symbols", ("x",))
    cleaned = original.without_artifact("symbols")
    assert "symbols" in original.artifacts
    assert "symbols" not in cleaned.artifacts


def test_require_artifact_has_clear_error():
    with pytest.raises(KeyError, match="types"):
        make_document().require_artifact("types")


def test_metadata_is_merged_immutably():
    original = make_document().with_metadata(version="alpha")
    updated = original.with_metadata(release="atlas")
    assert original.metadata == {"version": "alpha"}
    assert updated.metadata == {"version": "alpha", "release": "atlas"}


def test_diagnostics_are_accumulated_immutably():
    diagnostic = Diagnostic("ATLAS001", "Example", DiagnosticSeverity.WARNING)
    original = make_document()
    updated = original.with_diagnostic(diagnostic)
    assert len(original.diagnostics) == 0
    assert tuple(updated.diagnostics) == (diagnostic,)


def test_document_serialization_is_stable():
    document = make_document().with_artifact("z", 2).with_artifact("a", 1)
    data = semantic_document_to_dict(document)
    assert data["kind"] == "SemanticDocument"
    assert list(data["artifacts"]) == ["a", "z"]
    assert data["language"] == "java"
