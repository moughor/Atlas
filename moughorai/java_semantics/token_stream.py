from __future__ import annotations
from .diagnostics import DiagnosticBag
from .tokens import Token, TokenKind

class TokenStream:
    def __init__(self, tokens: tuple[Token, ...], diagnostics: DiagnosticBag | None = None):
        if not tokens:
            raise ValueError("tokens cannot be empty")
        self.tokens = tokens
        self.position = 0
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.position + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        token = self.peek()
        if self.position < len(self.tokens) - 1:
            self.position += 1
        return token

    def match(self, *kinds: TokenKind) -> Token | None:
        if self.peek().kind in kinds:
            return self.advance()
        return None

    def expect(self, kind: TokenKind, code: str = "PARSE001") -> Token:
        token = self.peek()
        if token.kind == kind:
            return self.advance()
        self.diagnostics.add(code, f"Expected {kind.value}, found {token.kind.value}", span=token.span)
        return Token(kind, "", token.span)

    def mark(self) -> int:
        return self.position

    def reset(self, mark: int) -> None:
        if not 0 <= mark < len(self.tokens):
            raise ValueError("invalid mark")
        self.position = mark

    @property
    def at_end(self) -> bool:
        return self.peek().kind == TokenKind.EOF
