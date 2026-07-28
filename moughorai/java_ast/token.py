"""Immutable Java token model."""

from __future__ import annotations

from dataclasses import dataclass

from moughorai.java_ast.models import SourceSpan
from moughorai.java_ast.token_type import JavaTokenType


@dataclass(frozen=True)
class JavaToken:
    """One lexical token."""

    type: JavaTokenType
    lexeme: str
    span: SourceSpan

    @property
    def line(self) -> int:
        return self.span.start.line

    @property
    def column(self) -> int:
        return self.span.start.column
