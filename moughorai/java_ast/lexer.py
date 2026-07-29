"""Deterministic Java lexer with exact source locations."""

from __future__ import annotations

from dataclasses import dataclass

from moughorai.java_ast.models import SourceLocation, SourceSpan
from moughorai.java_ast.token import JavaToken
from moughorai.java_ast.token_type import JavaTokenType


class JavaLexError(ValueError):
    """Raised when Java source contains an unterminated token."""

    def __init__(
        self,
        message: str,
        location: SourceLocation,
    ) -> None:
        super().__init__(
            f"{message} at line {location.line}, "
            f"column {location.column}"
        )
        self.location = location


_JAVA_KEYWORDS = frozenset(
    {
        "abstract",
        "assert",
        "boolean",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "exports",
        "extends",
        "final",
        "finally",
        "float",
        "for",
        "goto",
        "if",
        "implements",
        "import",
        "instanceof",
        "int",
        "interface",
        "long",
        "module",
        "native",
        "new",
        "non-sealed",
        "open",
        "opens",
        "package",
        "permits",
        "private",
        "protected",
        "provides",
        "public",
        "record",
        "requires",
        "return",
        "sealed",
        "short",
        "static",
        "strictfp",
        "super",
        "switch",
        "synchronized",
        "this",
        "throw",
        "throws",
        "to",
        "transient",
        "transitive",
        "try",
        "uses",
        "var",
        "void",
        "volatile",
        "while",
        "with",
        "yield",
    }
)

_LITERAL_KEYWORDS = {
    "true": JavaTokenType.BOOLEAN_LITERAL,
    "false": JavaTokenType.BOOLEAN_LITERAL,
    "null": JavaTokenType.NULL_LITERAL,
}

_OPERATORS: tuple[tuple[str, JavaTokenType], ...] = (
    (">>>=", JavaTokenType.UNSIGNED_RIGHT_SHIFT_ASSIGN),
    ("...", JavaTokenType.ELLIPSIS),
    (">>>", JavaTokenType.UNSIGNED_RIGHT_SHIFT),
    ("<<=", JavaTokenType.LEFT_SHIFT_ASSIGN),
    (">>=", JavaTokenType.RIGHT_SHIFT_ASSIGN),
    ("::", JavaTokenType.DOUBLE_COLON),
    ("->", JavaTokenType.ARROW),
    ("==", JavaTokenType.EQUAL),
    ("!=", JavaTokenType.NOT_EQUAL),
    ("<=", JavaTokenType.LESS_EQUAL),
    (">=", JavaTokenType.GREATER_EQUAL),
    ("++", JavaTokenType.PLUS_PLUS),
    ("--", JavaTokenType.MINUS_MINUS),
    ("&&", JavaTokenType.AND_AND),
    ("||", JavaTokenType.OR_OR),
    ("<<", JavaTokenType.LEFT_SHIFT),
    (">>", JavaTokenType.RIGHT_SHIFT),
    ("+=", JavaTokenType.PLUS_ASSIGN),
    ("-=", JavaTokenType.MINUS_ASSIGN),
    ("*=", JavaTokenType.STAR_ASSIGN),
    ("/=", JavaTokenType.SLASH_ASSIGN),
    ("%=", JavaTokenType.PERCENT_ASSIGN),
    ("&=", JavaTokenType.AMPERSAND_ASSIGN),
    ("|=", JavaTokenType.PIPE_ASSIGN),
    ("^=", JavaTokenType.CARET_ASSIGN),
    ("@", JavaTokenType.AT),
    (".", JavaTokenType.DOT),
    (",", JavaTokenType.COMMA),
    (";", JavaTokenType.SEMICOLON),
    (":", JavaTokenType.COLON),
    ("?", JavaTokenType.QUESTION),
    ("(", JavaTokenType.LEFT_PAREN),
    (")", JavaTokenType.RIGHT_PAREN),
    ("{", JavaTokenType.LEFT_BRACE),
    ("}", JavaTokenType.RIGHT_BRACE),
    ("[", JavaTokenType.LEFT_BRACKET),
    ("]", JavaTokenType.RIGHT_BRACKET),
    ("=", JavaTokenType.ASSIGN),
    ("<", JavaTokenType.LESS),
    (">", JavaTokenType.GREATER),
    ("+", JavaTokenType.PLUS),
    ("-", JavaTokenType.MINUS),
    ("*", JavaTokenType.STAR),
    ("/", JavaTokenType.SLASH),
    ("%", JavaTokenType.PERCENT),
    ("&", JavaTokenType.AMPERSAND),
    ("|", JavaTokenType.PIPE),
    ("^", JavaTokenType.CARET),
    ("~", JavaTokenType.TILDE),
    ("!", JavaTokenType.BANG),
)


@dataclass
class _Cursor:
    source: str
    offset: int = 0
    line: int = 1
    column: int = 1

    @property
    def at_end(self) -> bool:
        return self.offset >= len(self.source)

    def location(self) -> SourceLocation:
        return SourceLocation(
            offset=self.offset,
            line=self.line,
            column=self.column,
        )

    def peek(self, distance: int = 0) -> str:
        position = self.offset + distance
        if position >= len(self.source):
            return ""
        return self.source[position]

    def startswith(self, value: str) -> bool:
        return self.source.startswith(value, self.offset)

    def advance(self) -> str:
        character = self.source[self.offset]
        self.offset += 1

        if character == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1

        return character


class JavaLexer:
    """Convert Java source text into an immutable token sequence."""

    def tokenize(
        self,
        source: str,
        *,
        include_trivia: bool = False,
    ) -> tuple[JavaToken, ...]:
        cursor = _Cursor(source=source)
        tokens: list[JavaToken] = []

        while not cursor.at_end:
            token = self._next_token(cursor)

            if include_trivia or token.type not in {
                JavaTokenType.WHITESPACE,
                JavaTokenType.LINE_COMMENT,
                JavaTokenType.BLOCK_COMMENT,
                JavaTokenType.JAVADOC_COMMENT,
            }:
                tokens.append(token)

        location = cursor.location()
        tokens.append(
            JavaToken(
                type=JavaTokenType.EOF,
                lexeme="",
                span=SourceSpan(location, location),
            )
        )
        return tuple(tokens)

    def _next_token(self, cursor: _Cursor) -> JavaToken:
        character = cursor.peek()

        if character.isspace():
            return self._consume_whitespace(cursor)

        if cursor.startswith("//"):
            return self._consume_line_comment(cursor)

        if cursor.startswith("/*"):
            return self._consume_block_comment(cursor)

        if cursor.startswith('"""'):
            return self._consume_text_block(cursor)

        if character == '"':
            return self._consume_quoted(
                cursor,
                quote='"',
                token_type=JavaTokenType.STRING_LITERAL,
                label="string literal",
            )

        if character == "'":
            return self._consume_quoted(
                cursor,
                quote="'",
                token_type=JavaTokenType.CHARACTER_LITERAL,
                label="character literal",
            )

        if self._is_identifier_start(character):
            return self._consume_identifier(cursor)

        if character.isdigit():
            return self._consume_number(cursor)

        for lexeme, token_type in _OPERATORS:
            if cursor.startswith(lexeme):
                return self._consume_fixed(
                    cursor,
                    lexeme,
                    token_type,
                )

        start = cursor.location()
        unknown = cursor.advance()
        raise JavaLexError(
            f"unexpected character {unknown!r}",
            start,
        )

    def _consume_whitespace(self, cursor: _Cursor) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset

        while not cursor.at_end and cursor.peek().isspace():
            cursor.advance()

        return self._token(
            cursor,
            start,
            start_offset,
            JavaTokenType.WHITESPACE,
        )

    def _consume_line_comment(self, cursor: _Cursor) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset

        while not cursor.at_end and cursor.peek() not in "\r\n":
            cursor.advance()

        return self._token(
            cursor,
            start,
            start_offset,
            JavaTokenType.LINE_COMMENT,
        )

    def _consume_block_comment(self, cursor: _Cursor) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset
        is_javadoc = cursor.startswith("/**")

        cursor.advance()
        cursor.advance()

        while not cursor.at_end and not cursor.startswith("*/"):
            cursor.advance()

        if cursor.at_end:
            raise JavaLexError("unterminated block comment", start)

        cursor.advance()
        cursor.advance()

        return self._token(
            cursor,
            start,
            start_offset,
            (
                JavaTokenType.JAVADOC_COMMENT
                if is_javadoc
                else JavaTokenType.BLOCK_COMMENT
            ),
        )

    def _consume_text_block(self, cursor: _Cursor) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset

        for _ in range(3):
            cursor.advance()

        while not cursor.at_end and not cursor.startswith('"""'):
            cursor.advance()

        if cursor.at_end:
            raise JavaLexError("unterminated text block", start)

        for _ in range(3):
            cursor.advance()

        return self._token(
            cursor,
            start,
            start_offset,
            JavaTokenType.TEXT_BLOCK,
        )

    def _consume_quoted(
        self,
        cursor: _Cursor,
        *,
        quote: str,
        token_type: JavaTokenType,
        label: str,
    ) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset
        cursor.advance()
        escaped = False

        while not cursor.at_end:
            character = cursor.advance()

            if escaped:
                escaped = False
                continue

            if character == "\\":
                escaped = True
                continue

            if character == quote:
                return self._token(
                    cursor,
                    start,
                    start_offset,
                    token_type,
                )

            if character in "\r\n":
                raise JavaLexError(f"unterminated {label}", start)

        raise JavaLexError(f"unterminated {label}", start)

    def _consume_identifier(self, cursor: _Cursor) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset

        while (
            not cursor.at_end
            and self._is_identifier_part(cursor.peek())
        ):
            cursor.advance()

        lexeme = cursor.source[start_offset:cursor.offset]

        if lexeme in _LITERAL_KEYWORDS:
            token_type = _LITERAL_KEYWORDS[lexeme]
        elif lexeme in _JAVA_KEYWORDS:
            token_type = JavaTokenType.KEYWORD
        else:
            token_type = JavaTokenType.IDENTIFIER

        return JavaToken(
            type=token_type,
            lexeme=lexeme,
            span=SourceSpan(start, cursor.location()),
        )

    def _consume_number(self, cursor: _Cursor) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset
        token_type = JavaTokenType.INTEGER_LITERAL

        while (
            not cursor.at_end
            and (
                cursor.peek().isalnum()
                or cursor.peek() in "._"
            )
        ):
            if cursor.peek() in ".eEpPfFdD":
                token_type = JavaTokenType.FLOAT_LITERAL
            cursor.advance()

        return self._token(
            cursor,
            start,
            start_offset,
            token_type,
        )

    def _consume_fixed(
        self,
        cursor: _Cursor,
        lexeme: str,
        token_type: JavaTokenType,
    ) -> JavaToken:
        start = cursor.location()
        start_offset = cursor.offset

        for _ in lexeme:
            cursor.advance()

        return self._token(
            cursor,
            start,
            start_offset,
            token_type,
        )

    @staticmethod
    def _token(
        cursor: _Cursor,
        start: SourceLocation,
        start_offset: int,
        token_type: JavaTokenType,
    ) -> JavaToken:
        return JavaToken(
            type=token_type,
            lexeme=cursor.source[start_offset:cursor.offset],
            span=SourceSpan(start, cursor.location()),
        )

    @staticmethod
    def _is_identifier_start(character: str) -> bool:
        return bool(character) and (
            character == "_"
            or character == "$"
            or character.isalpha()
        )

    @staticmethod
    def _is_identifier_part(character: str) -> bool:
        return bool(character) and (
            character == "_"
            or character == "$"
            or character.isalnum()
        )
