from pathlib import Path

from moughorai.java_analysis.models import (
    JavaImport,
    JavaSourceFile,
    JavaSourceSet,
    JavaTypeDeclaration,
    JavaTypeKind,
)


def test_source_file_primary_and_qualified_name() -> None:
    helper = JavaTypeDeclaration(
        name="Helper",
        kind=JavaTypeKind.CLASS,
    )
    primary = JavaTypeDeclaration(
        name="UserService",
        kind=JavaTypeKind.CLASS,
        modifiers=("public",),
    )
    source = JavaSourceFile(
        path=Path("UserService.java"),
        package_name="com.demo.service",
        imports=(),
        types=(helper, primary),
        source_set=JavaSourceSet.MAIN,
    )

    assert source.primary_type == primary
    assert source.qualified_primary_name == (
        "com.demo.service.UserService"
    )
    assert primary.is_public


def test_import_package_name() -> None:
    assert JavaImport("java.util.List").package_name == "java.util"
    assert JavaImport(
        "java.util.*",
        is_wildcard=True,
    ).package_name == "java.util"


def test_single_segment_import_has_empty_package() -> None:
    assert JavaImport("Type").package_name == ""


def test_wildcard_import_keeps_full_package() -> None:
    assert JavaImport(
        "com.example.deep.package.*",
        is_wildcard=True,
    ).package_name == "com.example.deep.package"
