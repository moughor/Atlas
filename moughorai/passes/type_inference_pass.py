from __future__ import annotations

from moughorai.semantic import PassContext, SemanticDocument

from .base import PassDescriptor, SemanticPass


class TypeInferencePass(SemanticPass):
    """
    Compiler pass responsible for semantic type inference.

    This initial Sprint 3 implementation establishes the public pass contract
    and pipeline integration point. Literal, variable, and expression
    inference will be added incrementally in the following changes.

    The pass currently consumes no semantic artifacts and produces no declared
    artifacts. Consequently, it returns the immutable input document unchanged.

    Future implementation will produce the ``types`` artifact stored as a
    language-neutral ``TypeTable`` on ``SemanticDocument``.
    """

    descriptor = PassDescriptor(
        name="type_inference",
        requires=frozenset(),
        produces=frozenset(),
    )

    def run(
        self,
        document: SemanticDocument,
        context: PassContext,
    ) -> SemanticDocument:
        """
        Execute semantic type inference.

        Args:
            document:
                Immutable semantic document to analyze.
            context:
                Compiler-pass execution context.

        Returns:
            The semantic document. PR #1 intentionally performs no inference.
        """
        return document
