from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from moughorai.semantic import PassContext, SemanticDocument


@dataclass(frozen=True, slots=True)
class PassDescriptor:
    name: str
    requires: frozenset[str] = frozenset()
    produces: frozenset[str] = frozenset()


class SemanticPass(ABC):
    descriptor: PassDescriptor

    @abstractmethod
    def run(self, document: SemanticDocument, context: PassContext) -> SemanticDocument:
        """Return an enriched document without mutating the input document."""
        raise NotImplementedError
