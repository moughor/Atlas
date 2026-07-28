import pytest

from moughorai.java_ast.ast_nodes import (
    AnnotationDeclaration,
    ClassDeclaration,
    EnumDeclaration,
    InterfaceDeclaration,
    RecordDeclaration,
)
from moughorai.java_ast.lexer import JavaLexer
from moughorai.java_ast.parser import JavaParseError, JavaParser


def parse(source: str):
    return JavaParser().parse_source(source)


def test_parser_returns_empty_unit() -> None:
    unit = JavaParser().parse(JavaLexer().tokenize(""))
    assert unit.package is None
    assert unit.imports == ()
    assert unit.types == ()


def test_parses_package() -> None:
    unit = parse("package com.example.demo;")
    assert unit.package is not None
    assert unit.package.name == "com.example.demo"


def test_parses_normal_static_and_wildcard_imports() -> None:
    unit = parse(
        """
        import java.util.List;
        import java.util.*;
        import static java.util.Collections.emptyList;
        """
    )
    assert unit.imports[0].name == "java.util.List"
    assert not unit.imports[0].is_static
    assert not unit.imports[0].is_wildcard
    assert unit.imports[1].name == "java.util"
    assert unit.imports[1].is_wildcard
    assert unit.imports[2].name == "java.util.Collections.emptyList"
    assert unit.imports[2].is_static


def test_parses_annotated_class_and_modifiers() -> None:
    unit = parse(
        """
        @Deprecated
        @org.example.Component(value = "demo")
        public final class Demo {}
        """
    )
    declaration = unit.types[0]
    assert isinstance(declaration, ClassDeclaration)
    assert declaration.name == "Demo"
    assert declaration.annotations == (
        "Deprecated",
        "org.example.Component",
    )
    assert declaration.modifiers == ("public", "final")


def test_parses_class_inheritance() -> None:
    unit = parse(
        "class Demo<T> extends Base<T> implements One, two.Three {}"
    )
    declaration = unit.types[0]
    assert declaration.extends == "Base<T>"
    assert declaration.implements == ("One", "two.Three")


def test_combines_interface_extends_as_parent_interfaces() -> None:
    unit = parse("public interface Demo extends One, Two<String> {}")
    declaration = unit.types[0]
    assert isinstance(declaration, InterfaceDeclaration)
    assert declaration.extends is None
    assert declaration.implements == ("One", "Two<String>")


def test_parses_enum() -> None:
    unit = parse("enum Status { READY, DONE }")
    assert isinstance(unit.types[0], EnumDeclaration)
    assert unit.types[0].name == "Status"


def test_parses_record_and_skips_components() -> None:
    unit = parse("public record User(String name, int age) implements Named {}")
    declaration = unit.types[0]
    assert isinstance(declaration, RecordDeclaration)
    assert declaration.name == "User"
    assert declaration.implements == ("Named",)


def test_parses_annotation_declaration() -> None:
    unit = parse("public @interface Audited { String value(); }")
    declaration = unit.types[0]
    assert isinstance(declaration, AnnotationDeclaration)
    assert declaration.name == "Audited"
    assert declaration.modifiers == ("public",)


def test_parses_sealed_permits_clause() -> None:
    unit = parse("sealed class Shape permits Circle, Rectangle {}")
    declaration = unit.types[0]
    assert declaration.permits == ("Circle", "Rectangle")


def test_parses_multiple_top_level_types() -> None:
    unit = parse("class First {} interface Second {}")
    assert tuple(item.name for item in unit.types) == ("First", "Second")


def test_nested_braces_do_not_end_type_early() -> None:
    unit = parse(
        "class First { void run() { if (true) { } } } class Second {}"
    )
    assert tuple(item.name for item in unit.types) == ("First", "Second")


def test_reports_missing_semicolon_with_location() -> None:
    with pytest.raises(JavaParseError, match="line 1"):
        parse("package demo class Example {}")


def test_parses_fields_methods_and_constructor() -> None:
    unit = JavaParser().parse_source("""
        package demo;
        public class UserService {
            @Inject
            private final UserRepository repository;

            public UserService(UserRepository repository) {
                this.repository = repository;
            }

            @Transactional
            public User find(long id) throws NotFoundException {
                return repository.find(id);
            }
        }
    """)
    decl = unit.types[0]
    assert decl.fields[0].name == "repository"
    assert decl.fields[0].type_name == "UserRepository"
    assert decl.fields[0].annotations == ("Inject",)
    assert decl.constructors[0].parameters[0].type_name == "UserRepository"
    assert decl.methods[0].name == "find"
    assert decl.methods[0].return_type == "User"
    assert decl.methods[0].throws == ("NotFoundException",)


def test_parses_generic_method_varargs_and_arrays() -> None:
    unit = JavaParser().parse_source("""
        class Tools {
            public static <T> java.util.List<T> collect(
                final T first,
                @Nullable T... rest
            );
            private byte[] payload;
        }
    """)
    decl = unit.types[0]
    method = decl.methods[0]
    assert method.type_parameters == "<T>"
    assert method.return_type == "java.util.List<T>"
    assert method.parameters[0].modifiers == ("final",)
    assert method.parameters[1].annotations == ("Nullable",)
    assert method.parameters[1].is_varargs
    assert decl.fields[0].type_name == "byte[]"


def test_parses_nested_types() -> None:
    unit = JavaParser().parse_source("""
        class Outer {
            private int value;
            static class Inner {
                void run() {}
            }
        }
    """)
    outer = unit.types[0]
    assert outer.fields[0].name == "value"
    assert outer.nested_types[0].name == "Inner"
    assert outer.nested_types[0].methods[0].name == "run"
