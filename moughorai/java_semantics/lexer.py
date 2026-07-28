from __future__ import annotations
from .diagnostics import DiagnosticBag
from .source import SourceSpan
from .tokens import Token, TokenKind

_KEYWORDS = {
    "true": TokenKind.TRUE, "false": TokenKind.FALSE, "null": TokenKind.NULL,
    "var": TokenKind.VAR, "new": TokenKind.NEW, "this": TokenKind.THIS,
    "super": TokenKind.SUPER, "return": TokenKind.RETURN, "throw": TokenKind.THROW,
    "if": TokenKind.IF, "else": TokenKind.ELSE, "while": TokenKind.WHILE,
    "for": TokenKind.FOR, "break": TokenKind.BREAK, "continue": TokenKind.CONTINUE,
}

_MULTI = {
    "++": TokenKind.PLUS_PLUS, "--": TokenKind.MINUS_MINUS,
    "==": TokenKind.EQ_EQ, "!=": TokenKind.BANG_EQ,
    "<=": TokenKind.LT_EQ, ">=": TokenKind.GT_EQ,
    "&&": TokenKind.AMP_AMP, "||": TokenKind.PIPE_PIPE,
    "+=": TokenKind.PLUS_EQ, "-=": TokenKind.MINUS_EQ,
    "*=": TokenKind.STAR_EQ, "/=": TokenKind.SLASH_EQ,
    "%=": TokenKind.PERCENT_EQ, "->": TokenKind.ARROW,
}
_SINGLE = {kind.value: kind for kind in TokenKind if len(kind.value) == 1}

class JavaLexer:
    def tokenize(self, source: str, diagnostics: DiagnosticBag | None = None) -> tuple[Token, ...]:
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()
        tokens: list[Token] = []
        i, line, col = 0, 1, 1

        def span(start, end, sl, sc):
            return SourceSpan(start, end, sl, sc)

        while i < len(source):
            ch = source[i]
            if ch.isspace():
                if ch == "\n":
                    line, col = line + 1, 1
                else:
                    col += 1
                i += 1
                continue

            if source.startswith("//", i):
                while i < len(source) and source[i] != "\n":
                    i += 1
                    col += 1
                continue

            if source.startswith("/*", i):
                start, sl, sc = i, line, col
                i += 2
                col += 2
                while i < len(source) and not source.startswith("*/", i):
                    if source[i] == "\n":
                        line, col = line + 1, 1
                    else:
                        col += 1
                    i += 1
                if i >= len(source):
                    diagnostics.add("LEX001", "Unterminated block comment", span(start, i, sl, sc))
                    break
                i += 2
                col += 2
                continue

            start, sl, sc = i, line, col

            if ch.isalpha() or ch in "_$":
                i += 1
                col += 1
                while i < len(source) and (source[i].isalnum() or source[i] in "_$"):
                    i += 1
                    col += 1
                text = source[start:i]
                tokens.append(Token(_KEYWORDS.get(text, TokenKind.IDENTIFIER), text, span(start, i, sl, sc)))
                continue

            if ch.isdigit():
                i += 1
                col += 1
                while i < len(source) and (source[i].isalnum() or source[i] in "._"):
                    i += 1
                    col += 1
                tokens.append(Token(TokenKind.NUMBER, source[start:i], span(start, i, sl, sc)))
                continue

            if ch in {'"', "'"}:
                quote = ch
                i += 1
                col += 1
                escaped = False
                while i < len(source):
                    current = source[i]
                    if current == "\n" and quote == '"':
                        line, col = line + 1, 1
                    else:
                        col += 1
                    i += 1
                    if escaped:
                        escaped = False
                    elif current == "\\":
                        escaped = True
                    elif current == quote:
                        break
                else:
                    diagnostics.add("LEX002", "Unterminated literal", span(start, i, sl, sc))
                kind = TokenKind.STRING if quote == '"' else TokenKind.CHARACTER
                tokens.append(Token(kind, source[start:i], span(start, i, sl, sc)))
                continue

            two = source[i:i+2]
            if two in _MULTI:
                tokens.append(Token(_MULTI[two], two, span(i, i+2, sl, sc)))
                i += 2
                col += 2
                continue

            kind = _SINGLE.get(ch)
            if kind is not None:
                tokens.append(Token(kind, ch, span(i, i+1, sl, sc)))
                i += 1
                col += 1
                continue

            diagnostics.add("LEX003", f"Unexpected character: {ch}", span(i, i+1, sl, sc))
            i += 1
            col += 1

        tokens.append(Token(TokenKind.EOF, "", SourceSpan(len(source), len(source), line, col)))
        return tuple(tokens)
