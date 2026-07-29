from pathlib import Path

import pytest

from moughorai.java_analysis.models import JavaSourceSet, JavaTypeKind
from moughorai.java_analysis.parser import (
    JavaSourceParseError,
    JavaSourceParser,
)


def write_java(tmp_path: Path, relative: str, content: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_package_import_annotations_and_primary_type(tmp_path: Path) -> None:
    path = write_java(
        tmp_path,
        "src/main/java/com/demo/UserService.java",
        """
        package com.demo;
        import java.util.List;
        import static java.util.Collections.emptyList;
        @Deprecated
        public final class UserService {}
        """,
    )
    source = JavaSourceParser().parse(path)
    assert source.package_name == "com.demo"
    assert source.source_set is JavaSourceSet.MAIN
    assert source.qualified_primary_name == "com.demo.UserService"
    assert len(source.imports) == 2
    assert any(item.is_static for item in source.imports)
    assert source.primary_type is not None
    assert source.primary_type.annotations[0].simple_name == "Deprecated"


def test_all_top_level_type_kinds(tmp_path: Path) -> None:
    path = write_java(
        tmp_path,
        "Types.java",
        "class A {} interface B {} enum C { VALUE } "
        "record D(String value) {} @interface E {}",
    )
    source = JavaSourceParser().parse(path)
    assert [item.kind for item in source.types] == [
        JavaTypeKind.CLASS,
        JavaTypeKind.INTERFACE,
        JavaTypeKind.ENUM,
        JavaTypeKind.RECORD,
        JavaTypeKind.ANNOTATION,
    ]


def test_nested_types_are_excluded(tmp_path: Path) -> None:
    path = write_java(
        tmp_path,
        "Outer.java",
        "public class Outer { static class Nested {} }",
    )
    assert [
        item.name for item in JavaSourceParser().parse(path).types
    ] == ["Outer"]


def test_comments_and_literals_are_ignored(tmp_path: Path) -> None:
    path = write_java(
        tmp_path,
        "Real.java",
        '// package fake;\n/* import fake.Type; */\n'
        'package real.pkg; public class Real {'
        'String text = "class Fake {}"; char brace = \'}\'; }',
    )
    source = JavaSourceParser().parse(path)
    assert source.package_name == "real.pkg"
    assert source.imports == ()
    assert [item.name for item in source.types] == ["Real"]


def test_imports_are_deduplicated_and_sorted(tmp_path: Path) -> None:
    path = write_java(
        tmp_path,
        "Imports.java",
        "import zeta.Type; import alpha.Type; import zeta.Type; "
        "class Imports {}",
    )
    source = JavaSourceParser().parse(path)
    assert [item.qualified_name for item in source.imports] == [
        "alpha.Type",
        "zeta.Type",
    ]


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("src/main/java/A.java", JavaSourceSet.MAIN),
        ("src/test/java/A.java", JavaSourceSet.TEST),
        (
            "target/generated-sources/annotations/A.java",
            JavaSourceSet.GENERATED,
        ),
        ("other/A.java", JavaSourceSet.UNKNOWN),
    ],
)
def test_source_set_classification(
    relative: str,
    expected: JavaSourceSet,
) -> None:
    assert JavaSourceParser.classify_source_set(Path(relative)) is expected


def test_parse_many_is_deterministic(tmp_path: Path) -> None:
    second = write_java(tmp_path, "z/Z.java", "class Z {}")
    first = write_java(tmp_path, "a/A.java", "class A {}")
    assert [
        source.path
        for source in JavaSourceParser().parse_many([second, first])
    ] == [first, second]


def test_missing_file_raises_safe_error(tmp_path: Path) -> None:
    with pytest.raises(JavaSourceParseError, match="does not exist"):
        JavaSourceParser().parse(tmp_path / "Missing.java")
