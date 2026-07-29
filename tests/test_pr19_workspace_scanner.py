from pathlib import Path

import pytest

from moughorai.java_workspace import BuildSystem, JavaWorkspaceScanner, SourceRootKind


def touch(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_discovers_maven_root(tmp_path: Path):
    touch(tmp_path / "pom.xml", "<project/>")
    catalog = JavaWorkspaceScanner().scan(tmp_path)
    assert len(catalog.modules) == 1
    assert catalog.modules[0].build_system is BuildSystem.MAVEN


def test_discovers_nested_maven_modules(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    touch(tmp_path / "api/pom.xml")
    touch(tmp_path / "service/pom.xml")
    catalog = JavaWorkspaceScanner().scan(tmp_path)
    assert [m.name for m in catalog.modules] == [tmp_path.name, "api", "service"]


def test_discovers_gradle_groovy(tmp_path: Path):
    touch(tmp_path / "build.gradle")
    assert JavaWorkspaceScanner().scan(tmp_path).modules[0].build_system is BuildSystem.GRADLE


def test_prefers_gradle_kotlin_descriptor(tmp_path: Path):
    touch(tmp_path / "build.gradle")
    touch(tmp_path / "build.gradle.kts")
    assert JavaWorkspaceScanner().scan(tmp_path).modules[0].descriptor.name == "build.gradle.kts"


def test_source_only_workspace_gets_unknown_module(tmp_path: Path):
    touch(tmp_path / "src/X.java")
    module = JavaWorkspaceScanner().scan(tmp_path).modules[0]
    assert module.build_system is BuildSystem.UNKNOWN
    assert module.root == tmp_path.resolve()


def test_detects_main_java_root(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    (tmp_path / "src/main/java").mkdir(parents=True)
    roots = JavaWorkspaceScanner().scan(tmp_path).modules[0].source_roots
    assert roots[0].kind is SourceRootKind.MAIN


def test_detects_test_java_root(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    (tmp_path / "src/test/java").mkdir(parents=True)
    roots = JavaWorkspaceScanner().scan(tmp_path).modules[0].source_roots
    assert roots[0].kind is SourceRootKind.TEST


def test_detects_resources(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    (tmp_path / "src/main/resources").mkdir(parents=True)
    roots = JavaWorkspaceScanner().scan(tmp_path).modules[0].source_roots
    assert roots[0].kind is SourceRootKind.RESOURCE


def test_detects_kotlin_source_root(tmp_path: Path):
    touch(tmp_path / "build.gradle.kts")
    (tmp_path / "src/main/kotlin").mkdir(parents=True)
    assert JavaWorkspaceScanner().scan(tmp_path).modules[0].source_roots[0].language == "kotlin"


def test_detects_jar_libraries(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    touch(tmp_path / "lib/a.jar", "binary")
    touch(tmp_path / "lib/readme.txt")
    libraries = JavaWorkspaceScanner().scan(tmp_path).modules[0].libraries
    assert [item.path.name for item in libraries] == ["a.jar"]


def test_detects_war_and_ear_libraries(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    touch(tmp_path / "libs/a.war")
    touch(tmp_path / "libs/b.ear")
    assert [x.path.name for x in JavaWorkspaceScanner().scan(tmp_path).modules[0].libraries] == ["a.war", "b.ear"]


def test_ignores_target_modules(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    touch(tmp_path / "target/generated/pom.xml")
    assert len(JavaWorkspaceScanner().scan(tmp_path).modules) == 1


def test_ignores_build_modules(tmp_path: Path):
    touch(tmp_path / "pom.xml")
    touch(tmp_path / "build/copied/pom.xml")
    assert len(JavaWorkspaceScanner().scan(tmp_path).modules) == 1


def test_ignores_git_content(tmp_path: Path):
    touch(tmp_path / ".git/pom.xml")
    assert JavaWorkspaceScanner().scan(tmp_path).modules[0].build_system is BuildSystem.UNKNOWN


def test_scan_is_deterministic(tmp_path: Path):
    touch(tmp_path / "z/pom.xml")
    touch(tmp_path / "a/pom.xml")
    first = JavaWorkspaceScanner().scan(tmp_path)
    second = JavaWorkspaceScanner().scan(tmp_path)
    assert first == second


def test_rejects_missing_root(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        JavaWorkspaceScanner().scan(tmp_path / "missing")


def test_rejects_file_root(tmp_path: Path):
    file = tmp_path / "x"
    file.write_text("x")
    with pytest.raises(NotADirectoryError):
        JavaWorkspaceScanner().scan(file)
