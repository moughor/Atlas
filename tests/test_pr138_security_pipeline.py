from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.ai_context.persistence import (
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.security_intelligence import (
    SecurityCategory,
    SecurityIntelligenceReport,
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SecurityProducerReport,
)
from moughorai.security_analysis import (
    Confidence,
    SecurityFinding,
    Severity,
    SourceLocation,
)
from moughorai.workspace import Project
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


def _write_java(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _analyze(
    root: Path,
    *paths: Path,
    analyzer: JavaLanguageAnalyzer | None = None,
):
    return (analyzer or JavaLanguageAnalyzer()).analyze(
        Project("demo", root),
        tuple(paths),
        {},
    )


def test_java_pipeline_reuses_one_source_read_and_publishes_source_free_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "password=supersecret123"
    source_path = _write_java(
        tmp_path / "src/main/java/demo/App.java",
        f'package demo; class App {{ String password = "{secret}"; }}',
    )
    original_read_text = Path.read_text
    reads: list[Path] = []

    def counted_read_text(path: Path, *args, **kwargs) -> str:
        if path.resolve() == source_path.resolve():
            reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    document = _analyze(tmp_path, source_path)
    report = document.get_artifact("security_producer_report")

    assert isinstance(report, SecurityProducerReport)
    assert reads == [source_path]
    assert report.project_id == "demo"
    assert report.language == "java"
    assert report.source_files == 1
    assert len(report.findings) == 1
    assert report.findings[0].location.path == "src/main/java/demo/App.java"
    serialized = json.dumps(report.to_dict(), sort_keys=True)
    assert secret not in serialized
    assert str(tmp_path) not in serialized


def test_positive_finding_survives_analysis_snapshot_and_reload(
    tmp_path: Path,
) -> None:
    project = tmp_path / "app"
    secret = "password=must-never-escape-138"
    _write_java(
        project / "src/main/java/demo/App.java",
        f'package demo; class App {{ String password = "{secret}"; }}',
    )
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: app\n    path: app\n",
        encoding="utf-8",
    )

    analyzed = CliRunner().invoke(
        app,
        ["analyze", str(tmp_path), "--no-recover"],
    )
    assert analyzed.exit_code == 0
    snapshot = SemanticSnapshotStore(
        WorkspaceService(tmp_path).workspace
    ).load()
    assert snapshot is not None
    assert "security_intelligence" in snapshot.semantic_context

    report = SecurityIntelligenceService.from_snapshot(snapshot).analyze(
        SecurityIntelligenceRequest(
            categories=(SecurityCategory.SECRETS,),
            limit=10,
        )
    )
    assert len(report.findings) == 1
    assert report.findings[0].category is SecurityCategory.SECRETS
    assert report.findings[0].project_id == "app"
    assert (
        SecurityIntelligenceReport.from_dict(report.to_dict()).to_dict()
        == report.to_dict()
    )
    serialized = report.to_json()
    assert secret not in serialized
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize(
    "body,expected",
    (
        (
            'String value = request.getParameter("q"); '
            "statement.executeQuery(value);",
            SecurityCategory.SQL_INJECTION,
        ),
        (
            'MessageDigest.getInstance("MD5");',
            SecurityCategory.WEAK_CRYPTOGRAPHY,
        ),
        (
            'String value = request.getParameter("file"); '
            "Files.readAllBytes(value);",
            SecurityCategory.PATH_TRAVERSAL,
        ),
        (
            'String value = request.getParameter("url"); '
            "URL.openConnection(value);",
            SecurityCategory.SSRF,
        ),
        (
            "Object value = request.getInputStream(); "
            "ObjectInputStream.readObject(value);",
            SecurityCategory.UNSAFE_DESERIALIZATION,
        ),
        (
            'String value = request.getParameter("class"); '
            "Class.forName(value);",
            SecurityCategory.UNSAFE_REFLECTION,
        ),
        (
            'String value = request.getParameter("cmd"); '
            "Runtime.getRuntime().exec(value);",
            SecurityCategory.GENERAL_TAINT,
        ),
    ),
)
def test_normal_java_pipeline_maps_supported_security_categories(
    tmp_path: Path,
    body: str,
    expected: SecurityCategory,
) -> None:
    source = _write_java(
        tmp_path / "src/main/java/demo/App.java",
        f"package demo; class App {{ void run() {{ {body} }} }}",
    )

    report = _analyze(tmp_path, source).require_artifact(
        "security_producer_report"
    )

    assert [item.category for item in report.findings] == [expected]


def test_java_security_analysis_is_isolated_per_selected_source(
    tmp_path: Path,
) -> None:
    source = _write_java(
        tmp_path / "src/main/java/demo/Source.java",
        "package demo; class Source { void run() { "
        'String value = request.getParameter("q"); } }',
    )
    sink = _write_java(
        tmp_path / "src/main/java/demo/Sink.java",
        "package demo; class Sink { void run() { "
        "statement.executeQuery(value); } }",
    )

    first = _analyze(tmp_path, source, sink).require_artifact(
        "security_producer_report"
    )
    second = _analyze(tmp_path, sink, source).require_artifact(
        "security_producer_report"
    )

    assert isinstance(first, SecurityProducerReport)
    assert first.source_files == 2
    assert first.findings == ()
    assert first.to_dict() == second.to_dict()


class _FailingSecurityAnalyzer:
    def analyze_source(self, source: str, path: str):
        raise RuntimeError("producer details must not escape")


def test_security_producer_failure_is_explicit_and_does_not_fail_java(
    tmp_path: Path,
) -> None:
    source = _write_java(
        tmp_path / "src/main/java/demo/App.java",
        "package demo; class App {}",
    )
    document = _analyze(
        tmp_path,
        source,
        analyzer=JavaLanguageAnalyzer(
            security_analyzer=_FailingSecurityAnalyzer(),
        ),
    )
    report = document.require_artifact("security_producer_report")

    assert isinstance(report, SecurityProducerReport)
    assert report.findings == ()
    assert report.source_files == 0
    assert report.warning_count == 1
    assert any(
        "failed for 1 selected source file" in item
        for item in report.limitations
    )
    assert "producer details must not escape" not in json.dumps(
        report.to_dict(),
        sort_keys=True,
    )
    assert any(
        symbol.qualified_name == "demo.App"
        for symbol in document.require_artifact("global_symbols")
    )


def test_security_producer_report_recovery_round_trip_is_exact_and_additive(
    tmp_path: Path,
) -> None:
    source = _write_java(
        tmp_path / "src/main/java/demo/App.java",
        "package demo; class App {}",
    )
    document = _analyze(tmp_path, source)

    encoded = encode_analysis_result(document)
    restored = decode_analysis_result(encoded)

    assert encode_analysis_result(restored) == encoded
    assert (
        restored.require_artifact("security_producer_report").to_dict()
        == document.require_artifact("security_producer_report").to_dict()
    )

    legacy = dict(encoded)
    legacy.pop("security_producer_report")
    restored_legacy = decode_analysis_result(legacy)
    assert restored_legacy.get_artifact("security_producer_report") is None
    assert encode_analysis_result(restored_legacy) == legacy

    malformed = dict(encoded)
    malformed["security_producer_report"] = []
    with pytest.raises(TypeError, match="must be an object"):
        decode_analysis_result(malformed)


class _MalformedSecurityAnalyzer:
    def analyze_source(self, source: str, path: str):
        return SimpleNamespace(findings=(object(),), warnings=())


def test_security_normalization_failure_is_isolated_from_java_semantics(
    tmp_path: Path,
) -> None:
    source = _write_java(
        tmp_path / "src/main/java/demo/App.java",
        "package demo; class App {}",
    )

    document = _analyze(
        tmp_path,
        source,
        analyzer=JavaLanguageAnalyzer(
            security_analyzer=_MalformedSecurityAnalyzer(),
        ),
    )
    report = document.require_artifact("security_producer_report")

    assert report.findings == ()
    assert report.warning_count == 1
    assert any("failed for 1 selected source file" in item for item in report.limitations)
    assert any(
        symbol.qualified_name == "demo.App"
        for symbol in document.require_artifact("global_symbols")
    )


def test_unreadable_selected_source_reduces_security_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = _write_java(
        tmp_path / "src/main/java/demo/App.java",
        "package demo; class App {}",
    )
    original = Path.read_text

    def unreadable(path: Path, *args, **kwargs):
        if path.resolve() == source.resolve():
            raise PermissionError("private operating-system detail")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)
    document = _analyze(tmp_path, source)
    report = document.require_artifact("security_producer_report")

    assert report.source_files == 0
    assert report.warning_count == 1
    assert any("could not be read" in item for item in report.limitations)
    assert "private operating-system detail" not in report.to_json()


class _NoisySecurityAnalyzer:
    def analyze_source(self, source: str, path: str):
        findings = tuple(
            SecurityFinding(
                "ATLAS-SQL-001",
                "SQL injection",
                "structured test finding",
                Severity.HIGH,
                Confidence.HIGH,
                "CWE-89",
                "A03:2021",
                SourceLocation(path, line),
            )
            for line in range(1, 3_001)
        )
        return SimpleNamespace(findings=findings, warnings=())


def test_normal_pipeline_bounds_findings_during_multi_file_accumulation(
    tmp_path: Path,
) -> None:
    first = _write_java(tmp_path / "src/main/java/demo/A.java", "class A {}")
    second = _write_java(tmp_path / "src/main/java/demo/B.java", "class B {}")

    document = _analyze(
        tmp_path,
        first,
        second,
        analyzer=JavaLanguageAnalyzer(
            security_analyzer=_NoisySecurityAnalyzer(),
        ),
    )
    report = document.require_artifact("security_producer_report")

    assert len(report.findings) == 4_096
    assert report.warning_count == 1
    assert any("omitted 1904" in item for item in report.limitations)


def test_gradle_isolated_source_sets_publish_partial_security_report(
    tmp_path: Path,
) -> None:
    (tmp_path / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    test_source = _write_java(
        tmp_path / "src/test/java/demo/Shared.java",
        "package demo; class Shared { int testOnly; }",
    )
    integration_source = _write_java(
        tmp_path / "src/integrationTest/java/demo/Shared.java",
        "package demo; class Shared { int integrationOnly; }",
    )

    document = _analyze(tmp_path, test_source, integration_source)
    report = document.require_artifact("security_producer_report")

    assert isinstance(report, SecurityProducerReport)
    assert report.source_files == 2
    assert report.findings == ()
    assert any(
        "Gradle source sets were analyzed independently" in item
        for item in report.limitations
    )
    assert any(
        diagnostic.code == "ATLAS-JAVA-SOURCE-SETS-PARTIAL"
        for diagnostic in document.diagnostics
    )
    assert document.get_artifact("java_architecture_graph") is None
