from .base import PassDescriptor, SemanticPass
from .literal_inference import (
    LiteralInferenceResult,
    LiteralKind,
    infer_java_literal,
)
from .literal_type_inference import (
    LiteralTypeInferenceResult,
    attach_java_literal_type,
    infer_java_literal_type,
    literal_kind_to_type,
    resolve_literal_type,
)
from .variable_type_inference import (
    VARIABLE_DECLARATION_TYPE_MISMATCH,
    VARIABLE_REQUIRES_INITIALIZER,
    VARIABLE_UNKNOWN_INITIALIZER,
    VariableTypeInferencePass,
    VariableTypeInferenceResult,
    analyze_variable_declaration,
    attach_variable_declaration,
    infer_initializer_type,
    is_assignment_compatible,
    resolve_declared_type,
)
from .expression_type_inference import (
    EXPRESSION_CONDITIONAL_MISMATCH,
    EXPRESSION_INVALID_OPERANDS,
    EXPRESSION_UNKNOWN_NAME,
    ExpressionTypeInferencePass,
    ExpressionTypeInferenceResult,
    attach_expression_type,
    expression_node_key,
    infer_expression_type,
)
from .statement_type_checking import (
    STATEMENT_DECLARATION_TYPE_MISMATCH,
    STATEMENT_INVALID_THROW_TYPE,
    STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP,
    STATEMENT_MISSING_RETURN_VALUE,
    STATEMENT_NON_BOOLEAN_CONDITION,
    STATEMENT_RETURN_TYPE_MISMATCH,
    STATEMENT_UNEXPECTED_RETURN_VALUE,
    STATEMENT_UNREACHABLE,
    StatementTypeCheckingPass,
    StatementTypeCheckingResult,
    check_statement_types,
)
from .method_resolution import (
    METHOD_AMBIGUOUS,
    METHOD_INCOMPATIBLE_ARGUMENT,
    METHOD_NOT_FOUND,
    METHOD_STATIC_CONTEXT_MISMATCH,
    MethodResolutionResult,
    MethodSignature,
    resolve_constructor,
    resolve_method,
)
from .manager import (
    PassConfigurationError,
    PassExecutionError,
    PassManager,
    PipelineResult,
)
from .type_inference_pass import TypeInferencePass

__all__ = [
    "PassConfigurationError",
    "PassDescriptor",
    "PassExecutionError",
    "PassManager",
    "PipelineResult",
    "SemanticPass",
    "TypeInferencePass",
    "LiteralInferenceResult",
    "LiteralKind",
    "infer_java_literal",
    "LiteralTypeInferenceResult",
    "attach_java_literal_type",
    "infer_java_literal_type",
    "literal_kind_to_type",
    "resolve_literal_type",
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
    "EXPRESSION_CONDITIONAL_MISMATCH",
    "EXPRESSION_INVALID_OPERANDS",
    "EXPRESSION_UNKNOWN_NAME",
    "ExpressionTypeInferencePass",
    "ExpressionTypeInferenceResult",
    "attach_expression_type",
    "expression_node_key",
    "infer_expression_type",    "STATEMENT_DECLARATION_TYPE_MISMATCH",
    "STATEMENT_INVALID_THROW_TYPE",
    "STATEMENT_LOOP_CONTROL_OUTSIDE_LOOP",
    "STATEMENT_MISSING_RETURN_VALUE",
    "STATEMENT_NON_BOOLEAN_CONDITION",
    "STATEMENT_RETURN_TYPE_MISMATCH",
    "STATEMENT_UNEXPECTED_RETURN_VALUE",
    "STATEMENT_UNREACHABLE",
    "StatementTypeCheckingPass",
    "StatementTypeCheckingResult",
    "check_statement_types",    "METHOD_AMBIGUOUS",
    "METHOD_INCOMPATIBLE_ARGUMENT",
    "METHOD_NOT_FOUND",
    "METHOD_STATIC_CONTEXT_MISMATCH",
    "MethodResolutionResult",
    "MethodSignature",
    "resolve_constructor",
    "resolve_method",]

from .generic_type_inference import (
    GENERIC_INFERENCE_ARITY,
    GENERIC_INFERENCE_CONFLICT,
    GENERIC_INFERENCE_UNRESOLVED,
    GenericInferenceResult,
    infer_method_type_arguments,
    substitute_type,
)

from .functional_interface_typing import (
    FunctionalInterface, LambdaExpression, MethodReference, TargetTypingResult,
    check_lambda, resolve_method_reference,
)

from .constant_evaluation import (
    ConstantKind, ConstantValue, Literal, Name, Unary, Binary, Cast,
    ConstantEvaluationError, NonConstantExpression, ConstantArithmeticError,
    evaluate, cast_constant, require_constant,
)