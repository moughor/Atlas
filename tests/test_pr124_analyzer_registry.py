from dataclasses import dataclass, field
from pathlib import Path

import pytest

from moughorai.ai_context import AnalyzerRegistry, SemanticProjectAnalyzer
from moughorai.semantic import SemanticDocument
from moughorai.workspace import Project


@dataclass
class RecordingAnalyzer:
    language: str
    extensions: tuple[str, ...]
    calls: list[tuple[Path, ...]] = field(default_factory=list)

    def analyze(self, project, paths, dependencies):
        self.calls.append(paths)
        return SemanticDocument(
            self.language, "", tuple(path.name for path in paths),
        ).with_artifact(f"{self.language}_files", paths)


def test_default_registry_contains_java_and_python() -> None:
    registry = AnalyzerRegistry()
    assert tuple(item.language for item in registry.registrations()) == ("java", "python")
    assert registry.analyzer_for("Main.java").language == "java"
    assert registry.analyzer_for("app.PY").language == "python"
    assert registry.analyzer_for("README.md") is None


@pytest.mark.parametrize(
    ("language", "extension"),
    (
        ("kotlin", ".kt"),
        ("javascript", ".js"),
        ("typescript", ".ts"),
        ("rust", ".rs"),
        ("go", ".go"),
    ),
)
def test_plugin_language_is_routed_by_extension(
    tmp_path: Path, language: str, extension: str,
) -> None:
    source = tmp_path / f"sample{extension}"
    source.write_text("plugin source", encoding="utf-8")
    analyzer = RecordingAnalyzer(language, (extension,))
    registry = AnalyzerRegistry((analyzer,))
    document = registry(Project("demo", tmp_path), {})
    assert document.language == language
    assert analyzer.calls == [(source,)]
    assert document.get_artifact(f"{language}_files") == (source,)


def test_registry_merges_languages_in_registration_order(tmp_path: Path) -> None:
    (tmp_path / "app.ts").write_text("", encoding="utf-8")
    (tmp_path / "main.go").write_text("", encoding="utf-8")
    registry = AnalyzerRegistry((
        RecordingAnalyzer("typescript", ("ts",)),
        RecordingAnalyzer("go", ("go",)),
    ))
    document = registry(Project("mixed", tmp_path), {})
    assert document.language == "mixed"
    assert document.syntax_tree == ("main.go", "app.ts")


def test_duplicate_language_and_extension_are_rejected() -> None:
    registry = AnalyzerRegistry((RecordingAnalyzer("typescript", (".ts",)),))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(RecordingAnalyzer("typescript", (".tsx",)))
    with pytest.raises(ValueError, match="extension"):
        registry.register(RecordingAnalyzer("other", (".ts",)))


def test_legacy_semantic_project_analyzer_remains_registry() -> None:
    assert isinstance(SemanticProjectAnalyzer(), AnalyzerRegistry)
