from pathlib import Path

from moughorai.java_ast.parser import JavaParser
from moughorai.java_resolution import (
    JavaTypeResolver,
    JavaTypeResolutionService,
    ResolutionStatus,
)
from moughorai.java_symbols.service import JavaSymbolService


def build(sources: dict[str, str]):
    mapped = {Path(name): source for name, source in sources.items()}
    index = JavaSymbolService().index_sources(mapped)
    units = {name: JavaParser().parse_source(source) for name, source in sources.items()}
    return index, units


def test_resolves_explicit_import() -> None:
    index, units = build({
        "User.java": "package app.model; public class User {}",
        "Service.java": "package app.service; import app.model.User; public class Service { User user; }",
    })
    result = JavaTypeResolver(index).resolve("User", units["Service.java"])
    assert result.qualified_name == "app.model.User"


def test_resolves_same_package_type() -> None:
    index, units = build({
        "User.java": "package app; public class User {}",
        "Service.java": "package app; public class Service { User user; }",
    })
    assert JavaTypeResolver(index).resolve("User", units["Service.java"]).qualified_name == "app.User"


def test_resolves_wildcard_import() -> None:
    index, units = build({
        "User.java": "package app.model; public class User {}",
        "Service.java": "package app.service; import app.model.*; public class Service { User user; }",
    })
    assert JavaTypeResolver(index).resolve("User", units["Service.java"]).qualified_name == "app.model.User"


def test_reports_ambiguous_simple_name() -> None:
    index, units = build({
        "a/User.java": "package a; public class User {}",
        "b/User.java": "package b; public class User {}",
        "Service.java": "package app; public class Service { User user; }",
    })
    result = JavaTypeResolver(index).resolve("User", units["Service.java"])
    assert result.status is ResolutionStatus.AMBIGUOUS
    assert set(result.candidates) == {"a.User", "b.User"}


def test_primitive_and_array_are_normalized() -> None:
    index, units = build({"Service.java": "package app; public class Service {}"})
    result = JavaTypeResolver(index).resolve("int[]", units["Service.java"])
    assert result.status is ResolutionStatus.PRIMITIVE
    assert result.qualified_name == "int"


def test_unresolved_type_is_explicit() -> None:
    index, units = build({"Service.java": "package app; public class Service {}"})
    result = JavaTypeResolver(index).resolve("Missing", units["Service.java"])
    assert result.status is ResolutionStatus.UNRESOLVED


def test_service_collects_cross_file_member_references() -> None:
    index, units = build({
        "Repo.java": "package app.data; public interface Repo {}",
        "Service.java": "package app; import app.data.Repo; public class Service { private Repo repo; public Repo find(Repo input) { return input; } }",
    })
    refs = JavaTypeResolutionService(JavaTypeResolver(index)).resolve_unit(units["Service.java"])
    resolved = {(ref.role, ref.resolution.qualified_name) for ref in refs}
    assert ("field:repo", "app.data.Repo") in resolved
    assert ("method-return:find", "app.data.Repo") in resolved
    assert ("method-parameter:find:input", "app.data.Repo") in resolved
