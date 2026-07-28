import pytest
from moughorai.java_semantics import JavaLexer, TokenKind, DiagnosticBag

@pytest.mark.parametrize("source,kinds", [
    ("a+b", [TokenKind.IDENTIFIER, TokenKind.PLUS, TokenKind.IDENTIFIER, TokenKind.EOF]),
    ("true && false", [TokenKind.TRUE, TokenKind.AMP_AMP, TokenKind.FALSE, TokenKind.EOF]),
    ("x += 1", [TokenKind.IDENTIFIER, TokenKind.PLUS_EQ, TokenKind.NUMBER, TokenKind.EOF]),
    ("new User()", [TokenKind.NEW, TokenKind.IDENTIFIER, TokenKind.LPAREN, TokenKind.RPAREN, TokenKind.EOF]),
    ('"hello"', [TokenKind.STRING, TokenKind.EOF]),
    ("'a'", [TokenKind.CHARACTER, TokenKind.EOF]),
    ("if(x){}", [TokenKind.IF, TokenKind.LPAREN, TokenKind.IDENTIFIER, TokenKind.RPAREN, TokenKind.LBRACE, TokenKind.RBRACE, TokenKind.EOF]),
])
def test_token_sequences(source, kinds):
    assert [t.kind for t in JavaLexer().tokenize(source)] == kinds

def test_comments_are_ignored():
    tokens = JavaLexer().tokenize("a /* x */ + // y\n b")
    assert [t.text for t in tokens[:-1]] == ["a", "+", "b"]

def test_unterminated_literal_reports_diagnostic():
    bag = DiagnosticBag()
    JavaLexer().tokenize('"abc', bag)
    assert [d.code for d in bag] == ["LEX002"]

def test_positions_are_tracked():
    token = JavaLexer().tokenize("\n  value")[0]
    assert (token.span.line, token.span.column) == (2, 3)
