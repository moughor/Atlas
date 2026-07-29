from __future__ import annotations
from .diagnostics import DiagnosticBag
from .lexer import JavaLexer
from .token_stream import TokenStream
from .tokens import TokenKind
from .source import SourceSpan
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

_PRECEDENCE = {
    TokenKind.EQ: 1, TokenKind.PLUS_EQ: 1, TokenKind.MINUS_EQ: 1,
    TokenKind.STAR_EQ: 1, TokenKind.SLASH_EQ: 1, TokenKind.PERCENT_EQ: 1,
    TokenKind.QUESTION: 2,
    TokenKind.PIPE_PIPE: 3,
    TokenKind.AMP_AMP: 4,
    TokenKind.PIPE: 5,
    TokenKind.CARET: 6,
    TokenKind.AMP: 7,
    TokenKind.EQ_EQ: 8, TokenKind.BANG_EQ: 8,
    TokenKind.LT: 9, TokenKind.LT_EQ: 9, TokenKind.GT: 9, TokenKind.GT_EQ: 9,
    TokenKind.PLUS: 10, TokenKind.MINUS: 10,
    TokenKind.STAR: 11, TokenKind.SLASH: 11, TokenKind.PERCENT: 11,
}
_ASSIGNMENTS = {
    TokenKind.EQ, TokenKind.PLUS_EQ, TokenKind.MINUS_EQ,
    TokenKind.STAR_EQ, TokenKind.SLASH_EQ, TokenKind.PERCENT_EQ,
}
_PREFIX = {
    TokenKind.PLUS, TokenKind.MINUS, TokenKind.BANG, TokenKind.TILDE,
    TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS,
}

def _join_span(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return SourceSpan(left.start, right.end, left.line, left.column)

class JavaSemanticParser:
    def __init__(self, source: str, diagnostics: DiagnosticBag | None = None):
        self.source = source
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()
        self.stream = TokenStream(JavaLexer().tokenize(source, self.diagnostics), self.diagnostics)

    @classmethod
    def parse_expression_text(cls, source: str):
        parser = cls(source)
        return parser.parse_expression(), parser.diagnostics.snapshot()

    @classmethod
    def parse_block_text(cls, source: str):
        parser = cls(source)
        return parser.parse_block(), parser.diagnostics.snapshot()

    def parse_expression(self, minimum_precedence: int = 0) -> JavaExpression:
        left = self._parse_prefix()

        while True:
            token = self.stream.peek()

            if token.kind in (TokenKind.DOT, TokenKind.LPAREN, TokenKind.LBRACKET,
                              TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
                left = self._parse_postfix(left)
                continue

            precedence = _PRECEDENCE.get(token.kind, 0)
            if precedence <= minimum_precedence:
                break

            operator = self.stream.advance()

            if operator.kind == TokenKind.QUESTION:
                when_true = self.parse_expression()
                self.stream.expect(TokenKind.COLON)
                when_false = self.parse_expression(precedence - 1)
                left = ConditionalExpression(
                    span=_join_span(left.span, when_false.span),
                    condition=left, when_true=when_true, when_false=when_false,
                )
                continue

            right_min = precedence - 1 if operator.kind in _ASSIGNMENTS else precedence
            right = self.parse_expression(right_min)
            if operator.kind in _ASSIGNMENTS:
                left = AssignmentExpression(
                    span=_join_span(left.span, right.span),
                    target=left, operator=operator.text, value=right,
                )
            else:
                left = BinaryExpression(
                    span=_join_span(left.span, right.span),
                    left=left, operator=operator.text, right=right,
                )
        return left

    def _parse_prefix(self) -> JavaExpression:
        token = self.stream.advance()
        kind = token.kind

        if kind == TokenKind.NUMBER:
            return LiteralExpression(token.span, self._number_value(token.text), "number", token.text)
        if kind == TokenKind.STRING:
            return LiteralExpression(token.span, self._decode_string(token.text), "string", token.text)
        if kind == TokenKind.CHARACTER:
            value = self._decode_string(token.text)
            return LiteralExpression(token.span, value, "character", token.text)
        if kind == TokenKind.TRUE:
            return LiteralExpression(token.span, True, "boolean", token.text)
        if kind == TokenKind.FALSE:
            return LiteralExpression(token.span, False, "boolean", token.text)
        if kind == TokenKind.NULL:
            return LiteralExpression(token.span, None, "null", token.text)
        if kind == TokenKind.IDENTIFIER or kind == TokenKind.VAR:
            return UnresolvedNameExpression(token.span, token.text)
        if kind == TokenKind.THIS:
            return ThisExpression(token.span)
        if kind == TokenKind.SUPER:
            return SuperExpression(token.span)
        if kind in _PREFIX:
            operand = self.parse_expression(12)
            return UnaryExpression(_join_span(token.span, operand.span), token.text, operand, False)
        if kind == TokenKind.NEW:
            type_token = self.stream.expect(TokenKind.IDENTIFIER)
            self.stream.expect(TokenKind.LPAREN)
            args = self._parse_arguments()
            end = self.stream.expect(TokenKind.RPAREN)
            return ObjectCreationExpression(_join_span(token.span, end.span), type_token.text, args)
        if kind == TokenKind.LPAREN:
            mark = self.stream.mark()
            possible_type = self.stream.peek()
            after_close = self.stream.peek(2)
            looks_like_type = (
                possible_type.kind == TokenKind.IDENTIFIER
                and self.stream.peek(1).kind == TokenKind.RPAREN
                and after_close.kind not in (TokenKind.EOF, TokenKind.SEMICOLON, TokenKind.RPAREN)
                and (possible_type.text[:1].isupper() or possible_type.text in {"int", "long", "double", "float", "boolean", "char", "byte", "short"})
            )
            if looks_like_type:
                self.stream.advance()
                self.stream.advance()
                expression = self.parse_expression(12)
                return CastExpression(_join_span(token.span, expression.span), possible_type.text, expression)
            self.stream.reset(mark)
            expression = self.parse_expression()
            end = self.stream.expect(TokenKind.RPAREN)
            return ParenthesizedExpression(_join_span(token.span, end.span), expression)

        self.diagnostics.add("PARSE002", f"Unexpected token in expression: {token.kind.value}", span=token.span)
        return UnknownExpression(token.span, token.text)

    def _parse_postfix(self, left: JavaExpression) -> JavaExpression:
        token = self.stream.peek()
        if token.kind == TokenKind.DOT:
            self.stream.advance()
            name = self.stream.expect(TokenKind.IDENTIFIER)
            if self.stream.peek().kind == TokenKind.LPAREN:
                self.stream.advance()
                args = self._parse_arguments()
                end = self.stream.expect(TokenKind.RPAREN)
                return MethodCallExpression(_join_span(left.span, end.span), left, name.text, args)
            return FieldAccessExpression(_join_span(left.span, name.span), left, name.text)

        if token.kind == TokenKind.LPAREN:
            self.stream.advance()
            args = self._parse_arguments()
            end = self.stream.expect(TokenKind.RPAREN)
            if isinstance(left, UnresolvedNameExpression):
                return MethodCallExpression(_join_span(left.span, end.span), None, left.name, args)
            self.diagnostics.add("PARSE003", "Only names can be invoked directly", span=token.span)
            return MethodCallExpression(_join_span(left.span, end.span), left, "", args)

        if token.kind == TokenKind.LBRACKET:
            self.stream.advance()
            index = self.parse_expression()
            end = self.stream.expect(TokenKind.RBRACKET)
            return ArrayAccessExpression(_join_span(left.span, end.span), left, index)

        if token.kind in (TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS):
            op = self.stream.advance()
            return UnaryExpression(_join_span(left.span, op.span), op.text, left, True)

        return left

    def _parse_arguments(self) -> tuple[JavaExpression, ...]:
        args = []
        if self.stream.peek().kind == TokenKind.RPAREN:
            return ()
        while True:
            args.append(self.parse_expression())
            if not self.stream.match(TokenKind.COMMA):
                break
        return tuple(args)

    def parse_statement(self) -> JavaStatement:
        token = self.stream.peek()
        if token.kind == TokenKind.LBRACE:
            return self.parse_block()
        if token.kind == TokenKind.RETURN:
            start = self.stream.advance()
            expr = None if self.stream.peek().kind == TokenKind.SEMICOLON else self.parse_expression()
            end = self.stream.expect(TokenKind.SEMICOLON)
            return ReturnStatement(_join_span(start.span, end.span), expr)
        if token.kind == TokenKind.THROW:
            start = self.stream.advance()
            expr = self.parse_expression()
            end = self.stream.expect(TokenKind.SEMICOLON)
            return ThrowStatement(_join_span(start.span, end.span), expr)
        if token.kind == TokenKind.IF:
            start = self.stream.advance()
            self.stream.expect(TokenKind.LPAREN)
            cond = self.parse_expression()
            self.stream.expect(TokenKind.RPAREN)
            then_branch = self.parse_statement()
            else_branch = None
            if self.stream.match(TokenKind.ELSE):
                else_branch = self.parse_statement()
            end_span = else_branch.span if else_branch else then_branch.span
            return IfStatement(_join_span(start.span, end_span), cond, then_branch, else_branch)
        if token.kind == TokenKind.WHILE:
            start = self.stream.advance()
            self.stream.expect(TokenKind.LPAREN)
            cond = self.parse_expression()
            self.stream.expect(TokenKind.RPAREN)
            body = self.parse_statement()
            return WhileStatement(_join_span(start.span, body.span), cond, body)
        if token.kind == TokenKind.BREAK:
            start = self.stream.advance()
            end = self.stream.expect(TokenKind.SEMICOLON)
            return BreakStatement(_join_span(start.span, end.span))
        if token.kind == TokenKind.CONTINUE:
            start = self.stream.advance()
            end = self.stream.expect(TokenKind.SEMICOLON)
            return ContinueStatement(_join_span(start.span, end.span))

        declaration = self._try_parse_local_declaration()
        if declaration is not None:
            return declaration

        expression = self.parse_expression()
        end = self.stream.expect(TokenKind.SEMICOLON)
        return ExpressionStatement(_join_span(expression.span, end.span), expression)

    def _try_parse_local_declaration(self):
        mark = self.stream.mark()
        first = self.stream.peek()
        if first.kind not in (TokenKind.IDENTIFIER, TokenKind.VAR):
            return None
        second = self.stream.peek(1)
        if second.kind != TokenKind.IDENTIFIER:
            return None
        type_token = self.stream.advance()
        name_token = self.stream.advance()
        initializer = None
        if self.stream.match(TokenKind.EQ):
            initializer = self.parse_expression()
        if self.stream.peek().kind != TokenKind.SEMICOLON:
            self.stream.reset(mark)
            return None
        end = self.stream.advance()
        return LocalVariableDeclaration(
            _join_span(type_token.span, end.span),
            type_token.text, name_token.text, initializer,
        )

    def parse_block(self) -> BlockStatement:
        start = self.stream.expect(TokenKind.LBRACE)
        statements = []
        while not self.stream.at_end and self.stream.peek().kind != TokenKind.RBRACE:
            position = self.stream.position
            statements.append(self.parse_statement())
            if self.stream.position == position:
                self.stream.advance()
        end = self.stream.expect(TokenKind.RBRACE)
        return BlockStatement(_join_span(start.span, end.span), tuple(statements))

    @staticmethod
    def _number_value(text: str):
        normalized = text.replace("_", "")
        stripped = normalized.rstrip("lLfFdD")
        try:
            if any(c in stripped for c in ".eE"):
                return float(stripped)
            return int(stripped, 0)
        except ValueError:
            return text

    @staticmethod
    def _decode_string(text: str):
        if len(text) < 2:
            return text
        body = text[1:-1]
        try:
            return bytes(body, "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return body
