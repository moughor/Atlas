"""Unified Atlas command-line interface introduced in PR75."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import tempfile
from threading import RLock
import tracemalloc
from typing import Annotated, Any

import typer

from .ci_templates import CiProvider, CiTemplateError, CiTemplateService
from .cli_output import OutputFormat, render_report
from .finding_baseline import FindingBaselineError, FindingBaselineService, FindingBaselineStore
from .plugin_sdk import PluginDiscovery
from .quality_gate import FindingSeverity, QualityGatePolicy, WorkspaceQualityGate
from .version import __version__
from .git_diff import GitDiffError, GitDiffFilter, GitDiffService
from .history import HistoryDatabase, HistoryDatabaseError
from .dashboard import DashboardService
from .profiling import PerformanceProfiler
from .measurement import (
    MeasurementConfig,
    MeasurementPhase,
    MeasurementReport,
    MeasurementSession,
    MetricStatus,
)
from .adaptive_scheduler import AdaptiveWorkspaceScheduler
from .governance import GovernanceAuditLog, GovernanceError
from .structured_logging import LogFormat, LogLevel, configure_logging, get_logger, log_event
from .semantic_snapshot import SemanticSnapshotError, SemanticSnapshotStore
from .knowledge_graph import KnowledgeKind, KnowledgeRelation
from .semantic_search import (
    SemanticSearchRequest,
    SemanticSearchService,
    render_semantic_search,
)
from .impact_analysis import (
    ImpactChangeKind,
    ImpactPredictionRequest,
    ImpactPredictionService,
    render_impact_prediction,
)
from .refactoring_advisor import (
    RefactoringAdvisorService,
    RefactoringFamily,
    RefactoringRequest,
    render_refactoring_advice,
)
from .subject_resolution import SubjectQuery
from .ai_explain import ExplainEngine, ExplainRequest
from .ai_memory import ConversationMemoryStore
from .ai_review import ReviewEngine, ReviewRequest
from .ai_ask import AskEngine, AskRequest
from .ai_patch import GitPatchValidator, PatchEngine, PatchRequest
from .ai_git_context import GitContextService
from .ai import ATLAS_AI_VERSION, atlas_ai_capabilities
from .ai_context import (
    AnalyzerRegistry,
    SemanticContextCollector,
    SemanticProjectAnalyzer,
    decode_analysis_result,
    encode_analysis_result,
)
from .llm import LlmClient, OllamaProvider
from .workspace import (
    Project,
    Workspace,
    WorkspaceAnalysisOrchestrator,
    WorkspaceConfigurationError,
    WorkspaceRecoveryManager,
    WorkspaceRunReport,
    WorkspaceService,
    WorkspaceStateError,
    WorkspaceWatchManager,
    WorkspaceWatcher,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Atlas {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="atlas",
    help="Atlas modular static-analysis platform.",
    no_args_is_help=True,
)
ai_app = typer.Typer(
    name="ai",
    help="Reason over verified Atlas semantic snapshots.",
    no_args_is_help=True,
)
app.add_typer(ai_app, name="ai")
_logger = get_logger("cli")


@app.callback()
def root_callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the Atlas version and exit."),
    ] = False,
    log_level: Annotated[LogLevel, typer.Option("--log-level", help="Atlas log level; off preserves silent defaults.")] = LogLevel.OFF,
    log_format: Annotated[LogFormat, typer.Option("--log-format", help="Log format: json or text.")] = LogFormat.JSON,
    log_file: Annotated[Path | None, typer.Option("--log-file", help="Write Atlas logs to this file.")] = None,
    correlation_id: Annotated[str | None, typer.Option("--correlation-id", help="Correlation ID for this invocation.")] = None,
) -> None:
    """Atlas modular static-analysis platform."""
    active = configure_logging(
        level=log_level,
        output_format=log_format,
        path=log_file,
        correlation_id=correlation_id,
    )
    if active is not None:
        log_event(_logger, logging.INFO, "cli.started", version=__version__)


@dataclass(frozen=True, slots=True)
class AtlasCliContext:
    root: Path
    service: WorkspaceService


Analyzer = Callable[[Project, Mapping[str, Any]], Any]
_analyzer_factory: Callable[[WorkspaceService], Analyzer] | None = None
_ai_provider_factory: Callable[[], Any] | None = None
_tracemalloc_lock = RLock()
_tracemalloc_users = 0
_tracemalloc_owned = False


def _default_analyzer(service: WorkspaceService) -> Analyzer:
    return AnalyzerRegistry(measurement=service.measurement)


def _context(
    root: Path,
    *,
    measurement: MeasurementSession | None = None,
) -> AtlasCliContext:
    resolved = root.expanduser().resolve()
    return AtlasCliContext(
        resolved,
        WorkspaceService(resolved, measurement=measurement),
    )


def _analyzer(service: WorkspaceService) -> Analyzer:
    return (_analyzer_factory or _default_analyzer)(service)


def _emit_report(report: WorkspaceRunReport, output_format: OutputFormat = OutputFormat.TEXT) -> None:
    typer.echo(render_report(report, output_format))


def _execute(
    context: AtlasCliContext,
    *,
    projects: tuple[str, ...],
    workers: int,
    force: bool,
    recover: bool,
) -> WorkspaceRunReport:
    orchestrator = WorkspaceAnalysisOrchestrator(context.service)
    selected = projects or context.service.workspace.names()
    analyzer = _analyzer(context.service)
    if recover:
        manager = WorkspaceRecoveryManager(
            context.service,
            encoder=encode_analysis_result,
            decoder=decode_analysis_result,
        )
        resumed, _ = manager.resume(orchestrator, analyzer, max_workers=workers)
        if resumed is not None:
            return resumed
        return manager.execute(orchestrator, analyzer, projects=list(selected), force=force, max_workers=workers)
    return orchestrator.execute(analyzer, projects=selected, force=force, max_workers=workers)


@app.command()
def analyze(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    project: Annotated[list[str] | None, typer.Option("--project", "-p", help="Project to analyze.")] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", min=1, help="Maximum concurrent projects.")] = 1,
    force: Annotated[bool, typer.Option("--force", help="Ignore reusable results.")] = False,
    recover: Annotated[bool, typer.Option("--recover/--no-recover", help="Resume a valid interrupted run.")] = True,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="Output format: text, json, jsonl, or sarif.")] = OutputFormat.TEXT,
    baseline: Annotated[Path | None, typer.Option("--baseline", help="Report only findings absent from this baseline.")] = None,
    write_baseline: Annotated[Path | None, typer.Option("--write-baseline", help="Write all current findings as a baseline.")] = None,
    diff: Annotated[bool, typer.Option("--diff", help="Report findings only on changed Git lines.")] = False,
    diff_base: Annotated[str | None, typer.Option("--diff-base", help="Git base revision for changed-line analysis.")] = None,
    diff_head: Annotated[str | None, typer.Option("--diff-head", help="Git head revision (requires --diff-base).")] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Analyze staged Git changes.")] = False,
    adaptive: Annotated[bool, typer.Option("--adaptive", help="Adapt workers to topology and historical timings.")] = False,
    profile: Annotated[
        bool,
        typer.Option(
            "--profile",
            help="Write an opt-in M2 performance measurement sidecar.",
        ),
    ] = False,
    profile_output: Annotated[
        Path | None,
        typer.Option(
            "--profile-output",
            help="Measurement JSON path; implies --profile.",
        ),
    ] = None,
    profile_memory: Annotated[
        bool,
        typer.Option(
            "--profile-memory",
            help="Collect best-effort process memory counters; implies --profile.",
        ),
    ] = False,
    profile_python_memory: Annotated[
        bool,
        typer.Option(
            "--profile-python-memory",
            help="Collect Python allocation samples with tracemalloc; implies --profile.",
        ),
    ] = False,
) -> None:
    """Analyze a workspace."""
    def operation() -> None:
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(root.expanduser().resolve(), profile_output)
            if profile_enabled
            else None
        )
        with _python_memory_collection(profile_python_memory):
            measurement = MeasurementSession(MeasurementConfig(
                enabled=profile_enabled,
                capture_process_memory=profile_memory,
                capture_python_memory=profile_python_memory,
                worker_metrics_supported=True,
            ))
            try:
                context = _context(root, measurement=measurement)
                selected = tuple(project or ())
                actual_workers = _adaptive_workers(context, selected, workers) if adaptive else workers
                report = _execute(context, projects=selected, workers=actual_workers, force=force, recover=recover)
                report = _apply_baseline_options(report, baseline=baseline, write_baseline=write_baseline)
                report = _apply_diff_options(report, root, enabled=diff, base=diff_base, head=diff_head, staged=staged)
                history = HistoryDatabase(root)
                with measurement.scope(
                    MeasurementPhase.PUBLICATION,
                    consumer="analysis-history",
                    sample_key="history",
                ) as publication:
                    run_id = history.record(
                        report,
                        adaptive_eligible=not profile_enabled,
                    )
                    publication.add_units(1)
                    publication.add_objects_produced(1)
                if report.succeeded:
                    collected = SemanticContextCollector(
                        context.service,
                        measurement=measurement,
                    ).collect(report)
                    store = SemanticSnapshotStore(
                        context.service.workspace,
                        measurement=measurement,
                    )
                    store.save(store.capture(
                        collected.context,
                        history_reference=run_id,
                    ))
                _emit_report(report, output_format)
            finally:
                if profile_target is not None:
                    _publish_measurement_report(
                        profile_target,
                        measurement,
                        output_kind=(
                            "default" if profile_output is None else "custom"
                        ),
                        memory_requested=profile_memory,
                        python_memory_requested=profile_python_memory,
                    )

    _run_command(operation)


@app.command()
def check(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    project: Annotated[list[str] | None, typer.Option("--project", "-p", help="Project to check.")] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", min=1, help="Maximum concurrent projects.")] = 1,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="Output format: text, json, jsonl, or sarif.")] = OutputFormat.TEXT,
    baseline: Annotated[Path | None, typer.Option("--baseline", help="Report only findings absent from this baseline.")] = None,
    write_baseline: Annotated[Path | None, typer.Option("--write-baseline", help="Write all current findings as a baseline.")] = None,
    diff: Annotated[bool, typer.Option("--diff", help="Report findings only on changed Git lines.")] = False,
    diff_base: Annotated[str | None, typer.Option("--diff-base", help="Git base revision for changed-line analysis.")] = None,
    diff_head: Annotated[str | None, typer.Option("--diff-head", help="Git head revision (requires --diff-base).")] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Analyze staged Git changes.")] = False,
    fail_on: Annotated[FindingSeverity | None, typer.Option("--fail-on", help="Fail on findings at or above this severity.")] = None,
    max_findings: Annotated[int | None, typer.Option("--max-findings", min=0, help="Maximum allowed findings.")] = None,
    finding_exit_code: Annotated[int | None, typer.Option("--finding-exit-code", min=1, max=255)] = None,
    analysis_exit_code: Annotated[int | None, typer.Option("--analysis-exit-code", min=1, max=255)] = None,
    adaptive: Annotated[bool, typer.Option("--adaptive", help="Adapt workers to topology and historical timings.")] = False,
) -> None:
    """Analyze a workspace and fail when project analysis fails."""
    def operation() -> None:
        context = _context(root)
        selected = tuple(project or ())
        actual_workers = _adaptive_workers(context, selected, workers) if adaptive else workers
        report = _execute(context, projects=selected, workers=actual_workers, force=False, recover=True)
        report = _apply_baseline_options(report, baseline=baseline, write_baseline=write_baseline)
        report = _apply_diff_options(report, root, enabled=diff, base=diff_base, head=diff_head, staged=staged)
        HistoryDatabase(root).record(report)
        _emit_report(report, output_format)
        if not report.succeeded:
            policy = QualityGatePolicy.from_options(
                dict(context.service.workspace.options),
                minimum_severity=fail_on,
                max_findings=max_findings,
                finding_exit_code=finding_exit_code,
                analysis_exit_code=analysis_exit_code,
            )
            raise typer.Exit(code=policy.analysis_exit_code)
        policy = QualityGatePolicy.from_options(
            dict(context.service.workspace.options),
            minimum_severity=fail_on,
            max_findings=max_findings,
            finding_exit_code=finding_exit_code,
            analysis_exit_code=analysis_exit_code,
        )
        gate = WorkspaceQualityGate().evaluate(report, policy)
        if not gate.passed:
            for reason in gate.reasons:
                typer.echo(f"quality-gate: {reason}", err=True)
            raise typer.Exit(code=gate.exit_code)

    _run_command(operation)


@app.command()
def watch(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    continuous: Annotated[bool, typer.Option("--continuous", help="Keep polling until interrupted.")] = False,
    iterations: Annotated[int, typer.Option("--iterations", min=0, help="Bounded poll count (ignored with --continuous).")] = 0,
    interval: Annotated[float, typer.Option("--interval", min=0, help="Seconds between polls.")] = 0.5,
    workers: Annotated[int, typer.Option("--workers", "-j", min=1, help="Maximum concurrent projects.")] = 1,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="Output format for changed runs.")] = OutputFormat.TEXT,
) -> None:
    """Watch a workspace and incrementally analyze changed projects."""
    def operation() -> None:
        context = _context(root)
        watcher = WorkspaceWatcher(context.service.workspace, event_bus=context.service.events)
        manager = WorkspaceWatchManager(
            watcher,
            WorkspaceAnalysisOrchestrator(context.service),
            _analyzer(context.service),
            interval_seconds=interval,
            max_workers=workers,
        )
        poll_limit = None if continuous else iterations
        result = manager.run(iterations=poll_limit, on_report=lambda report: _emit_report(report, output_format))
        typer.echo(f"workspace: {context.root.as_posix()}")
        typer.echo(f"projects: {len(context.service.workspace.projects)}")
        typer.echo(f"tracked_files: {len(result.snapshot.files)}")
        typer.echo(f"polls: {result.polls}")
        typer.echo(f"analyses: {len(result.reports)}")
        typer.echo("status: stopped" if (continuous or iterations) else "status: ready")

    _run_command(operation)


@app.command("config")
def config_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    project: Annotated[str | None, typer.Option("--project", "-p", help="Resolve configuration for one project.")] = None,
) -> None:
    """Show deterministic resolved workspace configuration."""
    def operation() -> None:
        context = _context(root)
        if project is None:
            typer.echo(f"workspace: {context.root.as_posix()}")
            for key, value in sorted(context.service.workspace.options):
                typer.echo(f"{key}={value}")
            return
        resolved = context.service.resolved_configuration(project)
        typer.echo(f"project: {project}")
        for key, value in _flatten(resolved.to_dict()):
            typer.echo(f"{key}={_display(value)}")

    _run_command(operation)


@app.command()
def plugins(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    plugin_root: Annotated[list[Path] | None, typer.Option("--plugin-root", help="Plugin directory or manifest.")] = None,
) -> None:
    """List discovered plugins and diagnostics."""
    def operation() -> None:
        context = _context(root)
        roots = tuple(plugin_root or (context.root / "plugins",))
        result = PluginDiscovery().discover(roots)
        for plugin in result.plugins:
            typer.echo(f"{plugin.manifest.plugin_id} {plugin.manifest.version} {plugin.manifest.name}")
        for diagnostic in result.diagnostics:
            typer.echo(f"{diagnostic.level}: {diagnostic.message}", err=True)
        typer.echo(f"plugins: {len(result.plugins)}")
        typer.echo(f"diagnostics: {len(result.diagnostics)}")

    _run_command(operation)


@app.command("ci")
def ci_command(
    provider: Annotated[CiProvider, typer.Argument(help="CI provider: github, gitlab, or azure.")],
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Override the provider's canonical path.")] = None,
    python_version: Annotated[str, typer.Option("--python-version", help="Python version used by the CI job.")] = "3.12",
    force: Annotated[bool, typer.Option("--force", help="Replace an existing template.")] = False,
) -> None:
    """Install a deterministic Atlas CI template."""
    def operation() -> None:
        target = CiTemplateService().write(
            root,
            provider,
            output=output,
            python_version=python_version,
            force=force,
        )
        typer.echo(target.as_posix())

    _run_command(operation)


@app.command("history")
def history_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    limit: Annotated[int, typer.Option("--limit", min=0, help="Maximum runs to display.")] = 20,
) -> None:
    """List recorded workspace analyses, newest first."""
    def operation() -> None:
        runs = HistoryDatabase(root).list(limit=limit)
        for run in runs:
            typer.echo(
                f"{run.run_id} {run.created_at} "
                f"{'succeeded' if run.succeeded else 'failed'} projects={len(run.runs)}"
            )
        typer.echo(f"runs: {len(runs)}")

    _run_command(operation)


@app.command("dashboard")
def dashboard_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    output: Annotated[Path, typer.Option("--output", "-o", help="Dashboard HTML path.")] = Path(".atlas/dashboard.html"),
    limit: Annotated[int, typer.Option("--limit", min=0, help="Maximum historical runs.")] = 100,
) -> None:
    """Generate a self-contained historical dashboard."""
    def operation() -> None:
        target = DashboardService(HistoryDatabase(root)).generate(output, limit=limit)
        typer.echo(target.as_posix())

    _run_command(operation)


@app.command("profile")
def profile_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    project: Annotated[list[str] | None, typer.Option("--project", "-p", help="Project to profile.")] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", min=1, help="Maximum concurrent projects.")] = 1,
) -> None:
    """Analyze a workspace and emit deterministic performance metrics."""
    def operation() -> None:
        context = _context(root)
        profiler = PerformanceProfiler()
        orchestrator = WorkspaceAnalysisOrchestrator(context.service)
        selected = tuple(project or context.service.workspace.names())
        with profiler.measure("workspace"):
            orchestrator.execute(
                profiler.wrap_analyzer(_analyzer(context.service)),
                projects=selected,
                max_workers=workers,
            )
        typer.echo(profiler.report().to_json(), nl=False)

    _run_command(operation)


@app.command("governance")
def governance_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
) -> None:
    """Verify the workspace governance audit chain."""
    def operation() -> None:
        path = root.expanduser().resolve() / ".atlas" / "governance-audit.jsonl"
        count = GovernanceAuditLog(path).verify()
        typer.echo(f"audit: valid")
        typer.echo(f"records: {count}")

    _run_command(operation)


def _load_ai_snapshot(
    root: Path,
    snapshot: Path | None,
    *,
    measurement: MeasurementSession | None = None,
):
    # Snapshot-backed AI commands must not rediscover or rescan the repository.
    # A minimal workspace supplies only the durable ASS location; all repository
    # facts come from the checksum-verified snapshot itself.
    workspace = Workspace(root.expanduser().resolve(), ())
    store = SemanticSnapshotStore(workspace, measurement=measurement)
    loaded = store.load(snapshot)
    if loaded is None:
        target = snapshot or store.latest_path
        raise SemanticSnapshotError(
            f"semantic snapshot not found: {target}; run analysis snapshot creation first"
        )
    return loaded


@app.command("search")
def semantic_search_command(
    query: Annotated[str, typer.Argument(help="Engineering concept, subject, or relationship query.")],
    root: Annotated[Path, typer.Argument(help="Workspace root containing the semantic snapshot.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Read a specific .ass snapshot instead of latest.ass.")] = None,
    kind: Annotated[list[str] | None, typer.Option("--kind", help="Constrain a canonical subject kind; repeat as needed.")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Constrain the owning project.")] = None,
    module: Annotated[str | None, typer.Option("--module", help="Constrain the module projection.")] = None,
    package: Annotated[str | None, typer.Option("--package", help="Constrain the package projection.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="Constrain the analyzer language.")] = None,
    relation: Annotated[str | None, typer.Option("--relation", help="Constrain a canonical relationship kind.")] = None,
    minimum_confidence: Annotated[float, typer.Option("--min-confidence", min=0.0, max=1.0, help="Minimum structured evidence confidence.")] = 0.0,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100, help="Maximum returned results.")] = 20,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    explain_score: Annotated[bool, typer.Option("--explain-score", help="Show deterministic score components in human output.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 search measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Search measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Search a verified semantic snapshot without an LLM or source text."""

    def operation() -> None:
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(
                root.expanduser().resolve(),
                profile_output,
                default_name="latest-search.json",
            )
            if profile_enabled else None
        )
        with _python_memory_collection(profile_python_memory):
            measurement = MeasurementSession(MeasurementConfig(
                enabled=profile_enabled,
                capture_process_memory=profile_memory,
                capture_python_memory=profile_python_memory,
            ))
            try:
                kinds = tuple(
                    KnowledgeKind(item.strip().casefold().replace("-", "_"))
                    for item in (kind or ())
                )
                selected_relation = (
                    KnowledgeRelation(relation.strip().casefold().replace("-", "_"))
                    if relation is not None else None
                )
                request = SemanticSearchRequest(
                    query,
                    kinds,
                    project,
                    module,
                    package,
                    language,
                    selected_relation,
                    minimum_confidence,
                    limit,
                )
                try:
                    loaded = _load_ai_snapshot(
                        root, snapshot, measurement=measurement,
                    )
                except SemanticSnapshotError as exc:
                    if str(exc).startswith("semantic snapshot not found:"):
                        raise SemanticSnapshotError(
                            "semantic snapshot not found; run analysis snapshot creation first"
                        ) from exc
                    raise SemanticSnapshotError(
                        "semantic snapshot could not be loaded or verified"
                    ) from exc
                response = SemanticSearchService.from_snapshot(
                    loaded, measurement=measurement,
                ).search_semantic(request)
                with measurement.scope(
                    "semantic_search.render",
                    consumer="semantic-search",
                    sample_key=response.index_id,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_semantic_search(
                            response, explain_score=explain_score,
                        )
                    )
                    rendering.add_units(len(response.hits))
                    rendering.add_bytes(len(output.encode("utf-8")))
                    rendering.add_objects_produced(1)
                    typer.echo(output, nl=False)
            finally:
                if profile_target is not None:
                    _publish_measurement_report(
                        profile_target,
                        measurement,
                        output_kind=(
                            "default" if profile_output is None else "custom"
                        ),
                        memory_requested=profile_memory,
                        python_memory_requested=profile_python_memory,
                    )

    _run_command(operation)


@app.command("impact")
def impact_prediction_command(
    subject: Annotated[str, typer.Argument(help="Canonical subject ID or exact repository subject name.")],
    root: Annotated[Path, typer.Argument(help="Workspace root containing the semantic snapshot.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Read a specific .ass snapshot instead of latest.ass.")] = None,
    additional_subject: Annotated[list[str] | None, typer.Option("--additional-subject", help="Add another deterministic impact root; repeat as needed.")] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="Constrain the canonical subject kind.")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Constrain the owning project.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="Constrain the analyzer language.")] = None,
    path_constraint: Annotated[str | None, typer.Option("--path", help="Constrain a workspace-relative subject path.")] = None,
    module: Annotated[str | None, typer.Option("--module", help="Constrain the represented module scope.")] = None,
    package: Annotated[str | None, typer.Option("--package", help="Constrain the represented package scope.")] = None,
    change: Annotated[ImpactChangeKind, typer.Option("--change", help="Structured change scenario.")] = ImpactChangeKind.UNKNOWN,
    relation: Annotated[list[str] | None, typer.Option("--relation", help="Restrict canonical propagation relations; repeat as needed.")] = None,
    tests: Annotated[bool, typer.Option("--tests", help="Include compatible evidence-backed test impact.")] = False,
    dependencies: Annotated[bool, typer.Option("--dependencies/--no-dependencies", help="Include declared dependency impact.")] = True,
    risk: Annotated[bool, typer.Option("--risk/--no-risk", help="Attach compatible PR132 risk context.")] = True,
    git_context: Annotated[bool, typer.Option("--git-context", help="Request compatible source-free Git enrichment when available.")] = False,
    search_enrichment: Annotated[bool, typer.Option("--search-enrichment", help="Request optional PR135 discovery context; never impact proof.")] = False,
    depth: Annotated[int, typer.Option("--depth", min=1, max=64, help="Maximum relationship depth.")] = 4,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum returned impact classifications.")] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    explain_score: Annotated[bool, typer.Option("--explain-score", help="Show deterministic score components in human output.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 impact measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Impact measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Predict evidence-backed change impact without an LLM."""

    def operation() -> None:
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(
                root.expanduser().resolve(),
                profile_output,
                default_name="latest-impact.json",
            )
            if profile_enabled else None
        )
        with _python_memory_collection(profile_python_memory):
            measurement = MeasurementSession(MeasurementConfig(
                enabled=profile_enabled,
                capture_process_memory=profile_memory,
                capture_python_memory=profile_python_memory,
            ))
            try:
                selected_kind = (
                    KnowledgeKind(kind.strip().casefold().replace("-", "_"))
                    if kind is not None else None
                )
                selected_relations = tuple(
                    KnowledgeRelation(item.strip().casefold().replace("-", "_"))
                    for item in (relation or ())
                )
                request = ImpactPredictionRequest(
                    SubjectQuery(
                        subject,
                        selected_kind,
                        project,
                        language,
                        path_constraint,
                    ),
                    change,
                    relations=selected_relations,
                    module=module,
                    package=package,
                    max_depth=depth,
                    limit=limit,
                    include_tests=tests,
                    include_dependencies=dependencies,
                    include_risk=risk,
                    include_git_context=git_context,
                    include_search_enrichment=search_enrichment,
                    additional_subjects=tuple(
                        SubjectQuery(
                            item,
                            selected_kind,
                            project,
                            language,
                            path_constraint,
                        )
                        for item in (additional_subject or ())
                    ),
                )
                try:
                    loaded = _load_ai_snapshot(
                        root, snapshot, measurement=measurement,
                    )
                except SemanticSnapshotError as exc:
                    if str(exc).startswith("semantic snapshot not found:"):
                        raise SemanticSnapshotError(
                            "semantic snapshot not found; run analysis snapshot creation first"
                        ) from exc
                    raise SemanticSnapshotError(
                        "semantic snapshot could not be loaded or verified"
                    ) from exc
                response = ImpactPredictionService.from_snapshot(
                    loaded, measurement=measurement,
                ).predict(request)
                with measurement.scope(
                    "impact_prediction.render",
                    consumer="impact-prediction",
                    sample_key=response.input_fingerprint,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_impact_prediction(
                            response, explain_score=explain_score,
                        )
                    )
                    rendering.add_units(len(response.findings))
                    rendering.add_bytes(len(output.encode("utf-8")))
                    rendering.add_objects_produced(1)
                    typer.echo(output, nl=False)
            finally:
                if profile_target is not None:
                    _publish_measurement_report(
                        profile_target,
                        measurement,
                        output_kind=(
                            "default" if profile_output is None else "custom"
                        ),
                        memory_requested=profile_memory,
                        python_memory_requested=profile_python_memory,
                    )

    _run_command(operation)


@app.command("refactor")
def refactoring_advisor_command(
    root: Annotated[Path, typer.Argument(help="Workspace root containing the semantic snapshot.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Read a specific .ass snapshot instead of latest.ass.")] = None,
    subject: Annotated[str, typer.Option("--subject", help="Canonical subject ID or exact repository subject name.")] = "repository",
    kind: Annotated[str | None, typer.Option("--kind", help="Constrain the canonical subject kind.")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Constrain the owning project.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="Constrain the analyzer language.")] = None,
    path_constraint: Annotated[str | None, typer.Option("--path", help="Constrain a workspace-relative subject path.")] = None,
    family: Annotated[list[str] | None, typer.Option("--family", help="Restrict an advice family; repeat as needed.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum returned advice items.")] = 20,
    impact: Annotated[bool, typer.Option("--impact/--no-impact", help="Attach compatible bounded PR136 impact context.")] = True,
    impact_depth: Annotated[int, typer.Option("--impact-depth", min=1, max=64, help="Maximum PR136 impact depth.")] = 4,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    explain_score: Annotated[bool, typer.Option("--explain-score", help="Show deterministic estimate and confidence components.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 refactoring-advisor measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Refactoring measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Suggest evidence-backed refactoring review seams without changing code."""

    def operation() -> None:
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(
                root.expanduser().resolve(),
                profile_output,
                default_name="latest-refactor.json",
            )
            if profile_enabled else None
        )
        with _python_memory_collection(profile_python_memory):
            measurement = MeasurementSession(MeasurementConfig(
                enabled=profile_enabled,
                capture_process_memory=profile_memory,
                capture_python_memory=profile_python_memory,
            ))
            try:
                selected_kind = (
                    KnowledgeKind(kind.strip().casefold().replace("-", "_"))
                    if kind is not None else None
                )
                selected_families = tuple(
                    RefactoringFamily(
                        item.strip().casefold().replace("-", "_")
                    )
                    for item in (family or ())
                )
                request = RefactoringRequest(
                    SubjectQuery(
                        subject,
                        selected_kind,
                        project,
                        language,
                        path_constraint,
                    ),
                    families=selected_families,
                    limit=limit,
                    include_impact=impact,
                    impact_depth=impact_depth,
                )
                try:
                    loaded = _load_ai_snapshot(
                        root, snapshot, measurement=measurement,
                    )
                except SemanticSnapshotError as exc:
                    if str(exc).startswith("semantic snapshot not found:"):
                        raise SemanticSnapshotError(
                            "semantic snapshot not found; run analysis snapshot creation first"
                        ) from exc
                    raise SemanticSnapshotError(
                        "semantic snapshot could not be loaded or verified"
                    ) from exc
                response = RefactoringAdvisorService.from_snapshot(
                    loaded, measurement=measurement,
                ).advise(request)
                with measurement.scope(
                    "refactoring_advisor.render",
                    consumer="refactoring-advisor",
                    sample_key=response.input_fingerprint,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_refactoring_advice(
                            response, explain_score=explain_score,
                        )
                    )
                    rendering.add_units(len(response.advice))
                    rendering.add_bytes(len(output.encode("utf-8")))
                    rendering.add_objects_produced(1)
                    typer.echo(output, nl=False)
            finally:
                if profile_target is not None:
                    _publish_measurement_report(
                        profile_target,
                        measurement,
                        output_kind=(
                            "default" if profile_output is None else "custom"
                        ),
                        memory_requested=profile_memory,
                        python_memory_requested=profile_python_memory,
                    )

    _run_command(operation)


def _future_ai_engine(command: str, root: Path, snapshot: Path | None) -> None:
    def operation() -> None:
        _load_ai_snapshot(root, snapshot)
        typer.echo(
            f"error: atlas ai {command} requires its roadmap engine, which is not implemented yet",
            err=True,
        )
        raise typer.Exit(code=2)

    _run_command(operation)


@ai_app.command("context")
def ai_context_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    snapshot: Annotated[
        Path | None,
        typer.Option("--snapshot", help="Read a specific .ass file instead of latest.ass."),
    ] = None,
    metadata: Annotated[
        bool,
        typer.Option("--metadata", help="Include snapshot metadata instead of semantic context only."),
    ] = False,
) -> None:
    """Print deterministic semantic context from an Atlas snapshot."""
    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        payload = loaded.to_dict() if metadata else loaded.to_context().to_dict()
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    _run_command(operation)


@ai_app.command("explain")
def ai_explain_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Specific .ass snapshot.")] = None,
    subject: Annotated[str, typer.Option("--subject", help="Workspace semantic subject.")] = "workspace",
    kind: Annotated[str | None, typer.Option("--kind", help="Constrain the canonical subject kind.")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Constrain the owning project.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="Constrain the subject language.")] = None,
    path_constraint: Annotated[str | None, typer.Option("--path", help="Constrain a workspace-relative subject path.")] = None,
    target: Annotated[str | None, typer.Option("--target", help="Canonical target for a relationship explanation.")] = None,
    relation: Annotated[str | None, typer.Option("--relation", help="Canonical relationship kind to explain.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print deterministic structured explanation JSON without an LLM.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 Explain measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Explain measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Render a repository report or explain a targeted semantic subject."""
    def operation() -> None:
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(
                root.expanduser().resolve(),
                profile_output,
                default_name="latest-explain.json",
            )
            if profile_enabled
            else None
        )
        with _python_memory_collection(profile_python_memory):
            measurement = MeasurementSession(MeasurementConfig(
                enabled=profile_enabled,
                capture_process_memory=profile_memory,
                capture_python_memory=profile_python_memory,
            ))
            try:
                loaded = _load_ai_snapshot(
                    root,
                    snapshot,
                    measurement=measurement,
                )
                request = ExplainRequest(
                    subject=subject,
                    kind=kind,
                    project=project,
                    language=language,
                    path_constraint=path_constraint,
                    target=target,
                    relation=relation,
                    narrative=not json_output,
                )
                if json_output:
                    result = ExplainEngine(
                        measurement=measurement,
                    ).explain(loaded, request)
                    structured = result.structured_explanation
                    if structured is None:
                        raise ValueError("structured explanation is unavailable")
                    typer.echo(structured.to_json())
                elif ExplainEngine._is_repository_default(request):
                    result = ExplainEngine(
                        memory=ConversationMemoryStore(root),
                        measurement=measurement,
                    ).explain(loaded, request)
                    typer.echo(result.markdown)
                else:
                    provider = (_ai_provider_factory or OllamaProvider)()
                    try:
                        result = ExplainEngine(
                            LlmClient(provider),
                            memory=ConversationMemoryStore(root),
                            measurement=measurement,
                        ).explain(loaded, request)
                        typer.echo(result.markdown)
                    finally:
                        close = getattr(provider, "close", None)
                        if callable(close):
                            close()
            finally:
                if profile_target is not None:
                    _publish_measurement_report(
                        profile_target,
                        measurement,
                        output_kind=(
                            "default" if profile_output is None else "custom"
                        ),
                        memory_requested=profile_memory,
                        python_memory_requested=profile_python_memory,
                    )

    _run_command(operation)


@ai_app.command("ask")
def ai_ask_command(
    question: Annotated[str, typer.Argument(help="Question about the workspace.")],
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Specific .ass snapshot.")] = None,
) -> None:
    """Ask a semantic question about an ASS artifact."""
    if not question.strip():
        typer.echo("error: question must not be empty", err=True)
        raise typer.Exit(code=2)
    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        provider = (_ai_provider_factory or OllamaProvider)()
        try:
            result = AskEngine(LlmClient(provider), memory=ConversationMemoryStore(root)).ask(
                loaded, AskRequest(question)
            )
            typer.echo(result.answer)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
    _run_command(operation)


@ai_app.command("review")
def ai_review_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Specific .ass snapshot.")] = None,
    category: Annotated[list[str] | None, typer.Option("--category", "-c")] = None,
) -> None:
    """Review architecture using verified semantic knowledge."""
    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        provider = (_ai_provider_factory or OllamaProvider)()
        try:
            request = ReviewRequest(categories=tuple(category)) if category else ReviewRequest()
            result = ReviewEngine(LlmClient(provider), memory=ConversationMemoryStore(root)).review(loaded, request)
            typer.echo(result.markdown)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
    _run_command(operation)


@ai_app.command("fix")
def ai_fix_command(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Specific .ass snapshot.")] = None,
    objective: Annotated[str, typer.Option("--objective", "-o", help="Requested code change.")] = "Fix verified diagnostics.",
) -> None:
    """Propose and validate a Git patch without applying it."""
    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        provider = (_ai_provider_factory or OllamaProvider)()
        try:
            result = PatchEngine(LlmClient(provider), GitPatchValidator(root)).propose(
                loaded, PatchRequest(objective)
            )
            typer.echo(result.patch, nl=False)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
    _run_command(operation)


@ai_app.command("git-context")
def ai_git_context_command(
    root: Annotated[Path, typer.Argument(help="Git workspace root.")] = Path("."),
    commits: Annotated[int, typer.Option("--commits", min=0)] = 20,
    blame: Annotated[list[str] | None, typer.Option("--blame")] = None,
) -> None:
    """Print deterministic Git context for Atlas AI."""
    _run_command(
        lambda: typer.echo(
            GitContextService(root).collect(
                commit_limit=commits,
                blame_files=tuple(blame or ()),
            ).to_json(),
            nl=False,
        )
    )


@ai_app.command("version")
def ai_version_command() -> None:
    """Print Atlas AI release version and capabilities."""
    typer.echo(f"Atlas AI {ATLAS_AI_VERSION}")
    typer.echo(atlas_ai_capabilities().to_json())


def _run_command(operation: Callable[[], None]) -> None:
    try:
        operation()
    except typer.Exit:
        raise
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        ValueError,
        WorkspaceConfigurationError,
        WorkspaceStateError,
        FindingBaselineError,
        GitDiffError,
        CiTemplateError,
        HistoryDatabaseError,
        GovernanceError,
        SemanticSnapshotError,
    ) as exc:
        log_event(
            _logger,
            logging.ERROR,
            "cli.command_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


def _measurement_output_path(
    root: Path,
    output: Path | None,
    *,
    default_name: str = "latest.json",
) -> Path:
    workspace_root = root.expanduser().resolve()
    if output is None:
        return workspace_root / ".atlas" / "measurements" / default_name
    target = output.expanduser().resolve()
    if target.suffix.casefold() != ".json":
        raise ValueError("measurement output must use a .json extension")
    try:
        target.relative_to(workspace_root)
    except ValueError:
        return target
    measurement_root = workspace_root / ".atlas" / "measurements"
    try:
        target.relative_to(measurement_root)
    except ValueError as exc:
        raise ValueError(
            "measurement output inside a workspace must be under "
            ".atlas/measurements so it cannot affect semantic identity"
        ) from exc
    return target


class _PythonMemoryCollection(AbstractContextManager[None]):
    """Own tracemalloc without a generator context rewriting exceptions."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.joined = False

    def __enter__(self) -> None:
        global _tracemalloc_owned, _tracemalloc_users
        if not self.enabled:
            return None
        with _tracemalloc_lock:
            try:
                tracing = tracemalloc.is_tracing()
            except Exception:
                tracing = False
            if _tracemalloc_users == 0 and not tracing:
                try:
                    tracemalloc.start()
                except Exception:
                    _tracemalloc_owned = False
                else:
                    _tracemalloc_owned = True
            _tracemalloc_users += 1
            self.joined = True
        return None

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        global _tracemalloc_owned, _tracemalloc_users
        if self.joined:
            with _tracemalloc_lock:
                _tracemalloc_users = max(0, _tracemalloc_users - 1)
                if _tracemalloc_users == 0 and _tracemalloc_owned:
                    try:
                        tracemalloc.stop()
                    except Exception:
                        pass
                    finally:
                        _tracemalloc_owned = False
                self.joined = False
        return False


def _python_memory_collection(enabled: bool) -> AbstractContextManager[None]:
    return _PythonMemoryCollection(enabled)


def _write_measurement_report(
    path: Path,
    report: MeasurementReport,
) -> Path:
    """Atomically replace one source-free measurement sidecar."""

    _validate_measurement_output_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(report.to_json())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return path


def _validate_measurement_output_target(path: Path) -> None:
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, Mapping):
            raise ValueError("measurement sidecar must be a JSON object")
        MeasurementReport.from_dict(existing)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(
            "refusing to replace an existing file that is not a valid "
            "Atlas performance measurement sidecar"
        ) from exc


def _publish_measurement_report(
    path: Path,
    measurement: MeasurementSession,
    *,
    output_kind: str,
    memory_requested: bool,
    python_memory_requested: bool,
) -> bool:
    """Publish operational evidence without changing an Atlas command outcome."""

    try:
        report = measurement.report()
        _write_measurement_report(path, report)
        _emit_measurement_summary(
            report,
            output_kind=output_kind,
            memory_requested=memory_requested,
            python_memory_requested=python_memory_requested,
        )
    except Exception:
        typer.echo(
            "profile: unavailable (sidecar-publication-failed)",
            err=True,
        )
        return False
    return True


def _emit_measurement_summary(
    report: MeasurementReport,
    *,
    output_kind: str,
    memory_requested: bool,
    python_memory_requested: bool,
) -> None:
    """Write a compact operational summary without changing command stdout."""

    typer.echo(
        f"profile: samples={len(report.samples)} phases={len(report.aggregates)} "
        f"eligible={report.sampling.eligible_scopes} "
        f"sample_every={report.sampling.sample_every} output={output_kind}",
        err=True,
    )
    unavailable_phases = sum(
        item["status"] == MetricStatus.UNAVAILABLE.value
        for item in report.phase_statuses
    )
    unsupported_phases = sum(
        item["status"] == MetricStatus.UNSUPPORTED.value
        for item in report.phase_statuses
    )
    typer.echo(
        "profile-coverage: "
        f"unsupported={unsupported_phases} unavailable={unavailable_phases}",
        err=True,
    )
    for aggregate in report.aggregates:
        wall = next(
            (
                metric
                for metric in aggregate.metrics
                if metric.name == "wall_time_ns"
            ),
            None,
        )
        if wall is not None and wall.measured_count:
            typer.echo(
                f"profile-phase: {aggregate.phase_id} "
                f"samples={aggregate.sample_count} "
                "cumulative_sample_wall_ms="
                f"{float(wall.total or 0) / 1_000_000:.3f}",
                err=True,
            )
    if memory_requested:
        rss = [
            metric
            for sample in report.samples
            for name, metric in sample.metrics
            if name == "rss_bytes" and metric.value is not None
        ]
        if rss:
            typer.echo(
                f"profile-memory: maximum_sampled_rss_bytes="
                f"{max(int(metric.value) for metric in rss if metric.value is not None)}",
                err=True,
            )
        else:
            statuses = {
                metric.status
                for sample in report.samples
                for name, metric in sample.metrics
                if name == "rss_bytes"
            }
            state = (
                "unsupported"
                if MetricStatus.UNSUPPORTED in statuses
                else "unavailable"
            )
            typer.echo(f"profile-memory: {state}", err=True)
    if python_memory_requested:
        python_peaks = [
            metric
            for sample in report.samples
            for name, metric in sample.metrics
            if name == "python_peak_allocated_bytes" and metric.value is not None
        ]
        if python_peaks:
            typer.echo(
                f"profile-python-memory: maximum_sampled_peak_bytes="
                f"{max(int(metric.value) for metric in python_peaks if metric.value is not None)}",
                err=True,
            )
        else:
            statuses = {
                metric.status
                for sample in report.samples
                for name, metric in sample.metrics
                if name == "python_peak_allocated_bytes"
            }
            state = (
                "unsupported"
                if MetricStatus.UNSUPPORTED in statuses
                else "unavailable"
            )
            typer.echo(f"profile-python-memory: {state}", err=True)


def _apply_baseline_options(
    report: WorkspaceRunReport,
    *,
    baseline: Path | None,
    write_baseline: Path | None,
) -> WorkspaceRunReport:
    service = FindingBaselineService()
    if write_baseline is not None:
        FindingBaselineStore(write_baseline).save(service.capture(report))
    if baseline is not None:
        report, _ = service.filter(report, FindingBaselineStore(baseline).load())
    return report


def _apply_diff_options(
    report: WorkspaceRunReport,
    root: Path,
    *,
    enabled: bool,
    base: str | None,
    head: str | None,
    staged: bool,
) -> WorkspaceRunReport:
    if not (enabled or base is not None or head is not None or staged):
        return report
    resolved = root.expanduser().resolve()
    diff = GitDiffService(resolved).collect(base=base, head=head, staged=staged)
    return GitDiffFilter().filter_report(report, diff, root=resolved)


def _adaptive_workers(context: AtlasCliContext, projects: tuple[str, ...], worker_cap: int) -> int:
    selected = projects or context.service.workspace.names()
    ordered = context.service.analysis_order(selected)
    durations: dict[str, list[float]] = {}
    for historical in HistoryDatabase(context.root).list_adaptive_eligible(limit=20):
        for run in historical.runs:
            durations.setdefault(run.project, []).append(run.duration_ms)
    averages = {name: sum(values) / len(values) for name, values in durations.items()}
    return AdaptiveWorkspaceScheduler().recommend(
        ordered,
        worker_cap=worker_cap,
        duration_ms=averages,
    ).workers


def _flatten(values: Mapping[str, Any], prefix: str = "") -> tuple[tuple[str, Any], ...]:
    result: list[tuple[str, Any]] = []
    for key in sorted(values):
        path = f"{prefix}.{key}" if prefix else str(key)
        value = values[key]
        if isinstance(value, Mapping):
            result.extend(_flatten(value, path))
        else:
            result.append((path, value))
    return tuple(result)


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (list, tuple)):
        return ",".join(_display(item) for item in value)
    return str(value)


def main() -> None:
    """Run the unified Atlas CLI."""
    app()


if __name__ == "__main__":
    main()
