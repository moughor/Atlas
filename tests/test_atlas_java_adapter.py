from moughorai.java_semantics.integration import AtlasSemanticAdapter
from moughorai.semantic import SemanticDocument


def test_adapter_builds_language_neutral_document():
    document = AtlasSemanticAdapter().adapt_method_body("{ int x = 1; return; }")
    assert isinstance(document, SemanticDocument)
    assert document.language == "java"
    assert document.metadata["front_end"] == "java_semantics"
    assert document.get_artifact("scopes") is not None
    assert document.get_artifact("unresolved_names") == ()


def test_adapter_preserves_unresolved_names():
    document = AtlasSemanticAdapter().adapt_method_body("{ save(user); }")
    assert document.require_artifact("unresolved_names") == ("user",)


def test_adapter_preserves_parser_diagnostics():
    document = AtlasSemanticAdapter().adapt_method_body("{ int x = ; }")
    assert len(document.diagnostics) > 0
    assert all(item.pass_name == "java-alpha-front-end" for item in document.diagnostics)
