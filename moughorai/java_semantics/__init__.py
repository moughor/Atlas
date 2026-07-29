from .diagnostics import Diagnostic, DiagnosticBag, DiagnosticSeverity
from .source import SourceSpan
from .tokens import Token, TokenKind
from .lexer import JavaLexer
from .token_stream import TokenStream
from .expressions import (
    ArrayAccessExpression,
    AssignmentExpression,
    BinaryExpression,
    CastExpression,
    ConditionalExpression,
    FieldAccessExpression,
    JavaExpression,
    LiteralExpression,
    MethodCallExpression,
    ObjectCreationExpression,
    ParenthesizedExpression,
    SuperExpression,
    ThisExpression,
    UnaryExpression,
    UnknownExpression,
    UnresolvedNameExpression,
    VariableExpression,
)
from .statements import (
    BlockStatement,
    BreakStatement,
    ContinueStatement,
    ExpressionStatement,
    IfStatement,
    JavaStatement,
    LocalVariableDeclaration,
    ReturnStatement,
    ThrowStatement,
    UnknownStatement,
    WhileStatement,
)
from .parser import JavaSemanticParser
from .scopes import (
    Scope,
    ScopeKind,
    Symbol,
    SymbolKind,
    ScopeBuilder,
    LocalResolver,
    ResolutionResult,
)
from .serialization import semantic_to_dict
from .service import JavaAnalysisResult, JavaSemanticFrontEnd, SemanticDocument

__all__ = [
    "Diagnostic", "DiagnosticBag", "DiagnosticSeverity",
    "SourceSpan", "Token", "TokenKind", "JavaLexer", "TokenStream",
    "JavaSemanticParser", "Scope", "ScopeKind", "Symbol", "SymbolKind",
    "ScopeBuilder", "LocalResolver", "ResolutionResult",
    "semantic_to_dict", "JavaAnalysisResult", "JavaSemanticFrontEnd", "SemanticDocument",
    "ArrayAccessExpression", "AssignmentExpression", "BinaryExpression",
    "CastExpression", "ConditionalExpression", "FieldAccessExpression",
    "JavaExpression", "LiteralExpression", "MethodCallExpression",
    "ObjectCreationExpression", "ParenthesizedExpression", "SuperExpression",
    "ThisExpression", "UnaryExpression", "UnknownExpression",
    "UnresolvedNameExpression", "VariableExpression", "BlockStatement",
    "BreakStatement", "ContinueStatement", "ExpressionStatement", "IfStatement",
    "JavaStatement", "LocalVariableDeclaration", "ReturnStatement",
    "ThrowStatement", "UnknownStatement", "WhileStatement",
]

# Atlas PR11: flow-sensitive definite-assignment analysis
from .flow_analysis import (
    DefiniteAssignmentAnalyzer,
    FlowDiagnostic,
    FlowDiagnosticCode,
    FlowState,
    VariableFacts,
    analyze_do_while,
    analyze_if,
    analyze_infinite_loop_with_break,
    analyze_while,
    merge_states,
)

# Atlas PR12: pattern-matching foundations
from .pattern_matching import (
    PatternAnalyzer,
    PatternBinding,
    PatternDiagnostic,
    PatternDiagnosticCode,
    PatternFlow,
    PatternScope,
    TypePattern,
    analyze_and,
    analyze_or,
    analyze_type_pattern,
    empty_condition,
    intersect_scopes,
    is_pattern_compatible,
)

# Atlas PR13: sealed hierarchies and exhaustive switches
from .sealed_types import PermittedSubtype, SealedType, TypeOpenness
from .hierarchy_graph import (
    HierarchyDiagnostic,
    HierarchyDiagnosticCode,
    HierarchyGraph,
)
from .switch_exhaustiveness import (
    ExhaustivenessResult,
    SwitchAnalyzer,
    SwitchCase,
    SwitchCaseKind,
    SwitchDiagnostic,
    SwitchDiagnosticCode,
)

# Atlas PR14: record patterns
from .record_patterns import (
    ComponentPattern,
    ComponentPatternKind,
    RecordComponent,
    RecordDeclaration,
    RecordPattern,
    RecordPatternBinding,
)
from .record_pattern_validator import (
    RecordPatternDiagnostic,
    RecordPatternDiagnosticCode,
    RecordPatternRegistry,
    RecordPatternResult,
    RecordPatternValidator,
)
