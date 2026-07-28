from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from moughorai.semantic import PassContext, SemanticDocument

from .base import SemanticPass


class PassConfigurationError(ValueError):
    pass


class PassExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PipelineResult:
    document: SemanticDocument
    execution_order: tuple[str, ...]


class PassManager:
    def __init__(self, passes: Iterable[SemanticPass] = ()) -> None:
        self._passes: list[SemanticPass] = []
        for semantic_pass in passes:
            self.add(semantic_pass)

    @property
    def passes(self) -> tuple[SemanticPass, ...]:
        return tuple(self._passes)

    def add(self, semantic_pass: SemanticPass) -> PassManager:
        name = semantic_pass.descriptor.name
        if any(item.descriptor.name == name for item in self._passes):
            raise PassConfigurationError(f"Duplicate semantic pass: {name}")
        self._passes.append(semantic_pass)
        return self

    def ordered(self, initially_available: Iterable[str] = ()) -> tuple[SemanticPass, ...]:
        available = set(initially_available)
        remaining = list(self._passes)
        ordered: list[SemanticPass] = []

        while remaining:
            executable = next(
                (
                    item
                    for item in remaining
                    if item.descriptor.requires.issubset(available)
                ),
                None,
            )
            if executable is None:
                missing = {
                    item.descriptor.name: sorted(item.descriptor.requires - available)
                    for item in remaining
                }
                raise PassConfigurationError(
                    f"Unresolvable pass dependencies: {missing}"
                )
            ordered.append(executable)
            remaining.remove(executable)
            available.update(executable.descriptor.produces)

        return tuple(ordered)

    def run(
        self,
        document: SemanticDocument,
        context: PassContext | None = None,
    ) -> PipelineResult:
        context = context or PassContext()
        ordered = self.ordered(document.artifacts.keys())
        current = document
        names: list[str] = []

        for semantic_pass in ordered:
            if context.is_cancelled():
                raise PassExecutionError("Semantic pipeline execution was cancelled")

            descriptor = semantic_pass.descriptor
            context.emit(f"Running semantic pass: {descriptor.name}")
            started = context.timer()
            before = current
            try:
                current = semantic_pass.run(current, context)
            except Exception as exc:
                raise PassExecutionError(
                    f"Semantic pass '{descriptor.name}' failed"
                ) from exc

            if not isinstance(current, SemanticDocument):
                raise PassExecutionError(
                    f"Semantic pass '{descriptor.name}' returned {type(current).__name__}, "
                    "expected SemanticDocument"
                )
            missing_outputs = descriptor.produces - current.artifacts.keys()
            if missing_outputs:
                raise PassExecutionError(
                    f"Semantic pass '{descriptor.name}' did not produce: "
                    f"{sorted(missing_outputs)}"
                )
            if current is before and descriptor.produces:
                raise PassExecutionError(
                    f"Semantic pass '{descriptor.name}' declared outputs but returned "
                    "the unchanged document"
                )

            produced = tuple(sorted(descriptor.produces))
            context.record(descriptor.name, started, produced)
            names.append(descriptor.name)

        return PipelineResult(current, tuple(names))
