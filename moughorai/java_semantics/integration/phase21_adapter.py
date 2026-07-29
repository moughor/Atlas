from __future__ import annotations
from dataclasses import dataclass
from ..parser import JavaSemanticParser
from ..expressions import JavaExpression

@dataclass(frozen=True, slots=True)
class AdaptedLocalVariable:
    type_name: str
    name: str
    initializer: JavaExpression | None

class Phase21SemanticAdapter:
    def adapt_local_variable(self, value) -> AdaptedLocalVariable:
        initializer = None
        if getattr(value, "initializer", None):
            initializer, _ = JavaSemanticParser.parse_expression_text(value.initializer)
        return AdaptedLocalVariable(value.type_name, value.name, initializer)
