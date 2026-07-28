from __future__ import annotations

from moughorai.semantic.types.relations import PRIMITIVE_WIDENING

from dataclasses import dataclass
from typing import Hashable

from moughorai.java_semantics.expressions import LiteralExpression
from moughorai.java_semantics.statements import LocalVariableDeclaration
from moughorai.semantic import (
    Diagnostic,
    DiagnosticSeverity,
    PassContext,
    SemanticDocument,
    SymbolTable,
    VariableSymbol,
)
from moughorai.semantic.types import (
    ClassType,
    NullType,
    PrimitiveType,
    Type,
    TypeRegistry,
    UnknownType,
)

from .base import PassDescriptor, SemanticPass
from .literal_type_inference import infer_java_literal_type


VARIABLE_DECLARATION_TYPE_MISMATCH = "ATLAS-TYPE-001"
VARIABLE_REQUIRES_INITIALIZER = "ATLAS-TYPE-002"
VARIABLE_UNKNOWN_INITIALIZER = "ATLAS-TYPE-003"


@dataclass(frozen=True, slots=True)
class VariableTypeInferenceResult:
    declaration: LocalVariableDeclaration
    declared_type: Type
    initializer_type: Type | None
    variable_type: Type
    compatible: bool
    inferred: bool
    diagnostics: tuple[Diagnostic, ...] = ()


def _stable_node_key(node: object, role: str) -> Hashable:
    span = getattr(node, "span", None)
    start = getattr(span, "start", None)
    end = getattr(span, "end", None)
    name = getattr(node, "name", None)
    return (role, node.__class__.__name__, start, end, name)


def resolve_declared_type(type_name: str, registry: TypeRegistry | None = None) -> Type:
    if not isinstance(type_name, str):
        raise TypeError("type_name must be a string")

    normalized = type_name.strip()
    if not normalized:
        raise ValueError("type_name must not be empty")

    target = registry if registry is not None else TypeRegistry()
    primitives = {
        "byte", "short", "int", "long", "float", "double",
        "boolean", "char",
    }

    if normalized in primitives:
        return target.primitive(normalized)
    if normalized in {"String", "java.lang.String"}:
        return target.class_type("java.lang.String")
    if normalized == "var":
        return target.unknown
    return target.class_type(normalized)


def infer_initializer_type(
    initializer: object | None,
    registry: TypeRegistry | None = None,
) -> Type | None:
    if initializer is None:
        return None
    if isinstance(initializer, LiteralExpression):
        return infer_java_literal_type(initializer.source_text, registry).semantic_type
    return (registry if registry is not None else TypeRegistry()).unknown


def is_assignment_compatible(target: Type, source: Type) -> bool:
    if not isinstance(target, Type) or not isinstance(source, Type):
        raise TypeError("target and source must be Type instances")
    if isinstance(target, UnknownType) or isinstance(source, UnknownType):
        return True
    if target == source:
        return True
    if isinstance(source, NullType):
        return target.is_reference

    if isinstance(target, PrimitiveType) and isinstance(source, PrimitiveType):
        widening = PRIMITIVE_WIDENING
        return target.name in widening.get(source.name, set())

    return False


def analyze_variable_declaration(
    declaration: LocalVariableDeclaration,
    registry: TypeRegistry | None = None,
) -> VariableTypeInferenceResult:
    if not isinstance(declaration, LocalVariableDeclaration):
        raise TypeError("declaration must be a LocalVariableDeclaration")

    target = registry if registry is not None else TypeRegistry()
    initializer_type = infer_initializer_type(declaration.initializer, target)
    is_var = declaration.type_name.strip() == "var"
    diagnostics: list[Diagnostic] = []

    if is_var:
        if initializer_type is None:
            variable_type = target.unknown
            diagnostics.append(Diagnostic(
                code=VARIABLE_REQUIRES_INITIALIZER,
                message=f"Variable '{declaration.name}' declared with var requires an initializer.",
                severity=DiagnosticSeverity.ERROR,
                location=declaration.span,
                pass_name="variable_type_inference",
            ))
            compatible = False
        else:
            variable_type = initializer_type
            compatible = not isinstance(initializer_type, UnknownType)
            if isinstance(initializer_type, UnknownType):
                diagnostics.append(Diagnostic(
                    code=VARIABLE_UNKNOWN_INITIALIZER,
                    message=f"Cannot infer the type of variable '{declaration.name}' from its initializer.",
                    severity=DiagnosticSeverity.ERROR,
                    location=declaration.span,
                    pass_name="variable_type_inference",
                ))
    else:
        variable_type = resolve_declared_type(declaration.type_name, target)
        compatible = initializer_type is None or is_assignment_compatible(variable_type, initializer_type)
        if initializer_type is not None and not compatible:
            diagnostics.append(Diagnostic(
                code=VARIABLE_DECLARATION_TYPE_MISMATCH,
                message=(
                    f"Cannot assign {initializer_type.display_name} to "
                    f"variable '{declaration.name}' of type {variable_type.display_name}."
                ),
                severity=DiagnosticSeverity.ERROR,
                location=declaration.span,
                pass_name="variable_type_inference",
            ))

    return VariableTypeInferenceResult(
        declaration=declaration,
        declared_type=resolve_declared_type(declaration.type_name, target),
        initializer_type=initializer_type,
        variable_type=variable_type,
        compatible=compatible,
        inferred=is_var,
        diagnostics=tuple(diagnostics),
    )


def attach_variable_declaration(
    document: SemanticDocument,
    declaration: LocalVariableDeclaration,
    registry: TypeRegistry | None = None,
) -> SemanticDocument:
    if not isinstance(document, SemanticDocument):
        raise TypeError("document must be a SemanticDocument")

    result = analyze_variable_declaration(declaration, registry)
    declaration_key = _stable_node_key(declaration, "variable-declaration")
    symbol_key = _stable_node_key(declaration, "variable-symbol")
    initializer_key = (
        _stable_node_key(declaration.initializer, "initializer")
        if declaration.initializer is not None else None
    )

    updated = document.with_type(declaration_key, result.variable_type)
    if initializer_key is not None and result.initializer_type is not None:
        updated = updated.with_type(initializer_key, result.initializer_type)

    updated = updated.with_symbol(VariableSymbol(
        key=symbol_key,
        name=declaration.name,
        semantic_type=result.variable_type,
        declaration_key=declaration_key,
        initializer_key=initializer_key,
        inferred=result.inferred,
    ))
    return updated.with_diagnostics(result.diagnostics)


class VariableTypeInferencePass(SemanticPass):
    descriptor = PassDescriptor(
        name="variable_type_inference",
        requires=frozenset(),
        produces=frozenset({"types", "symbols"}),
    )

    def __init__(self, registry: TypeRegistry | None = None) -> None:
        self.registry = registry if registry is not None else TypeRegistry()

    def run(self, document: SemanticDocument, context: PassContext) -> SemanticDocument:
        if not isinstance(document, SemanticDocument):
            raise TypeError("document must be a SemanticDocument")

        result = document

        def visit(node: object | None) -> None:
            nonlocal result
            if node is None:
                return
            if isinstance(node, LocalVariableDeclaration):
                result = attach_variable_declaration(result, node, self.registry)
            if hasattr(node, "__dataclass_fields__"):
                for field_name in node.__dataclass_fields__:
                    value = getattr(node, field_name)
                    if hasattr(value, "__dataclass_fields__"):
                        visit(value)
                    elif isinstance(value, tuple):
                        for item in value:
                            if hasattr(item, "__dataclass_fields__"):
                                visit(item)

        visit(document.syntax_tree)
        return result


__all__ = [
    "VARIABLE_DECLARATION_TYPE_MISMATCH",
    "VARIABLE_REQUIRES_INITIALIZER",
    "VARIABLE_UNKNOWN_INITIALIZER",
    "VariableTypeInferencePass",
    "VariableTypeInferenceResult",
    "analyze_variable_declaration",
    "attach_variable_declaration",
    "infer_initializer_type",
    "is_assignment_compatible",
    "resolve_declared_type",
]
