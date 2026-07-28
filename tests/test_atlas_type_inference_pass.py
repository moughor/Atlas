from moughorai.passes import (
    PassManager,
    SemanticPass,
    TypeInferencePass,
)
from moughorai.semantic import PassContext, SemanticDocument


def make_document() -> SemanticDocument:
    return SemanticDocument(
        language="java",
        source="class Example {}",
        syntax_tree=object(),
    )


def test_type_inference_pass_is_a_semantic_pass() -> None:
    assert isinstance(TypeInferencePass(), SemanticPass)


def test_type_inference_pass_descriptor_is_stable() -> None:
    descriptor = TypeInferencePass.descriptor

    assert descriptor.name == "type_inference"
    assert descriptor.requires == frozenset()
    assert descriptor.produces == frozenset()


def test_type_inference_pass_returns_unchanged_document() -> None:
    document = make_document()

    result = TypeInferencePass().run(document, PassContext())

    assert result is document


def test_type_inference_pass_runs_through_pass_manager() -> None:
    document = make_document()
    result = PassManager([TypeInferencePass()]).run(document)

    assert result.document is document
    assert result.execution_order == ("type_inference",)
