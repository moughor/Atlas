import pytest

from moughorai.passes import (
    PassConfigurationError,
    PassDescriptor,
    PassExecutionError,
    PassManager,
    SemanticPass,
)
from moughorai.semantic import PassContext, SemanticDocument


class ArtifactPass(SemanticPass):
    def __init__(self, name, produces, requires=()):
        self.descriptor = PassDescriptor(name, frozenset(requires), frozenset({produces}))
        self.output = produces

    def run(self, document, context):
        return document.with_artifact(self.output, self.descriptor.name)


class BrokenPass(SemanticPass):
    descriptor = PassDescriptor("broken", produces=frozenset({"missing"}))

    def run(self, document, context):
        return document


class ExplodingPass(SemanticPass):
    descriptor = PassDescriptor("explode")

    def run(self, document, context):
        raise ValueError("boom")


class InvalidReturnPass(SemanticPass):
    descriptor = PassDescriptor("invalid")

    def run(self, document, context):
        return None


def document():
    return SemanticDocument("java", "{}", object())


def test_manager_runs_passes_in_dependency_order():
    manager = PassManager(
        [
            ArtifactPass("facts", "facts", requires=("types",)),
            ArtifactPass("symbols", "symbols"),
            ArtifactPass("types", "types", requires=("symbols",)),
        ]
    )
    result = manager.run(document())
    assert result.execution_order == ("symbols", "types", "facts")
    assert result.document.require_artifact("facts") == "facts"


def test_existing_document_artifacts_satisfy_dependencies():
    manager = PassManager([ArtifactPass("types", "types", requires=("symbols",))])
    result = manager.run(document().with_artifact("symbols", {}))
    assert result.execution_order == ("types",)


def test_duplicate_pass_names_are_rejected():
    manager = PassManager([ArtifactPass("same", "a")])
    with pytest.raises(PassConfigurationError, match="Duplicate"):
        manager.add(ArtifactPass("same", "b"))


def test_missing_dependencies_are_reported():
    manager = PassManager([ArtifactPass("types", "types", requires=("symbols",))])
    with pytest.raises(PassConfigurationError, match="symbols"):
        manager.run(document())


def test_cycles_are_reported_as_unresolvable():
    manager = PassManager(
        [
            ArtifactPass("a", "a", requires=("b",)),
            ArtifactPass("b", "b", requires=("a",)),
        ]
    )
    with pytest.raises(PassConfigurationError, match="Unresolvable"):
        manager.run(document())


def test_metrics_and_logging_are_recorded():
    messages = []
    context = PassContext(logger=messages.append)
    PassManager([ArtifactPass("symbols", "symbols")]).run(document(), context)
    assert messages == ["Running semantic pass: symbols"]
    assert context.metrics[0].pass_name == "symbols"
    assert context.metrics[0].duration_ns >= 0
    assert context.metrics[0].produced == ("symbols",)


def test_cancelled_pipeline_stops_before_execution():
    context = PassContext(cancelled=lambda: True)
    with pytest.raises(PassExecutionError, match="cancelled"):
        PassManager([ArtifactPass("symbols", "symbols")]).run(document(), context)


def test_declared_outputs_must_be_produced():
    with pytest.raises(PassExecutionError, match="did not produce"):
        PassManager([BrokenPass()]).run(document())


def test_pass_exception_is_wrapped_with_pass_name():
    with pytest.raises(PassExecutionError, match="explode") as error:
        PassManager([ExplodingPass()]).run(document())
    assert isinstance(error.value.__cause__, ValueError)


def test_invalid_return_type_is_rejected():
    with pytest.raises(PassExecutionError, match="expected SemanticDocument"):
        PassManager([InvalidReturnPass()]).run(document())
