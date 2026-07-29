from pathlib import Path

import pytest

from moughorai.java_ast.parser import JavaParser
from moughorai.java_symbols import (
    DuplicateTypeError,
    JavaSymbolIndexBuilder,
    JavaSymbolService,
    SymbolKind,
)


def parse(source: str):
    return JavaParser().parse_source(source)


def test_builds_fully_qualified_type_and_member_symbols() -> None:
    unit = parse("""
        package com.example;
        class UserService {
            private UserRepository repository;
            UserService(UserRepository repository) {}
            User find(long id) { return null; }
        }
    """)

    index = JavaSymbolIndexBuilder().build((unit,), (Path("UserService.java"),))

    assert index.type_by_name("com.example.UserService") is not None
    assert index.find("com.example.UserService.repository")[0].kind is SymbolKind.FIELD
    assert index.find("com.example.UserService#<init>(UserRepository)")
    assert index.find("com.example.UserService#find(long)")


def test_indexes_nested_types_with_enclosing_qualified_name() -> None:
    index = JavaSymbolIndexBuilder().build((parse("""
        package demo;
        class Outer { static class Inner { void run() {} } }
    """),))

    nested = index.type_by_name("demo.Outer.Inner")
    assert nested is not None
    assert nested.owner == "demo.Outer"
    assert index.find("demo.Outer.Inner#run()")


def test_simple_name_lookup_can_return_multiple_symbols() -> None:
    index = JavaSymbolIndexBuilder().build((
        parse("package first; class User {}"),
        parse("package second; class User {}"),
    ))

    assert len(index.find_simple("User")) == 2
    assert len(index.by_kind(SymbolKind.TYPE)) == 2


def test_duplicate_qualified_types_are_rejected() -> None:
    units = (
        parse("package demo; class User {}"),
        parse("package demo; class User {}"),
    )
    with pytest.raises(DuplicateTypeError, match="demo.User"):
        JavaSymbolIndexBuilder().build(units)


def test_service_parses_multiple_sources_and_preserves_paths() -> None:
    index = JavaSymbolService().index_sources({
        Path("src/A.java"): "package demo; class A {}",
        Path("src/B.java"): "package demo; class B { A value; }",
    })

    assert index.type_by_name("demo.A").source == Path("src/A.java")
    assert index.find("demo.B.value")[0].source == Path("src/B.java")
