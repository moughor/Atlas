"""Java token categories."""

from __future__ import annotations

from enum import Enum


class JavaTokenType(str, Enum):
    IDENTIFIER = "identifier"
    KEYWORD = "keyword"

    INTEGER_LITERAL = "integer_literal"
    FLOAT_LITERAL = "float_literal"
    STRING_LITERAL = "string_literal"
    TEXT_BLOCK = "text_block"
    CHARACTER_LITERAL = "character_literal"
    BOOLEAN_LITERAL = "boolean_literal"
    NULL_LITERAL = "null_literal"

    LINE_COMMENT = "line_comment"
    BLOCK_COMMENT = "block_comment"
    JAVADOC_COMMENT = "javadoc_comment"
    WHITESPACE = "whitespace"

    AT = "@"
    DOT = "."
    COMMA = ","
    SEMICOLON = ";"
    COLON = ":"
    DOUBLE_COLON = "::"
    QUESTION = "?"
    ARROW = "->"
    ELLIPSIS = "..."

    LEFT_PAREN = "("
    RIGHT_PAREN = ")"
    LEFT_BRACE = "{"
    RIGHT_BRACE = "}"
    LEFT_BRACKET = "["
    RIGHT_BRACKET = "]"

    ASSIGN = "="
    EQUAL = "=="
    NOT_EQUAL = "!="
    LESS = "<"
    LESS_EQUAL = "<="
    GREATER = ">"
    GREATER_EQUAL = ">="

    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    PLUS_PLUS = "++"
    MINUS_MINUS = "--"

    AMPERSAND = "&"
    PIPE = "|"
    CARET = "^"
    TILDE = "~"
    BANG = "!"
    AND_AND = "&&"
    OR_OR = "||"

    LEFT_SHIFT = "<<"
    RIGHT_SHIFT = ">>"
    UNSIGNED_RIGHT_SHIFT = ">>>"

    PLUS_ASSIGN = "+="
    MINUS_ASSIGN = "-="
    STAR_ASSIGN = "*="
    SLASH_ASSIGN = "/="
    PERCENT_ASSIGN = "%="
    AMPERSAND_ASSIGN = "&="
    PIPE_ASSIGN = "|="
    CARET_ASSIGN = "^="
    LEFT_SHIFT_ASSIGN = "<<="
    RIGHT_SHIFT_ASSIGN = ">>="
    UNSIGNED_RIGHT_SHIFT_ASSIGN = ">>>="

    EOF = "eof"
