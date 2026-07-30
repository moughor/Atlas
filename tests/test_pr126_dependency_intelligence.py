from pathlib import Path

from typer.testing import CliRunner

from moughorai.ai_context import AnalyzerRegistry, decode_analysis_result, encode_analysis_result
from moughorai.atlas_cli import app
from moughorai.dependency_intelligence import DependencyIntelligenceService
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import Project, WorkspaceService


runner = CliRunner()


def _manifests(root: Path) -> None:
    (root / "pom.xml").write_text(
        "<project><dependencies><dependency><groupId>org.demo</groupId>"
        "<artifactId>core</artifactId><version>1.2</version></dependency>"
        "</dependencies></project>",
        encoding="utf-8",
    )
    (root / "build.gradle.kts").write_text(
        'implementation("org.demo:gradle-lib:2.0")\n',
        encoding="utf-8",
    )
    (root / "requirements.txt").write_text(
        "requests==2.32\n# ignored\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[tool.poetry.dependencies]\npython = "^3.12"\nhttpx = "^0.27"\n',
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        '{"dependencies":{"react":"^19"},"devDependencies":{"vitest":"^2"}}',
        encoding="utf-8",
    )
    (root / "Cargo.toml").write_text(
        '[dependencies]\nserde = { version = "1", optional = true }\n',
        encoding="utf-8",
    )


def test_all_required_manifest_ecosystems_are_normalized(tmp_path: Path) -> None:
    _manifests(tmp_path)
    dependencies = DependencyIntelligenceService().analyze(
        tmp_path, tuple(sorted(tmp_path.iterdir())),
    )
    values = {(item.ecosystem, item.name, item.version, item.scope) for item in dependencies}
    assert ("maven", "org.demo:core", "1.2", "compile") in values
    assert ("gradle", "org.demo:gradle-lib", "2.0", "implementation") in values
    assert ("pypi", "requests", "==2.32", "runtime") in values
    assert ("pypi", "httpx", "^0.27", "runtime") in values
    assert ("npm", "react", "^19", "runtime") in values
    assert ("npm", "vitest", "^2", "development") in values
    assert ("cargo", "serde", "1", "runtime") in values


def test_manifest_intelligence_is_published_in_snapshot(tmp_path: Path) -> None:
    _manifests(tmp_path)
    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert result.exit_code == 0
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    dependencies = snapshot.semantic_context["dependencies"]
    assert {item["ecosystem"] for item in dependencies} == {
        "cargo", "gradle", "maven", "npm", "pypi",
    }
    assert dependencies == sorted(
        dependencies,
        key=lambda item: (
            item["ecosystem"], item["name"], item["version"] or "",
            item["scope"], item["source"], item["optional"],
        ),
    )


def test_declared_dependencies_survive_recovery_encoding(tmp_path: Path) -> None:
    _manifests(tmp_path)
    document = AnalyzerRegistry()(Project("demo", tmp_path), {})
    restored = decode_analysis_result(encode_analysis_result(document))
    assert restored.get_artifact("declared_dependencies") == document.get_artifact(
        "declared_dependencies"
    )


def test_invalid_manifests_do_not_abort_semantic_analysis(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{invalid", encoding="utf-8")
    document = AnalyzerRegistry()(Project("demo", tmp_path), {})
    assert document.get_artifact("declared_dependencies") == ()
