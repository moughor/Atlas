from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

from moughorai.semantic import SemanticDocument
from moughorai.semantic.types import (
    ClassType,
    NullType,
    PrimitiveType,
    Type,
    TypeRegistry,
    UnknownType,
)

from .literal_inference import (
    LiteralInferenceResult,
    LiteralKind,
    infer_java_literal,
)


@dataclass(frozen=True, slots=True)
class LiteralTypeInferenceResult:
    """
    Complete immutable result of Java literal semantic type inference.

    This result preserves both levels of deterministic analysis:

    1. Lexical literal classification.
    2. Resolution to the language-neutral Atlas semantic type system.

    Attributes:
        literal:
            Result produced by ``infer_java_literal``.
        semantic_type:
            Canonical Atlas type associated with the literal.
    """

    literal: LiteralInferenceResult
    semantic_type: Type

    @property
    def source(self) -> str:
        """
        Return the original Java source text.
        """
        return self.literal.source

    @property
    def kind(self) -> LiteralKind:
        """
        Return the classified Java literal kind.
        """
        return self.literal.kind

    @property
    def valid(self) -> bool:
        """
        Return whether the literal was recognized successfully.
        """
        return self.literal.valid


def literal_kind_to_type(
    kind: LiteralKind,
    registry: TypeRegistry | None = None,
) -> Type:
    """
    Resolve a Java literal kind to an Atlas semantic type.

    Args:
        kind:
            Literal classification to resolve.
        registry:
            Optional registry used to canonicalize allocated semantic types.

    Returns:
        A canonical Atlas ``Type``.

    Mapping:
        ``INT``      -> ``PrimitiveType("int")``
        ``LONG``     -> ``PrimitiveType("long")``
        ``FLOAT``    -> ``PrimitiveType("float")``
        ``DOUBLE``   -> ``PrimitiveType("double")``
        ``BOOLEAN``  -> ``PrimitiveType("boolean")``
        ``CHAR``     -> ``PrimitiveType("char")``
        ``STRING``   -> ``ClassType("java.lang.String")``
        ``NULL``     -> ``NullType``
        ``UNKNOWN``  -> ``UnknownType``

    Raises:
        TypeError:
            If ``kind`` is not a ``LiteralKind``.
    """

    if not isinstance(kind, LiteralKind):
        raise TypeError("kind must be a LiteralKind")

    target = registry if registry is not None else TypeRegistry()

    primitive_names = {
        LiteralKind.INT: "int",
        LiteralKind.LONG: "long",
        LiteralKind.FLOAT: "float",
        LiteralKind.DOUBLE: "double",
        LiteralKind.BOOLEAN: "boolean",
        LiteralKind.CHAR: "char",
    }

    primitive_name = primitive_names.get(kind)

    if primitive_name is not None:
        return target.primitive(primitive_name)

    if kind is LiteralKind.STRING:
        return target.class_type("java.lang.String")

    if kind is LiteralKind.NULL:
        return target.null

    return target.unknown


def resolve_literal_type(
    literal: LiteralInferenceResult,
    registry: TypeRegistry | None = None,
) -> LiteralTypeInferenceResult:
    """
    Resolve an existing literal-classification result to an Atlas type.

    This function is useful when lexical literal inference has already been
    performed and should not be repeated.

    Args:
        literal:
            Existing immutable literal-inference result.
        registry:
            Optional semantic type registry.

    Returns:
        Combined literal and semantic type result.

    Raises:
        TypeError:
            If ``literal`` is not a ``LiteralInferenceResult``.
    """

    if not isinstance(literal, LiteralInferenceResult):
        raise TypeError("literal must be a LiteralInferenceResult")

    return LiteralTypeInferenceResult(
        literal=literal,
        semantic_type=literal_kind_to_type(literal.kind, registry),
    )


def infer_java_literal_type(
    source: str,
    registry: TypeRegistry | None = None,
) -> LiteralTypeInferenceResult:
    """
    Infer the complete Atlas semantic type of one Java literal.

    The operation is deterministic and side-effect free.

    Invalid or unsupported source text is mapped to the canonical
    ``UnknownType`` rather than raising an inference exception.

    Args:
        source:
            Complete Java literal source text.
        registry:
            Optional registry for semantic type canonicalization.

    Returns:
        A combined immutable inference result.
    """

    literal = infer_java_literal(source)
    return resolve_literal_type(literal, registry)


def attach_java_literal_type(
    document: SemanticDocument,
    node_key: Hashable,
    source: str,
    registry: TypeRegistry | None = None,
) -> SemanticDocument:
    """
    Infer and attach a Java literal type to a SemanticDocument.

    The original document is never mutated. A new document containing an
    updated immutable ``TypeTable`` is returned.

    Args:
        document:
            Semantic document that owns the literal node.
        node_key:
            Stable, hashable semantic key identifying the literal expression.
        source:
            Complete Java literal source text.
        registry:
            Optional registry for canonical type identity.

    Returns:
        A new ``SemanticDocument`` containing the inferred type.

    Raises:
        TypeError:
            If ``document`` is not a ``SemanticDocument`` or if ``node_key``
            is not hashable.
    """

    if not isinstance(document, SemanticDocument):
        raise TypeError("document must be a SemanticDocument")

    try:
        hash(node_key)
    except TypeError as error:
        raise TypeError("node_key must be hashable") from error

    result = infer_java_literal_type(source, registry)

    return document.with_type(
        node_key,
        result.semantic_type,
    )


__all__ = [
    "LiteralTypeInferenceResult",
    "attach_java_literal_type",
    "infer_java_literal_type",
    "literal_kind_to_type",
    "resolve_literal_type",
]
