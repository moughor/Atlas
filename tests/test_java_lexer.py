import pytest

from moughorai.java_ast.lexer import JavaLexError, JavaLexer
from moughorai.java_ast.token_type import JavaTokenType


def significant(source: str):
    return JavaLexer().tokenize(source)


def test_lexer_tokenizes_package_and_class() -> None:
    tokens = significant(
        "package com.demo;\npublic class UserService {}"
    )

    assert [(token.type, token.lexeme) for token in tokens] == [
        (JavaTokenType.KEYWORD, "package"),
        (JavaTokenType.IDENTIFIER, "com"),
        (JavaTokenType.DOT, "."),
        (JavaTokenType.IDENTIFIER, "demo"),
        (JavaTokenType.SEMICOLON, ";"),
        (JavaTokenType.KEYWORD, "public"),
        (JavaTokenType.KEYWORD, "class"),
        (JavaTokenType.IDENTIFIER, "UserService"),
        (JavaTokenType.LEFT_BRACE, "{"),
        (JavaTokenType.RIGHT_BRACE, "}"),
        (JavaTokenType.EOF, ""),
    ]


def test_lexer_preserves_exact_locations() -> None:
    tokens = significant("class A {\n  int value;\n}")
    int_token = tokens[3]

    assert int_token.lexeme == "int"
    assert int_token.line == 2
    assert int_token.column == 3
    assert int_token.span.start.offset == 12


def test_lexer_can_include_trivia() -> None:
    tokens = JavaLexer().tokenize(
        "class A {} // comment\n",
        include_trivia=True,
    )

    types = [token.type for token in tokens]

    assert JavaTokenType.WHITESPACE in types
    assert JavaTokenType.LINE_COMMENT in types


def test_lexer_distinguishes_comment_types() -> None:
    tokens = JavaLexer().tokenize(
        "/** docs */ /* block */ // line\n",
        include_trivia=True,
    )

    assert [token.type for token in tokens if "comment" in token.type.value] == [
        JavaTokenType.JAVADOC_COMMENT,
        JavaTokenType.BLOCK_COMMENT,
        JavaTokenType.LINE_COMMENT,
    ]


def test_lexer_tokenizes_literals() -> None:
    tokens = significant(
        'true false null 42 3.14 "hello" \'x\''
    )

    assert [token.type for token in tokens[:-1]] == [
        JavaTokenType.BOOLEAN_LITERAL,
        JavaTokenType.BOOLEAN_LITERAL,
        JavaTokenType.NULL_LITERAL,
        JavaTokenType.INTEGER_LITERAL,
        JavaTokenType.FLOAT_LITERAL,
        JavaTokenType.STRING_LITERAL,
        JavaTokenType.CHARACTER_LITERAL,
    ]


def test_lexer_tokenizes_text_block() -> None:
    source = 'String sql = """\nselect * from dual\n""";'
    tokens = significant(source)

    assert any(
        token.type is JavaTokenType.TEXT_BLOCK
        for token in tokens
    )


def test_lexer_uses_longest_operator_match() -> None:
    tokens = significant(
        "a >>>= 1; b >>= 1; c -> d; Type::method;"
    )

    token_types = [token.type for token in tokens]

    assert JavaTokenType.UNSIGNED_RIGHT_SHIFT_ASSIGN in token_types
    assert JavaTokenType.RIGHT_SHIFT_ASSIGN in token_types
    assert JavaTokenType.ARROW in token_types
    assert JavaTokenType.DOUBLE_COLON in token_types


def test_lexer_supports_annotations_and_generics() -> None:
    tokens = significant(
        "@Service class A<T extends Base> {}"
    )

    assert [token.lexeme for token in tokens[:-1]] == [
        "@",
        "Service",
        "class",
        "A",
        "<",
        "T",
        "extends",
        "Base",
        ">",
        "{",
        "}",
    ]


def test_lexer_supports_java_module_keywords() -> None:
    tokens = significant(
        "open module com.demo { requires transitive java.sql; }"
    )

    assert all(
        token.type is JavaTokenType.KEYWORD
        for token in tokens
        if token.lexeme in {
            "open",
            "module",
            "requires",
            "transitive",
        }
    )


@pytest.mark.parametrize(
    "source",
    [
        '"unterminated',
        "'x",
        "/* missing",
        '"""missing',
    ],
)
def test_lexer_reports_unterminated_tokens(source: str) -> None:
    with pytest.raises(JavaLexError):
        significant(source)


def test_lexer_rejects_unknown_character() -> None:
    with pytest.raises(JavaLexError, match="unexpected character"):
        significant("class A { § }")


def test_eof_location_matches_source_end() -> None:
    source = "class A {}\n"
    eof = significant(source)[-1]

    assert eof.type is JavaTokenType.EOF
    assert eof.span.start.offset == len(source)
    assert eof.line == 2
    assert eof.column == 1
