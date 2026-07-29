from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .source import SourceSpan

class TokenKind(str, Enum):
    EOF = "EOF"
    IDENTIFIER = "IDENTIFIER"
    NUMBER = "NUMBER"
    STRING = "STRING"
    CHARACTER = "CHARACTER"
    TRUE = "TRUE"
    FALSE = "FALSE"
    NULL = "NULL"
    VAR = "VAR"
    NEW = "NEW"
    THIS = "THIS"
    SUPER = "SUPER"
    RETURN = "RETURN"
    THROW = "THROW"
    IF = "IF"
    ELSE = "ELSE"
    WHILE = "WHILE"
    FOR = "FOR"
    BREAK = "BREAK"
    CONTINUE = "CONTINUE"

    LPAREN = "("
    RPAREN = ")"
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    COMMA = ","
    DOT = "."
    SEMICOLON = ";"
    QUESTION = "?"
    COLON = ":"

    PLUS = "+"
    MINUS = "-"
    STAR = "*"
    SLASH = "/"
    PERCENT = "%"
    BANG = "!"
    TILDE = "~"
    AMP = "&"
    PIPE = "|"
    CARET = "^"
    EQ = "="
    LT = "<"
    GT = ">"

    PLUS_PLUS = "++"
    MINUS_MINUS = "--"
    EQ_EQ = "=="
    BANG_EQ = "!="
    LT_EQ = "<="
    GT_EQ = ">="
    AMP_AMP = "&&"
    PIPE_PIPE = "||"
    PLUS_EQ = "+="
    MINUS_EQ = "-="
    STAR_EQ = "*="
    SLASH_EQ = "/="
    PERCENT_EQ = "%="
    ARROW = "->"

@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    span: SourceSpan
