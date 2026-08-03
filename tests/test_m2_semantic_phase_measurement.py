from __future__ import annotations

import json
from pathlib import Path

from moughorai.ai_context import (
    AnalyzerRegistry,
    SemanticContextCollector,
    encode_analysis_result,
)
from moughorai.measurement import (
    MeasurementConfig,
    MeasurementPhase,
    MeasurementSession,
)
from moughorai.semantic import SemanticDocument
from moughorai.workspace import (
    Project,
    WorkspaceAnalysisOrchestrator,
    WorkspaceService,
)


def test_language_and_dependency_measurements_are_semantically_inert(
    tmp_path: Path,
) -> None:
    source = "package example; public class Main {}"
    (tmp_path / "Main.java").write_text(source, encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: example\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pytest==9.0\n", encoding="utf-8")
    project = Project("example", tmp_path)

    baseline = AnalyzerRegistry()(project, {})
    session = MeasurementSession(MeasurementConfig(enabled=True))
    measured = AnalyzerRegistry(measurement=session)(project, {})

    assert encode_analysis_result(measured) == encode_analysis_result(baseline)
    phases = {sample.phase_id for sample in session.report().samples}
    assert {
        MeasurementPhase.FILESYSTEM_TRAVERSAL.value,
        MeasurementPhase.PATH_NORMALIZATION.value,
        MeasurementPhase.JAVA_PARSING.value,
        MeasurementPhase.SYMBOL_EXTRACTION.value,
        MeasurementPhase.ARCHITECTURE.value,
        MeasurementPhase.DEPENDENCY_INTELLIGENCE.value,
    }.issubset(phases)
    totals = session.report().filesystem.totals
    assert totals["content_reads"] >= 2
    assert totals["language_parses"] >= 1
    assert totals["descriptor_parses"] >= 1
    encoded_report = session.report().to_json()
    assert str(tmp_path) not in encoded_report
    assert source not in encoded_report


def test_semantic_collection_measures_each_direct_analysis_phase(
    tmp_path: Path,
) -> None:
    source = "package example; public class Main {}"
    (tmp_path / "Main.java").write_text(source, encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: example\n    path: .\n",
        encoding="utf-8",
    )
    session = MeasurementSession(MeasurementConfig(enabled=True))
    service = WorkspaceService(tmp_path, measurement=session)
    report = WorkspaceAnalysisOrchestrator(service).execute(
        AnalyzerRegistry(measurement=session)
    )

    collected = SemanticContextCollector(service, measurement=session).collect(report)

    phases = {sample.phase_id for sample in session.report().samples}
    assert {
        MeasurementPhase.REPOSITORY_INVENTORY.value,
        MeasurementPhase.REPOSITORY_SUMMARY.value,
        MeasurementPhase.KNOWLEDGE_GRAPH.value,
        MeasurementPhase.ARCHITECTURE.value,
        "design_patterns.analysis",
        MeasurementPhase.REACHABILITY.value,
        MeasurementPhase.RISK.value,
        MeasurementPhase.REPOSITORY_REPORT.value,
    }.issubset(phases)
    context_json = json.dumps(collected.context.to_dict(), sort_keys=True)
    assert source not in context_json
    assert "measurement_report" not in context_json
    assert "wall_time_ns" not in context_json


class _CustomAnalyzer:
    language = "c#"
    extensions = (".cs",)

    def analyze(self, project, paths, dependencies):
        return SemanticDocument(self.language, "", tuple(path.name for path in paths))


def test_custom_language_uses_portable_fallback_phase(tmp_path: Path) -> None:
    (tmp_path / "Program.cs").write_text("custom source", encoding="utf-8")
    session = MeasurementSession(MeasurementConfig(enabled=True))

    document = AnalyzerRegistry(
        (_CustomAnalyzer(),),
        measurement=session,
    )(Project("custom", tmp_path), {})

    assert document.language == "c#"
    assert "language.other.parsing" in {
        sample.phase_id for sample in session.report().samples
    }
