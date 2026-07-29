from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class LiteralKind(str, Enum):
    """
    Language-neutral semantic categories for Java literal expressions.

    The enum values intentionally match the canonical Atlas type names that
    will later be resolved through TypeRegistry and stored in TypeTable.
    """

    INT = "int"
    LONG = "long"
    FLOAT = "float"
    DOUBLE = "double"
    BOOLEAN = "boolean"
    CHAR = "char"
    STRING = "String"
    NULL = "null"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LiteralInferenceResult:
    """
    Immutable result of Java literal classification.

    Attributes:
        source:
            Original literal source text.
        kind:
            Inferred semantic literal category.
        normalized:
            Literal text with numeric separators removed where applicable.
        valid:
            Whether the source is recognized as a complete Java literal.
    """

    source: str
    kind: LiteralKind
    normalized: str
    valid: bool

    @classmethod
    def unknown(cls, source: str) -> LiteralInferenceResult:
        """
        Construct an unsuccessful inference result.
        """
        return cls(
            source=source,
            kind=LiteralKind.UNKNOWN,
            normalized=source,
            valid=False,
        )


# Decimal integer literals.
#
# Java permits:
#   0
#   42
#   2_147_483_647
#   42L
#   42l
_DECIMAL_INTEGER_RE = re.compile(
    r"""
    (?:
        0
        |
        [1-9](?:_?[0-9])*
    )
    (?P<suffix>[lL])?
    """,
    re.VERBOSE,
)


# Hexadecimal integer literals.
#
# Java permits:
#   0xFF
#   0XCAFE
#   0x7fff_ffff
#   0xFFL
_HEXADECIMAL_INTEGER_RE = re.compile(
    r"""
    0[xX]
    [0-9a-fA-F](?:_?[0-9a-fA-F])*
    (?P<suffix>[lL])?
    """,
    re.VERBOSE,
)


# Binary integer literals.
#
# Java permits:
#   0b1010
#   0B1111_0000
#   0b1010L
_BINARY_INTEGER_RE = re.compile(
    r"""
    0[bB]
    [01](?:_?[01])*
    (?P<suffix>[lL])?
    """,
    re.VERBOSE,
)


# Octal integer literals.
#
# Java permits:
#   077
#   01_234
#   077L
#
# A single zero is handled by the decimal expression.
_OCTAL_INTEGER_RE = re.compile(
    r"""
    0
    [0-7](?:_?[0-7])*
    (?P<suffix>[lL])?
    """,
    re.VERBOSE,
)


# Decimal floating-point literals.
#
# Supported Java forms include:
#   1.0
#   .5
#   5.
#   1e10
#   1.0e-10
#   1f
#   1D
#   1_000.25
_DECIMAL_FLOAT_RE = re.compile(
    r"""
    (?:
        # Digits followed by a decimal point, optional fractional digits,
        # and optional exponent.
        [0-9](?:_?[0-9])*
        \.
        (?:[0-9](?:_?[0-9])*)?
        (?:[eE][+-]?[0-9](?:_?[0-9])*)?

        |

        # Decimal point followed by required fractional digits and an
        # optional exponent.
        \.
        [0-9](?:_?[0-9])*
        (?:[eE][+-]?[0-9](?:_?[0-9])*)?

        |

        # Digits followed by a required exponent.
        [0-9](?:_?[0-9])*
        [eE][+-]?
        [0-9](?:_?[0-9])*

        |

        # Integral-looking literal with a required floating suffix.
        [0-9](?:_?[0-9])*
    )
    (?P<suffix>[fFdD])?
    """,
    re.VERBOSE,
)


# Hexadecimal floating-point literals require a binary exponent in Java.
#
# Examples:
#   0x1.0p0
#   0x1p10
#   0xCAFE.p-2
#   0x1.ffffp127f
_HEXADECIMAL_FLOAT_RE = re.compile(
    r"""
    0[xX]
    (?:
        [0-9a-fA-F](?:_?[0-9a-fA-F])*
        (?:\.(?:[0-9a-fA-F](?:_?[0-9a-fA-F])*)?)?
        |
        \.
        [0-9a-fA-F](?:_?[0-9a-fA-F])*
    )
    [pP][+-]?
    [0-9](?:_?[0-9])*
    (?P<suffix>[fFdD])?
    """,
    re.VERBOSE,
)


_SIMPLE_ESCAPE_CHARACTERS = frozenset(
    {
        "b",
        "t",
        "n",
        "f",
        "r",
        '"',
        "'",
        "\\",
        "s",
    }
)


def _is_valid_java_escape(value: str) -> bool:
    """
    Determine whether ``value`` is one complete Java escape sequence.

    Supported forms:
        \\n
        \\t
        \\\\
        \\'
        \\"
        \\123
        \\u0041

    Unicode escapes with one or more ``u`` characters are accepted because
    Java permits forms such as ``\\uuuu0041``.
    """

    if len(value) < 2 or value[0] != "\\":
        return False

    escaped = value[1:]

    if escaped in _SIMPLE_ESCAPE_CHARACTERS:
        return True

    if re.fullmatch(r"[0-7]", escaped):
        return True

    if re.fullmatch(r"[0-7][0-7]", escaped):
        return True

    if re.fullmatch(r"[0-3][0-7][0-7]", escaped):
        return True

    if re.fullmatch(r"u+[0-9a-fA-F]{4}", escaped):
        return True

    return False


def _is_valid_char_literal(source: str) -> bool:
    """
    Validate a complete Java character literal.
    """

    if len(source) < 3:
        return False

    if not source.startswith("'") or not source.endswith("'"):
        return False

    content = source[1:-1]

    if not content:
        return False

    if content.startswith("\\"):
        return _is_valid_java_escape(content)

    return len(content) == 1 and content not in {"'", "\\", "\r", "\n"}


def _is_valid_string_content(content: str) -> bool:
    """
    Validate the contents of a Java string literal.

    This validator walks the source deterministically and ensures that every
    backslash begins a recognized Java escape sequence.
    """

    index = 0

    while index < len(content):
        character = content[index]

        if character in {"\r", "\n"}:
            return False

        if character == '"':
            return False

        if character != "\\":
            index += 1
            continue

        remaining = content[index:]

        unicode_match = re.match(r"\\u+[0-9a-fA-F]{4}", remaining)
        if unicode_match is not None:
            index += len(unicode_match.group(0))
            continue

        octal_match = re.match(r"\\[0-3][0-7][0-7]", remaining)
        if octal_match is not None:
            index += len(octal_match.group(0))
            continue

        octal_match = re.match(r"\\[0-7][0-7]?", remaining)
        if octal_match is not None:
            index += len(octal_match.group(0))
            continue

        if len(remaining) >= 2 and remaining[1] in _SIMPLE_ESCAPE_CHARACTERS:
            index += 2
            continue

        return False

    return True


def _is_valid_string_literal(source: str) -> bool:
    """
    Validate a complete traditional Java string literal.

    Java text blocks are intentionally outside the scope of this initial
    literal-inference milestone.
    """

    if len(source) < 2:
        return False

    if not source.startswith('"') or not source.endswith('"'):
        return False

    return _is_valid_string_content(source[1:-1])


def _numeric_result(
    source: str,
    match: re.Match[str],
    *,
    default_kind: LiteralKind,
) -> LiteralInferenceResult:
    """
    Build a numeric literal result from a successful regular-expression match.
    """

    suffix = match.groupdict().get("suffix")
    normalized = source.replace("_", "")

    if suffix in {"l", "L"}:
        kind = LiteralKind.LONG
    elif suffix in {"f", "F"}:
        kind = LiteralKind.FLOAT
    elif suffix in {"d", "D"}:
        kind = LiteralKind.DOUBLE
    else:
        kind = default_kind

    return LiteralInferenceResult(
        source=source,
        kind=kind,
        normalized=normalized,
        valid=True,
    )


def infer_java_literal(source: str) -> LiteralInferenceResult:
    """
    Infer the semantic category of one complete Java literal expression.

    The function is deterministic and side-effect free. It performs lexical
    classification only; it does not parse expressions and does not mutate a
    SemanticDocument.

    Args:
        source:
            Complete Java literal source text.

    Returns:
        An immutable ``LiteralInferenceResult``. Invalid or unsupported input
        produces ``LiteralKind.UNKNOWN`` rather than raising an exception.
    """

    if not isinstance(source, str):
        return LiteralInferenceResult.unknown(str(source))

    if source == "true" or source == "false":
        return LiteralInferenceResult(
            source=source,
            kind=LiteralKind.BOOLEAN,
            normalized=source,
            valid=True,
        )

    if source == "null":
        return LiteralInferenceResult(
            source=source,
            kind=LiteralKind.NULL,
            normalized=source,
            valid=True,
        )

    if _is_valid_char_literal(source):
        return LiteralInferenceResult(
            source=source,
            kind=LiteralKind.CHAR,
            normalized=source,
            valid=True,
        )

    if _is_valid_string_literal(source):
        return LiteralInferenceResult(
            source=source,
            kind=LiteralKind.STRING,
            normalized=source,
            valid=True,
        )

    match = _HEXADECIMAL_FLOAT_RE.fullmatch(source)
    if match is not None:
        return _numeric_result(
            source,
            match,
            default_kind=LiteralKind.DOUBLE,
        )

    match = _DECIMAL_FLOAT_RE.fullmatch(source)
    if match is not None:
        suffix = match.groupdict().get("suffix")

        # An integral-looking decimal such as "42" is not floating point
        # unless it includes a float or double suffix.
        if (
            "." not in source
            and "e" not in source.lower()
            and suffix not in {"f", "F", "d", "D"}
        ):
            match = None
        else:
            return _numeric_result(
                source,
                match,
                default_kind=LiteralKind.DOUBLE,
            )

    for pattern in (
        _HEXADECIMAL_INTEGER_RE,
        _BINARY_INTEGER_RE,
        _OCTAL_INTEGER_RE,
        _DECIMAL_INTEGER_RE,
    ):
        match = pattern.fullmatch(source)
        if match is not None:
            return _numeric_result(
                source,
                match,
                default_kind=LiteralKind.INT,
            )

    return LiteralInferenceResult.unknown(source)


__all__ = [
    "LiteralInferenceResult",
    "LiteralKind",
    "infer_java_literal",
]
