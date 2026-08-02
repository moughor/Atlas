from __future__ import annotations

import json
from pathlib import Path

import pytest

import moughorai.java_workspace.source_selection as source_selection_module
from moughorai.ai_context import AnalyzerRegistry, SemanticContextCollector
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.java_symbols import DuplicateTypeError
from moughorai.java_workspace.source_selection import (
    declared_java_resource_roots,
    declared_java_source_roots,
    select_compiled_java_sources,
)
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    WorkspaceDiscovery,
    WorkspaceRunReport,
    WorkspaceService,
)


def _java(path: Path, declaration: str, *, package: str = "demo") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"package {package}; " if package else ""
    path.write_text(f"{prefix}{declaration}\n", encoding="utf-8")
    return path


def _qualified_names(document) -> tuple[str, ...]:
    return tuple(
        symbol.qualified_name
        for symbol in document.get_artifact("global_symbols", ())
    )


@pytest.mark.parametrize("boundary", ("testData", "test-data"))
def test_parent_fixture_projects_stay_in_inventory_not_java_semantics(
    tmp_path: Path,
    boundary: str,
) -> None:
    real = _java(
        tmp_path / "src/main/java/demo/Real.java",
        "class Real {}",
    )
    fixture_paths = (
        _java(
            tmp_path / boundary / "first/src/Main.java",
            "class Main {}",
            package="",
        ),
        _java(
            tmp_path / boundary / "second/src/Main.java",
            "class Main {}",
            package="",
        ),
        _java(
            tmp_path / boundary / "Loose.java",
            "class Loose {}",
        ),
    )

    first = AnalyzerRegistry()(Project("parent", tmp_path), {})
    second = AnalyzerRegistry()(Project("parent", tmp_path), {})
    names = _qualified_names(first)

    assert first.metadata["files"] == 4
    assert names == _qualified_names(second)
    assert "demo.Real" in names
    assert "Main" not in names
    assert "demo.Loose" not in names
    assert all(
        symbol.source == real or symbol.source not in fixture_paths
        for symbol in first.get_artifact("global_symbols", ())
    )
    graph = first.get_artifact("java_architecture_graph")
    assert graph is not None
    assert {node.qualified_name for node in graph.nodes} == {"demo.Real"}


def test_gradle_fixture_corpus_is_excluded_but_custom_roots_remain(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle.kts").write_text(
        """sourceSets {
  test { java.srcDirs("test") }
  main { java.srcDirs("src") }
}
""",
        encoding="utf-8",
    )
    production = _java(tmp_path / "src/demo/Production.java", "class Production {}")
    test_source = _java(tmp_path / "test/demo/TestOnly.java", "class TestOnly {}")
    fixtures = (
        _java(
            tmp_path / "testData/manual/src/records/First.java",
            "class Anno {}",
            package="records",
        ),
        _java(
            tmp_path / "testData/manual/src/records/Second.java",
            "class Anno {}",
            package="records",
        ),
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("engine", tmp_path),
        (fixtures[1], test_source, fixtures[0], production),
        {},
    )
    names = set(_qualified_names(document))

    assert {"demo.Production", "demo.TestOnly"} <= names
    assert "records.Anno" not in names
    assert declared_java_source_roots(tmp_path) == (
        tmp_path / "src",
        tmp_path / "test",
    )


def test_literal_gradle_fixture_root_overrides_boundary_and_comments_do_not(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text(
        """def docs = /java.srcDirs("testData/string/src")/
sourceSets {
  main { java.srcDirs("testData/compiled/src") }
  // java.srcDirs("testData/ignored/src")
}
""",
        encoding="utf-8",
    )
    compiled = _java(
        tmp_path / "testData/compiled/src/demo/Compiled.java",
        "class Compiled {}",
    )
    ignored = _java(
        tmp_path / "testData/ignored/src/demo/Ignored.java",
        "class Ignored {}",
    )
    string_only = _java(
        tmp_path / "testData/string/src/demo/StringOnly.java",
        "class StringOnly {}",
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("custom", tmp_path),
        (ignored, string_only, compiled),
        {},
    )

    assert "demo.Compiled" in _qualified_names(document)
    assert "demo.Ignored" not in _qualified_names(document)
    assert "demo.StringOnly" not in _qualified_names(document)
    assert declared_java_source_roots(tmp_path) == (
        tmp_path / "testData/compiled/src",
    )


@pytest.mark.parametrize(
    "statement",
    (
        """println('java.srcDirs("testData/ignored/src")')""",
        """def docs = /java.srcDirs("testData/ignored/src")/""",
        """def docs = $/java.srcDirs("testData/ignored/src")/$""",
        """def docs = \"\"\"java.srcDirs('testData/ignored/src')\"\"\"""",
    ),
)
def test_gradle_string_content_is_not_source_root_evidence(
    tmp_path: Path,
    statement: str,
) -> None:
    (tmp_path / "build.gradle").write_text(
        f"{statement}\n",
        encoding="utf-8",
    )
    ignored = _java(
        tmp_path / "testData/ignored/src/demo/Ignored.java",
        "class Ignored {}",
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("custom", tmp_path),
        (ignored,),
        {},
    )

    assert "demo.Ignored" not in _qualified_names(document)
    assert declared_java_source_roots(tmp_path) == ()


def test_oversized_gradle_descriptor_cannot_reenable_fixture_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(source_selection_module, "_MAX_DESCRIPTOR_BYTES", 32)
    (tmp_path / "build.gradle").write_text(
        "java.srcDirs(\"testData/ignored/src\")\n" + (" " * 64),
        encoding="utf-8",
    )
    ignored = _java(
        tmp_path / "testData/ignored/src/demo/Ignored.java",
        "class Ignored {}",
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("custom", tmp_path),
        (ignored,),
        {},
    )

    assert "demo.Ignored" not in _qualified_names(document)
    assert declared_java_source_roots(tmp_path) == ()


def test_registered_intellij_source_root_overrides_fixture_boundary(
    tmp_path: Path,
) -> None:
    modules = tmp_path / ".idea" / "modules.xml"
    modules.parent.mkdir()
    modules.write_text(
        """<project version="4">
  <component name="ProjectModuleManager">
    <modules>
      <module filepath="$PROJECT_DIR$/tools/api/testData/real.iml" />
    </modules>
  </component>
</project>
""",
        encoding="utf-8",
    )
    registered_descriptor = tmp_path / "tools/api/testData/real.iml"
    registered_descriptor.parent.mkdir(parents=True)
    registered_descriptor.write_text(
        """<module type="JAVA_MODULE" version="4">
  <component name="NewModuleRootManager">
    <content url="file://$MODULE_DIR$">
      <sourceFolder url="file://$MODULE_DIR$/src" isTestSource="false" />
      <sourceFolder url="file://$MODULE_DIR$/resources" type="java-resource" />
    </content>
  </component>
</module>
""",
        encoding="utf-8",
    )
    registered = _java(
        registered_descriptor.parent / "src/demo/Registered.java",
        "class Registered {}",
    )
    unregistered_descriptor = tmp_path / "testData/case/local.iml"
    unregistered_descriptor.parent.mkdir(parents=True)
    unregistered_descriptor.write_text(
        """<module type="JAVA_MODULE" version="4">
  <component name="NewModuleRootManager">
    <content url="file://$MODULE_DIR$">
      <sourceFolder url="file://$MODULE_DIR$/src" isTestSource="false" />
    </content>
  </component>
</module>
""",
        encoding="utf-8",
    )
    unregistered = _java(
        unregistered_descriptor.parent / "src/demo/Unregistered.java",
        "class Unregistered {}",
    )
    resources = (
        _java(
            registered_descriptor.parent / "resources/first/Button.java",
            "class Button {}",
            package="",
        ),
        _java(
            registered_descriptor.parent / "resources/second/Button.java",
            "class Button {}",
            package="",
        ),
    )
    unclassified_projects = (
        _java(
            registered_descriptor.parent / "targetApp/src/Cat.java",
            "class Cat {}",
            package="",
        ),
        _java(
            registered_descriptor.parent / "otherTargetApp/src/Cat.java",
            "class Cat {}",
            package="",
        ),
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("idea", tmp_path),
        (
            unclassified_projects[1],
            resources[1],
            unregistered,
            resources[0],
            registered,
            unclassified_projects[0],
        ),
        {},
    )

    assert declared_java_source_roots(tmp_path) == (
        registered_descriptor.parent / "src",
    )
    assert declared_java_resource_roots(tmp_path) == (
        registered_descriptor.parent / "resources",
    )
    assert "demo.Registered" in _qualified_names(document)
    assert "demo.Unregistered" not in _qualified_names(document)
    assert "Button" not in _qualified_names(document)
    assert "Cat" not in _qualified_names(document)


def test_gradle_literal_and_conventional_resource_roots_are_not_compiled(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text(
        """sourceSets {
  main { resources.srcDirs("assets") }
}
""",
        encoding="utf-8",
    )
    production = _java(tmp_path / "src/demo/Production.java", "class Production {}")
    resources = (
        _java(
            tmp_path / "assets/first/Button.java",
            "class Button {}",
            package="",
        ),
        _java(
            tmp_path / "assets/second/Button.java",
            "class Button {}",
            package="",
        ),
        _java(
            tmp_path / "src/test/resources/first/Resource.java",
            "class Resource {}",
            package="",
        ),
        _java(
            tmp_path / "src/test/resources/second/Resource.java",
            "class Resource {}",
            package="",
        ),
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("demo", tmp_path),
        (*reversed(resources), production),
        {},
    )

    assert "demo.Production" in _qualified_names(document)
    assert "Button" not in _qualified_names(document)
    assert "Resource" not in _qualified_names(document)
    assert declared_java_resource_roots(tmp_path) == (tmp_path / "assets",)


def test_explicit_compiled_root_overrides_resource_like_directory_name(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text(
        """sourceSets {
  main { java.srcDirs("src/custom/resources") }
}
""",
        encoding="utf-8",
    )
    compiled = _java(
        tmp_path / "src/custom/resources/demo/Compiled.java",
        "class Compiled {}",
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("custom", tmp_path),
        (compiled,),
        {},
    )

    assert "demo.Compiled" in _qualified_names(document)


def test_more_specific_structured_resource_root_is_not_compiled(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text(
        """sourceSets {
  main {
    java.srcDirs("src")
    resources.srcDirs("src/main/resources")
  }
}
""",
        encoding="utf-8",
    )
    production = _java(
        tmp_path / "src/demo/Production.java",
        "class Production {}",
    )
    resource = _java(
        tmp_path / "src/main/resources/demo/Resource.java",
        "class Resource {}",
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("custom", tmp_path),
        (resource, production),
        {},
    )

    assert "demo.Production" in _qualified_names(document)
    assert "demo.Resource" not in _qualified_names(document)


def test_source_selection_rejects_paths_outside_project_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    inside = _java(
        project_root / "src/main/java/demo/Inside.java",
        "class Inside {}",
    )
    outside = _java(
        tmp_path / "outside/demo/Outside.java",
        "class Outside {}",
    )

    selected, excluded = select_compiled_java_sources(
        project_root,
        (outside, inside),
    )

    assert selected == (inside,)
    assert excluded == (outside,)


def test_internal_file_symlink_is_canonicalized_once(tmp_path: Path) -> None:
    source = _java(
        tmp_path / "src/main/java/demo/Real.java",
        "class Real {}",
    )
    alias = source.with_name("Alias.java")
    try:
        alias.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable on this platform: {exc}")

    selected, excluded = select_compiled_java_sources(
        tmp_path,
        (alias, source),
    )

    assert selected == (source,)
    assert excluded == ()


def test_nested_resource_like_package_is_not_a_resource_root(
    tmp_path: Path,
) -> None:
    source = _java(
        tmp_path / "src/main/java/example/src/test/resources/Real.java",
        "class Real {}",
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("demo", tmp_path),
        (source,),
        {},
    )

    assert "demo.Real" in _qualified_names(document)


def test_nested_conventional_resource_root_is_not_compiled(
    tmp_path: Path,
) -> None:
    resources = (
        _java(
            tmp_path / "first/src/main/resources/Button.java",
            "class Button {}",
            package="",
        ),
        _java(
            tmp_path / "second/src/main/resources/Button.java",
            "class Button {}",
            package="",
        ),
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("demo", tmp_path),
        resources,
        {},
    )

    assert "Button" not in _qualified_names(document)


def test_leading_src_name_alone_does_not_override_fixture_boundary(
    tmp_path: Path,
) -> None:
    fixtures = (
        _java(
            tmp_path / "src/testData/first/src/Main.java",
            "class Main {}",
            package="",
        ),
        _java(
            tmp_path / "src/testData/second/src/Main.java",
            "class Main {}",
            package="",
        ),
    )

    document = JavaLanguageAnalyzer().analyze(
        Project("demo", tmp_path),
        fixtures,
        {},
    )

    assert "Main" not in _qualified_names(document)


@pytest.mark.parametrize(
    "relative",
    (
        "src/test/java/demo/testData/Real.java",
        "src/testFixtures/java/demo/testData/Fixture.java",
        "src/jmh/java/demo/testData/Benchmark.java",
        "target/generated-sources/demo/testData/Generated.java",
    ),
)
def test_fixture_like_packages_after_recognized_roots_remain(
    tmp_path: Path,
    relative: str,
) -> None:
    source = _java(tmp_path / relative, "class Retained {}")

    document = JavaLanguageAnalyzer().analyze(
        Project("demo", tmp_path),
        (source,),
        {},
    )

    assert "demo.Retained" in _qualified_names(document)


def test_nested_fixture_project_keeps_independent_ownership(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    parent_source = _java(
        tmp_path / "src/main/java/demo/Shared.java",
        "class Shared {}",
    )
    child = tmp_path / "testData/library"
    (child / "pom.xml").parent.mkdir(parents=True)
    (child / "pom.xml").write_text("<project/>", encoding="utf-8")
    child_source = _java(
        child / "src/main/java/demo/Shared.java",
        "class Shared {}",
    )
    workspace = WorkspaceDiscovery().discover(tmp_path)
    parent = workspace.get(tmp_path.name)
    child_project = workspace.get("testData-library")

    parent_document = AnalyzerRegistry()(parent, {})
    child_document = AnalyzerRegistry()(child_project, {})

    assert parent.exclude == ("testData/library/**/*",)
    assert any(symbol.source == parent_source for symbol in parent_document.get_artifact(
        "global_symbols", ()
    ))
    assert any(symbol.source == child_source for symbol in child_document.get_artifact(
        "global_symbols", ()
    ))
    assert "demo.Shared" in _qualified_names(parent_document)
    assert "demo.Shared" in _qualified_names(child_document)


def test_genuine_duplicate_outside_fixture_data_still_raises(tmp_path: Path) -> None:
    first = _java(
        tmp_path / "src/main/java/one/Shared.java",
        "class Shared {}",
    )
    second = _java(
        tmp_path / "src/main/java/two/Shared.java",
        "class Shared {}",
    )

    with pytest.raises(DuplicateTypeError, match="demo.Shared"):
        JavaLanguageAnalyzer().analyze(
            Project("demo", tmp_path),
            (first, second),
            {},
        )


def test_semantic_context_fallback_uses_same_fixture_selection(
    tmp_path: Path,
) -> None:
    selected_root = tmp_path / "selected"
    selected_root.mkdir()
    (selected_root / "app.py").write_text("class App: pass\n", encoding="utf-8")
    unselected_root = tmp_path / "unselected"
    real = _java(
        unselected_root / "src/main/java/demo/Real.java",
        "class Real {}",
    )
    fixture_paths = (
        _java(
            unselected_root / "testData/first/src/Main.java",
            "class Main {}",
            package="",
        ),
        _java(
            unselected_root / "testData/second/src/Main.java",
            "class Main {}",
            package="",
        ),
    )
    (tmp_path / "atlas.yaml").write_text(
        """projects:
  - name: selected
    path: selected
  - name: unselected
    path: unselected
""",
        encoding="utf-8",
    )
    service = WorkspaceService(tmp_path)
    selected = AnalyzerRegistry()(service.project("selected"), {})
    report = WorkspaceRunReport(
        (ProjectRun("selected", ProjectRunStatus.SUCCEEDED, selected),),
        ("selected",),
        ("selected",),
    )

    context = SemanticContextCollector(service).collect(report).context.to_dict()
    java_symbols = [
        symbol
        for symbol in context["symbols"]
        if symbol.get("source") == real.as_posix()
        or symbol.get("qualified_name") in {"Main", "demo.Real"}
    ]
    summaries = {
        project["name"]: project
        for project in context["repository_summary"]["projects"]
    }

    assert any(symbol["qualified_name"] == "demo.Real" for symbol in java_symbols)
    assert not any(symbol["qualified_name"] == "Main" for symbol in java_symbols)
    assert all(symbol.get("source") not in {
        path.as_posix() for path in fixture_paths
    } for symbol in context["symbols"])
    assert summaries["unselected"]["inventoried_file_count"] == 3
    serialized = json.dumps(context, sort_keys=True)
    assert "class Main" not in serialized
    assert str(tmp_path) not in serialized
