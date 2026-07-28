from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class WorkspaceBuilder(Protocol):
    def build(self, projects: tuple[Any, ...]) -> Any:
        ...


@runtime_checkable
class KnowledgeBuilder(Protocol):
    def build(self, workspace: Any) -> Any:
        ...


@runtime_checkable
class BaselineService(Protocol):
    def capture(self, workspace: Any, policy: Any | None = None) -> Any:
        ...


@runtime_checkable
class QualityGateService(Protocol):
    def evaluate(
        self,
        workspace: Any,
        *,
        baseline: Any | None = None,
        policy: Any | None = None,
        changed_symbols: tuple[tuple[str, str], ...] = (),
    ) -> Any:
        ...


@runtime_checkable
class RetrievalService(Protocol):
    def retrieve(self, graph: Any, query: str) -> Any:
        ...

    def context(self, graph: Any, query: str) -> Any:
        ...


@runtime_checkable
class LlmContractService(Protocol):
    def request(self, context: Any, *, mode: Any | None = None) -> Any:
        ...


@runtime_checkable
class LlmProviderService(Protocol):
    def execute(
        self,
        request: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        ...
