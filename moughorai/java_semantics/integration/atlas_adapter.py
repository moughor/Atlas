from __future__ import annotations

from moughorai.semantic import (
    Diagnostic,
    DiagnosticSeverity,
    SemanticDocument,
)

from ..diagnostics import DiagnosticSeverity as JavaDiagnosticSeverity
from ..service import JavaSemanticFrontEnd


_SEVERITY_MAP = {
    JavaDiagnosticSeverity.INFO: DiagnosticSeverity.INFO,
    JavaDiagnosticSeverity.WARNING: DiagnosticSeverity.WARNING,
    JavaDiagnosticSeverity.ERROR: DiagnosticSeverity.ERROR,
}


class AtlasSemanticAdapter:
    """Creates an Atlas document from the existing Alpha Java front-end."""

    def adapt_method_body(self, source: str) -> SemanticDocument:
        alpha = JavaSemanticFrontEnd().analyze_method_body(source)
        diagnostics = tuple(
            Diagnostic(
                code=item.code,
                message=item.message,
                severity=_SEVERITY_MAP[item.severity],
                location=item.span,
                pass_name="java-alpha-front-end",
            )
            for item in alpha.diagnostics
        )
        document = SemanticDocument(
            language="java",
            source=source,
            syntax_tree=alpha.root,
            metadata={"front_end": "java_semantics", "front_end_version": "v2-alpha"},
        )
        document = document.with_artifact("scopes", alpha.root_scope)
        document = document.with_artifact("unresolved_names", alpha.unresolved_names)
        return document.with_diagnostics(diagnostics)
