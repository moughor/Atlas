from __future__ import annotations
from dataclasses import dataclass
from .diagnostics import Diagnostic
from .parser import JavaSemanticParser
from .scopes import Scope, ScopeBuilder, LocalResolver
from .statements import BlockStatement

@dataclass(frozen=True, slots=True)
class JavaAnalysisResult:
    source: str
    root: BlockStatement
    root_scope: Scope
    unresolved_names: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]

class JavaSemanticFrontEnd:
    def analyze_method_body(self, source: str) -> JavaAnalysisResult:
        parser = JavaSemanticParser(source)
        root = parser.parse_block()
        scope = ScopeBuilder().build(root)
        resolved = LocalResolver().resolve(root, scope)
        return JavaAnalysisResult(
            source=source,
            root=resolved.root,
            root_scope=scope,
            unresolved_names=resolved.unresolved_names,
            diagnostics=parser.diagnostics.snapshot(),
        )


# Backwards-compatible alias for consumers of the pre-hardening name.
SemanticDocument = JavaAnalysisResult
