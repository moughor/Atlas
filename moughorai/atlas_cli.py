"""Unified Atlas command-line interface introduced in PR75."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import stat
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
from .semantic_snapshot import (
    SemanticSnapshotError,
    SemanticSnapshotStore,
    SnapshotResolution,
    SnapshotResolver,
)
from .knowledge_graph import KnowledgeKind, KnowledgeRelation
from .code_intelligence import (
    CodeIntelligenceConfiguration,
    CodeSubjectResolutionStatus,
    JavaCodeIntelligenceService,
    render_code_intelligence,
)
from .engineering_answer import (
    EngineeringAnswerConfiguration,
    EngineeringAnswerNameResolver,
    EngineeringAnswerService,
    EngineeringAnswerView,
    render_engineering_answer,
)
from .semantic_search import (
    SemanticSearchRequest,
    SemanticSearchService,
    render_semantic_search,
)
from .semantic_search.interpreter import interpret_query
from .semantic_search.models import SearchIntent
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
from .security_intelligence import (
    SecurityCategory,
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SecurityScope,
    SecuritySeverity,
    render_security_intelligence,
)
from .change_review import (
    ChangeReviewRequest,
    ChangeReviewService,
    render_change_review,
)
from .repository_evolution import (
    RepositoryEvolutionRequest,
    RepositoryEvolutionService,
    render_repository_evolution,
)
from .technical_debt import (
    TechnicalDebtRequest,
    TechnicalDebtService,
    render_technical_debt,
)
from .subject_resolution import ResolutionStatus, SubjectQuery
from .ai_explain import ExplainEngine, ExplainRequest
from .ai_memory import ConversationMemoryStore
from .ai_review import ReviewEngine, ReviewRequest
from .ai_ask import AskEngine, AskRequest, EngineeringChatContextBuilder
from .repository_runtime import RepositoryRuntimeSession
from .story_planning import (
    StoryPlan,
    StoryPlanningRequest,
    StoryPlanningService,
    StoryPlanView,
    normalize_story_text,
    render_story_plan,
    story_fingerprint,
)
from .engineering_agent import (
    EngineeringAgentError,
    EngineeringAgentRuntime,
    EngineeringApplyError,
    EngineeringPatchProposal,
    EngineeringProviderFailure,
    EngineeringProviderTelemetry,
    render_apply_result,
    render_engineering_diff,
    render_implementation_proposal,
    render_verification_plan,
)
from .agent_context import (
    AgentContextService,
    AgentGraphDepth,
    load_agent_context_package,
    load_agent_graph_projection,
)
from .agent_review import (
    AgentReviewConfiguration,
    AgentReviewService,
    render_agent_post_change_review,
    resolve_default_graph_path,
)
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
from .ai_context.process_execution import ProcessProjectAnalyzer
from .llm import LlmClient, LlmProviderError, OllamaProvider, RetryPolicy
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
    help="Atlas deterministic repository-intelligence backend.",
    no_args_is_help=True,
)
ai_app = typer.Typer(
    name="ai",
    help=(
        "Query verified Atlas semantic snapshots; the interactive "
        "engineering-agent runtime is experimental."
    ),
    no_args_is_help=True,
)
snapshot_app = typer.Typer(
    name="snapshot",
    help="Resolve and register verified semantic snapshots for query commands.",
    no_args_is_help=True,
)
app.add_typer(ai_app, name="ai")
app.add_typer(snapshot_app, name="snapshot")
_logger = get_logger("cli")


agent_app = typer.Typer(
    name='agent',
    help='Primary supported export workflow and post-change review for external coding agents.',
    no_args_is_help=True,
)
app.add_typer(agent_app, name='agent')


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
    """Atlas deterministic repository-intelligence backend."""
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


class AnalysisExecutor(str, Enum):
    AUTO = "auto"
    SERIAL = "serial"
    THREAD = "thread"
    PROCESS = "process"


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
    executor: AnalysisExecutor = AnalysisExecutor.AUTO,
) -> WorkspaceRunReport:
    orchestrator = WorkspaceAnalysisOrchestrator(context.service)
    selected = projects or context.service.workspace.names()
    selected_executor = executor
    if selected_executor is AnalysisExecutor.AUTO:
        selected_executor = (
            AnalysisExecutor.SERIAL
            if workers == 1
            else AnalysisExecutor.THREAD
        )
    if selected_executor is AnalysisExecutor.SERIAL and workers != 1:
        raise ValueError("serial executor requires --workers 1")
    if selected_executor is AnalysisExecutor.PROCESS:
        if _analyzer_factory is not None:
            raise ValueError(
                "process executor supports only the built-in AnalyzerRegistry"
            )
        with ProcessProjectAnalyzer(workers) as analyzer:
            return _execute_with_analyzer(
                context,
                orchestrator,
                analyzer,
                selected=selected,
                workers=workers,
                force=force,
                recover=recover,
            )
    analyzer = _analyzer(context.service)
    return _execute_with_analyzer(
        context,
        orchestrator,
        analyzer,
        selected=selected,
        workers=(1 if selected_executor is AnalysisExecutor.SERIAL else workers),
        force=force,
        recover=recover,
    )


def _execute_with_analyzer(
    context: AtlasCliContext,
    orchestrator: WorkspaceAnalysisOrchestrator,
    analyzer: Analyzer,
    *,
    selected: tuple[str, ...],
    workers: int,
    force: bool,
    recover: bool,
) -> WorkspaceRunReport:
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
    executor: Annotated[
        AnalysisExecutor,
        typer.Option(
            "--executor",
            help=(
                "Project executor: auto preserves compatibility; serial is the "
                "reference; process provides CPU scaling; thread is legacy."
            ),
        ),
    ] = AnalysisExecutor.AUTO,
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
                worker_metrics_supported=(
                    executor is not AnalysisExecutor.PROCESS
                ),
            ))
            try:
                context = _context(root, measurement=measurement)
                selected = tuple(project or ())
                actual_workers = _adaptive_workers(context, selected, workers) if adaptive else workers
                report = _execute(
                    context,
                    projects=selected,
                    workers=actual_workers,
                    force=force,
                    recover=recover,
                    executor=executor,
                )
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


@agent_app.command('context')
def agent_context_command(
    root: Annotated[
        Path,
        typer.Argument(help='Repository root containing a validated Atlas snapshot.'),
    ],
    story_file: Annotated[
        Path,
        typer.Option(
            '--story-file',
            help=(
                'UTF-8 Jira/story text file (maximum 50,000 normalized '
                'characters and 256 KiB).'
            ),
        ),
    ],
    output: Annotated[
        Path,
        typer.Option('--output', help='External directory for the four context artifacts.'),
    ],
    snapshot: Annotated[
        Path | None,
        typer.Option('--snapshot', help='Read a specific checksum-verified .ass snapshot.'),
    ] = None,
    subject: Annotated[
        str | None,
        typer.Option(
            '--subject',
            help='Advanced optional exact canonical Java subject override.',
        ),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option(
            '--project',
            help='Advanced optional authoritative project discovery constraint.',
        ),
    ] = None,
    depth: Annotated[
        AgentGraphDepth,
        typer.Option('--depth', help='Projection tier: story or expanded.'),
    ] = AgentGraphDepth.STORY,
) -> None:
    '''Discover story roots and export four bounded deterministic context artifacts.'''

    def operation() -> None:
        story = _read_agent_story_file(story_file).text
        loaded = _load_ai_snapshot(root, snapshot)
        session = RepositoryRuntimeSession(workspace_root=root)
        try:
            artifacts = AgentContextService(
                session,
                workspace_root=root,
            ).export(
                loaded,
                story_text=story,
                output=output,
                subject=subject,
                project=project,
                depth=depth,
            )
        finally:
            session.close()
        target = output.expanduser().resolve()
        typer.echo(f'agent-context: {target}')
        typer.echo(f'context-fingerprint: {artifacts.package.context_fingerprint}')
        typer.echo(f'graph-fingerprint: {artifacts.graph.graph_fingerprint}')
        typer.echo(
            f'graph: {len(artifacts.graph.nodes)} nodes, '
            f'{len(artifacts.graph.edges)} edges, depth={depth.value}'
        )
        resolved_roots = sum(
            item.classification == 'resolved'
            for item in artifacts.graph.discovered_roots
        )
        candidate_roots = sum(
            item.classification == 'candidate'
            for item in artifacts.graph.discovered_roots
        )
        if artifacts.graph.version >= 2:
            typer.echo(
                f'roots: {resolved_roots} authoritative, '
                f'{candidate_roots} candidate, '
                f"{artifacts.graph.omitted_counts.get('discovery_roots', 0)} omitted"
            )
        for name, size in artifacts.output_files:
            typer.echo(f'artifact: {name} ({size} bytes)')

    _run_command(operation)


@agent_app.command('review')
def agent_review_command(
    root: Annotated[
        Path,
        typer.Argument(help='Git repository root reviewed against Atlas context.'),
    ],
    context: Annotated[
        Path,
        typer.Option('--context', help='Validated Atlas context.json authority.'),
    ],
    base: Annotated[
        str,
        typer.Option('--base', help='Required pre-change Git base reference.'),
    ],
    graph: Annotated[
        Path | None,
        typer.Option(
            '--graph',
            help='Validated graph.json; defaults to the context-referenced sibling.',
        ),
    ] = None,
    snapshot: Annotated[
        Path | None,
        typer.Option('--snapshot', help='Read a specific checksum-verified .ass snapshot.'),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Print deterministic canonical review JSON.'),
    ] = False,
) -> None:
    '''Review Git scope against pre-change Atlas context without mutating source.'''

    def operation() -> None:
        resolved_root = root.expanduser().resolve()
        package = load_agent_context_package(context)
        graph_path = (
            graph.expanduser().resolve()
            if graph is not None
            else resolve_default_graph_path(context, package)
        )
        projection = load_agent_graph_projection(graph_path)
        loaded = _load_ai_snapshot(resolved_root, snapshot)
        configuration = AgentReviewConfiguration()
        git = GitDiffService(resolved_root)
        diff = git.collect(base=base)
        untracked = git.collect_untracked_paths(
            maximum_paths=configuration.maximum_changed_files
        )
        review = AgentReviewService(
            loaded,
            repository_root=resolved_root,
        ).review(
            package,
            projection,
            diff,
            untracked,
            configuration=configuration,
        )
        typer.echo(
            review.to_json() if json_output
            else render_agent_post_change_review(review),
            nl=False,
        )

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
    resolution = SnapshotResolver(
        root,
        measurement=measurement,
    ).resolve(snapshot)
    _emit_snapshot_resolution(resolution)
    return resolution.snapshot


def _emit_snapshot_resolution(resolution: SnapshotResolution) -> None:
    typer.echo(f"snapshot: {resolution.snapshot_path}", err=True)
    typer.echo(f"snapshot-resolution: {resolution.method.value}", err=True)
    typer.echo(f"snapshot-id: {resolution.snapshot.snapshot_id}", err=True)


@snapshot_app.command("activate")
def snapshot_activate_command(
    snapshot: Annotated[
        Path,
        typer.Argument(help="Exact checksum-verified .ass snapshot to activate."),
    ],
    root: Annotated[
        Path,
        typer.Option("--root", help="Workspace root bound to this registration."),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print deterministic registration metadata."),
    ] = False,
) -> None:
    """Persist one workspace-local active snapshot for read-only queries."""

    def operation() -> None:
        resolver = SnapshotResolver(root)
        resolution = resolver.activate(snapshot)
        payload = {
            **resolution.to_dict(),
            "registration_path": resolver.registration_path.as_posix(),
        }
        if json_output:
            typer.echo(json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ))
            return
        typer.echo(f"snapshot: {resolution.snapshot_path}")
        typer.echo(f"resolution: {resolution.method.value}")
        typer.echo(f"snapshot-id: {resolution.snapshot.snapshot_id}")
        typer.echo(f"workspace: {resolution.workspace_root}")
        typer.echo(f"registration: {resolver.registration_path}")

    _run_command(operation)


@snapshot_app.command("status")
def snapshot_status_command(
    root: Annotated[
        Path,
        typer.Option("--root", help="Workspace root whose query snapshot is resolved."),
    ] = Path("."),
    snapshot: Annotated[
        Path | None,
        typer.Option("--snapshot", help="Resolve one explicit snapshot instead."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print deterministic resolution metadata."),
    ] = False,
) -> None:
    """Show the exact validated snapshot a query command will consume."""

    def operation() -> None:
        resolution = SnapshotResolver(root).resolve(snapshot)
        if json_output:
            typer.echo(json.dumps(
                resolution.to_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ))
            return
        typer.echo(f"snapshot: {resolution.snapshot_path}")
        typer.echo(f"resolution: {resolution.method.value}")
        typer.echo(f"snapshot-id: {resolution.snapshot.snapshot_id}")
        typer.echo(f"workspace: {resolution.workspace_root}")

    _run_command(operation)


@app.command("change-review")
def change_review_command(
    root: Annotated[Path, typer.Argument(help="Git workspace root containing the semantic snapshot.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Read a specific .ass snapshot instead of latest.ass.")] = None,
    base: Annotated[str | None, typer.Option("--base", help="Git base revision; without --head, compare it with the working tree.")] = None,
    head: Annotated[str | None, typer.Option("--head", help="Git head revision; requires --base and is incompatible with --staged.")] = None,
    staged: Annotated[bool, typer.Option("--staged", help="Review staged Git changes.")] = False,
    change_kind: Annotated[ImpactChangeKind, typer.Option("--change-kind", help="Explicit semantic change scenario; Git metadata alone defaults to unknown.")] = ImpactChangeKind.UNKNOWN,
    maximum_files: Annotated[int, typer.Option("--max-files", min=1, max=1000, help="Maximum changed files retained for review.")] = 256,
    maximum_subjects_per_file: Annotated[int, typer.Option("--max-subjects-per-file", min=1, max=128, help="Maximum canonical subjects retained per changed file.")] = 32,
    maximum_subjects: Annotated[int, typer.Option("--max-subjects", min=1, max=128, help="Maximum canonical subjects retained across the review.")] = 64,
    impact_depth: Annotated[int, typer.Option("--impact-depth", min=1, max=64, help="Maximum PR136 impact traversal depth.")] = 4,
    impact_limit: Annotated[int, typer.Option("--impact-limit", min=1, max=1000, help="Maximum returned PR136 impact classifications.")] = 100,
    architecture_subject_limit: Annotated[int, typer.Option("--architecture-subject-limit", min=1, max=32, help="Maximum changed subjects evaluated for compatible architecture context.")] = 8,
    architecture_advice_limit: Annotated[int, typer.Option("--architecture-advice-limit", min=1, max=100, help="Maximum compatible PR137 advice items across the review.")] = 8,
    architecture: Annotated[bool, typer.Option("--architecture/--no-architecture", help="Include compatible PR137 architecture and migration context.")] = True,
    assume_current_snapshot: Annotated[bool, typer.Option("--assume-current-snapshot", help="Explicitly permit semantic enrichment without independently rescanning the workspace.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 change-review measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Change-review measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Review tracked Git changes through deterministic snapshot-backed evidence."""

    def operation() -> None:
        resolved_root = root.expanduser().resolve()
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(
                resolved_root,
                profile_output,
                default_name="latest-change-review.json",
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
                request = ChangeReviewRequest(
                    change_kind=change_kind,
                    maximum_files=maximum_files,
                    maximum_subjects_per_file=maximum_subjects_per_file,
                    maximum_subjects=maximum_subjects,
                    impact_depth=impact_depth,
                    impact_limit=impact_limit,
                    architecture_subject_limit=architecture_subject_limit,
                    architecture_advice_limit=architecture_advice_limit,
                    include_architecture=architecture,
                    assume_snapshot_current=assume_current_snapshot,
                )
                with measurement.scope(
                    "change_review.git_diff",
                    consumer="change-review",
                    sample_key="workspace",
                ) as collection:
                    diff = GitDiffService(resolved_root).collect(
                        base=base,
                        head=head,
                        staged=staged,
                    )
                    collection.add_units(len(diff.files))
                    collection.add_objects_produced(len(diff.files))
                    collection.set_objects_retained(len(diff.files))
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
                response = ChangeReviewService.from_snapshot(
                    loaded,
                    measurement=measurement,
                ).review(diff, request)
                with measurement.scope(
                    "change_review.render",
                    consumer="change-review",
                    sample_key=response.input_fingerprint,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_change_review(response)
                    )
                    rendering.add_units(
                        len(response.changed_files) + len(response.sections)
                    )
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


@app.command("evolution")
def repository_evolution_command(
    base_snapshot: Annotated[Path, typer.Option("--base-snapshot", help="Checksum-verified base .ass snapshot.")],
    root: Annotated[Path, typer.Argument(help="Workspace root containing Atlas snapshot state.")] = Path("."),
    head_snapshot: Annotated[Path | None, typer.Option("--head-snapshot", help="Checksum-verified head .ass snapshot; defaults to latest.ass.")] = None,
    maximum_node_changes: Annotated[int, typer.Option("--max-node-changes", min=1, max=5000, help="Maximum canonical node changes retained.")] = 256,
    maximum_relation_changes: Annotated[int, typer.Option("--max-relation-changes", min=1, max=5000, help="Maximum canonical relation changes retained.")] = 256,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 repository-evolution measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Repository-evolution measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Compare exact canonical facts from two verified semantic snapshots."""

    def operation() -> None:
        resolved_root = root.expanduser().resolve()
        profile_enabled = (
            profile
            or profile_output is not None
            or profile_memory
            or profile_python_memory
        )
        profile_target = (
            _measurement_output_path(
                resolved_root,
                profile_output,
                default_name="latest-repository-evolution.json",
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
                try:
                    base = _load_ai_snapshot(
                        root,
                        base_snapshot,
                        measurement=measurement,
                    )
                except SemanticSnapshotError as exc:
                    if str(exc).startswith("semantic snapshot not found:"):
                        raise SemanticSnapshotError(
                            "base semantic snapshot not found"
                        ) from exc
                    raise SemanticSnapshotError(
                        "base semantic snapshot could not be loaded or verified"
                    ) from exc
                try:
                    head = _load_ai_snapshot(
                        root,
                        head_snapshot,
                        measurement=measurement,
                    )
                except SemanticSnapshotError as exc:
                    if str(exc).startswith("semantic snapshot not found:"):
                        raise SemanticSnapshotError(
                            "head semantic snapshot not found"
                        ) from exc
                    raise SemanticSnapshotError(
                        "head semantic snapshot could not be loaded or verified"
                    ) from exc
                request = RepositoryEvolutionRequest(
                    maximum_node_changes,
                    maximum_relation_changes,
                )
                response = RepositoryEvolutionService(
                    measurement=measurement,
                ).compare(base, head, request)
                with measurement.scope(
                    "repository_evolution.render",
                    consumer="repository-evolution",
                    sample_key=response.input_fingerprint,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_repository_evolution(response)
                    )
                    rendering.add_units(
                        len(response.node_changes)
                        + len(response.relation_changes)
                        + len(response.capabilities)
                    )
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


@app.command('code-impact')
def java_code_impact_command(
    subject: Annotated[str, typer.Argument(help='Exact canonical Java method or constructor ID.')],
    root: Annotated[Path, typer.Argument(help='Workspace root containing the semantic snapshot.')] = Path('.'),
    snapshot: Annotated[Path | None, typer.Option('--snapshot', help='Read a specific .ass snapshot instead of latest.ass.')] = None,
    kind: Annotated[str | None, typer.Option('--kind', help='Constrain to method or constructor.')] = None,
    project: Annotated[str | None, typer.Option('--project', help='Constrain the owning project.')] = None,
    depth: Annotated[int, typer.Option('--depth', min=1, max=64, help='Maximum reverse upstream traversal depth.')] = 8,
    max_nodes: Annotated[int, typer.Option('--max-nodes', min=1, max=100000, help='Maximum callable nodes visited by this bounded query.')] = 4096,
    limit: Annotated[int, typer.Option('--limit', min=1, max=256, help='Maximum representatives retained per deterministic section.')] = 64,
    json_output: Annotated[bool, typer.Option('--json', help='Print canonical deterministic JSON.')] = False,
) -> None:
    '''Query evidence-backed Java callable impact without rescanning or an LLM.'''

    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        result = JavaCodeIntelligenceService.from_snapshot(loaded).query(
            subject,
            kind=kind,
            project=project,
            configuration=CodeIntelligenceConfiguration(
                max_depth=depth,
                max_nodes=max_nodes,
                max_direct_relationships=limit,
                max_paths_per_section=limit,
                max_limitation_representatives=min(limit, 16),
            ),
        )
        output = (
            result.to_json() + '\n'
            if json_output else render_code_intelligence(result)
        )
        typer.echo(output, nl=False)

    _run_command(operation)


@app.command('answer')
def engineering_answer_command(
    subject: Annotated[
        str,
        typer.Argument(
            help='Exact canonical or human-readable Java method/constructor reference.'
        ),
    ],
    root: Annotated[
        Path,
        typer.Argument(help='Workspace root containing the semantic snapshot.'),
    ] = Path('.'),
    snapshot: Annotated[
        Path | None,
        typer.Option('--snapshot', help='Read a specific .ass snapshot instead of latest.ass.'),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option('--kind', help='Constrain to method or constructor.'),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option('--project', help='Constrain the authoritative project.'),
    ] = None,
    depth: Annotated[
        int,
        typer.Option('--depth', min=1, max=64, help='Maximum existing reverse-upstream traversal depth.'),
    ] = 8,
    max_nodes: Annotated[
        int,
        typer.Option('--max-nodes', min=1, max=100000, help='Maximum callable nodes visited by PR159.'),
    ] = 4096,
    limit: Annotated[
        int,
        typer.Option('--limit', min=1, max=32, help='Maximum representatives per synthesized section.'),
    ] = 8,
    detail: Annotated[
        bool,
        typer.Option('--detail', help='Show bounded representatives and source evidence.'),
    ] = False,
    full: Annotated[
        bool,
        typer.Option('--full', help='Show the complete PR167 evidence-rich rendering.'),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option('--json', help='Print separately versioned PR167 JSON.'),
    ] = False,
) -> None:
    '''Synthesize a concise engineering answer from existing Java evidence.'''

    if detail and full:
        raise typer.BadParameter('--detail and --full are mutually exclusive')
    selected_view = (
        EngineeringAnswerView.FULL
        if full else EngineeringAnswerView.DETAIL
        if detail else EngineeringAnswerView.SUMMARY
    )

    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        runtime_session = RepositoryRuntimeSession(workspace_root=root)
        try:
            runtime = runtime_session.runtime_for(loaded)
            result = EngineeringAnswerService(
                runtime.java_code_intelligence,
                measurement=runtime.measurement,
            ).query(
                subject,
                kind=kind,
                project=project,
                configuration=EngineeringAnswerConfiguration(
                    max_depth=depth,
                    max_nodes=max_nodes,
                    max_representatives_per_section=limit,
                    max_limitation_representatives=min(limit, 4),
                    max_candidates_per_call_site=min(limit, 5),
                    max_inspect_items=min(16, max(4, limit * 2)),
                ),
            )
            output = result.to_json() + '\n' if json_output else (
                render_engineering_answer(
                    result,
                    view=selected_view,
                    name_resolver=_engineering_answer_name_resolver(
                        runtime.java_code_intelligence,
                    ),
                )
            )
            typer.echo(output, nl=False)
        finally:
            runtime_session.close()

    _run_command(operation)


@app.command('impact')
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


@app.command("debt")
def technical_debt_command(
    root: Annotated[Path, typer.Argument(help="Workspace root containing the semantic snapshot.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Read a specific .ass snapshot instead of latest.ass.")] = None,
    subject: Annotated[str, typer.Option("--subject", help="Canonical subject ID or exact repository subject name.")] = "repository",
    kind: Annotated[str | None, typer.Option("--kind", help="Constrain the canonical subject kind.")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Constrain the owning project.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="Constrain the analyzer language.")] = None,
    path_constraint: Annotated[str | None, typer.Option("--path", help="Constrain a workspace-relative subject path.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum returned debt observations.")] = 20,
    candidate_limit: Annotated[int, typer.Option("--candidate-limit", min=1, max=256, help="Maximum verified cycle seams evaluated before output ranking.")] = 100,
    impact_depth: Annotated[int, typer.Option("--impact-depth", min=1, max=64, help="Maximum PR136 represented-impact depth.")] = 4,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 technical-debt measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Technical-debt measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Rank evidence-backed dependency-cycle debt observations."""

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
                default_name="latest-debt.json",
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
                request = TechnicalDebtRequest(
                    SubjectQuery(
                        subject,
                        selected_kind,
                        project,
                        language,
                        path_constraint,
                    ),
                    limit=limit,
                    candidate_limit=candidate_limit,
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
                response = TechnicalDebtService.from_snapshot(
                    loaded, measurement=measurement,
                ).analyze(request)
                with measurement.scope(
                    "technical_debt.render",
                    consumer="technical-debt",
                    sample_key=response.input_fingerprint,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_technical_debt(response)
                    )
                    rendering.add_units(response.returned_count)
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


@app.command("security")
def security_intelligence_command(
    root: Annotated[Path, typer.Argument(help="Workspace root containing the semantic snapshot.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Read a specific .ass snapshot instead of latest.ass.")] = None,
    scope: Annotated[str, typer.Option("--scope", help="Security scope: repository, project, or symbol.")] = "repository",
    project: Annotated[list[str] | None, typer.Option("--project", help="Restrict an owning project; repeat as needed.")] = None,
    language: Annotated[list[str] | None, typer.Option("--language", help="Restrict a producer language; repeat as needed.")] = None,
    category: Annotated[list[str] | None, typer.Option("--category", help="Restrict a security category; repeat as needed.")] = None,
    severity: Annotated[list[str] | None, typer.Option("--severity", help="Restrict a severity; repeat as needed.")] = None,
    subject_id: Annotated[list[str] | None, typer.Option("--subject-id", help="Restrict a canonical subject ID; repeat as needed and required for symbol scope.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=10000, help="Maximum returned security findings.")] = 100,
    json_output: Annotated[bool, typer.Option("--json", help="Print canonical deterministic JSON.")] = False,
    explain_priority: Annotated[bool, typer.Option("--explain-priority", help="Show deterministic priority components.")] = False,
    profile: Annotated[bool, typer.Option("--profile", help="Write an opt-in M2 security-intelligence measurement sidecar.")] = False,
    profile_output: Annotated[Path | None, typer.Option("--profile-output", help="Security measurement JSON path; implies --profile.")] = None,
    profile_memory: Annotated[bool, typer.Option("--profile-memory", help="Collect best-effort process memory counters; implies --profile.")] = False,
    profile_python_memory: Annotated[bool, typer.Option("--profile-python-memory", help="Collect Python allocation samples; implies --profile.")] = False,
) -> None:
    """Query persisted evidence-backed security intelligence without rescanning source."""

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
                default_name="latest-security.json",
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
                selected_scope = SecurityScope(
                    scope.strip().casefold().replace("-", "_")
                )
                request = SecurityIntelligenceRequest(
                    selected_scope,
                    projects=tuple(project or ()),
                    languages=tuple(language or ()),
                    categories=tuple(
                        SecurityCategory(item.strip().casefold().replace("-", "_"))
                        for item in (category or ())
                    ),
                    severities=tuple(
                        SecuritySeverity(item.strip().casefold().replace("-", "_"))
                        for item in (severity or ())
                    ),
                    limit=limit,
                    canonical_subject_ids=tuple(subject_id or ()),
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
                response = SecurityIntelligenceService.from_snapshot(
                    loaded, measurement=measurement,
                ).analyze(request)
                with measurement.scope(
                    "security_intelligence.render",
                    consumer="security-intelligence",
                    sample_key=response.input_fingerprint,
                ) as rendering:
                    output = (
                        response.to_json() + "\n"
                        if json_output
                        else render_security_intelligence(
                            response, explain_priority=explain_priority,
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


@ai_app.command("chat")
@ai_app.command("ask")
def ai_ask_command(
    question: Annotated[str, typer.Argument(help="Question about the workspace.")],
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    snapshot: Annotated[Path | None, typer.Option("--snapshot", help="Specific .ass snapshot.")] = None,
    conversation_id: Annotated[int | None, typer.Option("--conversation", help="Continue one workspace-scoped conversation.")] = None,
    subject: Annotated[str | None, typer.Option("--subject", help="Canonical subject or exact semantic identity.")] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="Constrain the canonical subject kind.")] = None,
    project: Annotated[str | None, typer.Option("--project", help="Constrain the owning project.")] = None,
    language: Annotated[str | None, typer.Option("--language", help="Constrain the subject language.")] = None,
    capability: Annotated[list[str] | None, typer.Option("--capability", help="Request impact, refactoring, or security enrichment.")] = None,
    history_limit: Annotated[int, typer.Option("--history-limit", min=0, help="Maximum prior messages retained in context.")] = 12,
    result_limit: Annotated[int, typer.Option("--limit", min=1, max=20, help="Maximum findings or semantic hits per capability.")] = 8,
    maximum_input_tokens: Annotated[int, typer.Option("--max-input-tokens", min=1024, help="Deterministic provider input ceiling.")] = 7000,
    json_output: Annotated[bool, typer.Option("--json", help="Print the structured grounded response envelope.")] = False,
) -> None:
    """Ask a grounded engineering question about an ASS artifact."""
    if not question.strip():
        typer.echo("error: question must not be empty", err=True)
        raise typer.Exit(code=2)
    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        provider = (_ai_provider_factory or OllamaProvider)()
        try:
            result = AskEngine(LlmClient(provider), memory=ConversationMemoryStore(root)).ask(
                loaded,
                AskRequest(
                    question,
                    conversation_id,
                    history_limit,
                    subject,
                    kind,
                    project,
                    language,
                    tuple(capability or ()),
                    maximum_input_tokens,
                    result_limit,
                ),
            )
            if json_output:
                typer.echo(result.to_json())
            else:
                typer.echo(result.answer)
                grounding = result.grounding_summary
                if grounding is None:
                    if not result.grounded:
                        typer.echo(
                            "warning: provider grounding citations were incomplete; "
                            "use --json for validation details",
                            err=True,
                        )
                elif not grounding.delivered_answer_grounded:
                    typer.echo(
                        "warning: delivered answer grounding is incomplete; "
                        "use --json for validation details",
                        err=True,
                    )
                elif not grounding.request_complete:
                    omitted = (
                        ", ".join(grounding.omitted_requested_capabilities)
                        or "one or more required dimensions"
                    )
                    typer.echo(
                        "notice: Atlas returned a grounded but incomplete answer; "
                        f"omitted requested dimensions: {omitted}; "
                        "use --json for status details",
                        err=True,
                    )
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


def _runtime_statistics_json(
    session: RepositoryRuntimeSession,
    engineering_provider: EngineeringProviderTelemetry | None = None,
) -> str:
    statistics = session.statistics
    payload = {
        'runtime_build_count': statistics.runtime_build_count,
        'reuse_count': statistics.reuse_count,
        'component_build_counts': dict(statistics.component_build_counts),
        'snapshot_id': (
            statistics.current_identity.snapshot_id
            if statistics.current_identity is not None else None
        ),
    }
    if engineering_provider is not None:
        payload['engineering_provider'] = engineering_provider.to_dict()
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    )


_SESSION_SEARCH_DEFAULT_LIMIT = 10
_SESSION_SEARCH_MAXIMUM_LIMIT = 20
_SESSION_REQUEST_MAXIMUM_CHARACTERS = 3_000
_SESSION_REQUEST_MAXIMUM_BYTES = _SESSION_REQUEST_MAXIMUM_CHARACTERS * 4
_AGENT_STORY_MAXIMUM_CHARACTERS = 50_000
_AGENT_STORY_MAXIMUM_BYTES = 256 * 1024
_SESSION_SEARCH_CONFIGURATION = CodeIntelligenceConfiguration(
    max_depth=1,
    max_nodes=1,
    max_direct_relationships=1,
    max_paths_per_section=1,
    max_limitation_representatives=1,
    max_resolution_candidates=1,
    max_candidates_per_call_site=1,
)


@dataclass(frozen=True, slots=True)
class _SessionFileInput:
    path: Path
    text: str
    byte_count: int


class _SessionStoryBuffer:
    '''Bounded multiline text retained until explicit submission or cancellation.'''

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._character_count = 0
        self._overflowed = False

    @property
    def character_count(self) -> int:
        return self._character_count

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    def append(self, line: str) -> None:
        if not isinstance(line, str):
            raise TypeError('story input line must be text')
        if self._overflowed:
            return
        added = len(line) + (1 if self._lines else 0)
        if self._character_count + added > _SESSION_REQUEST_MAXIMUM_CHARACTERS:
            self._lines.clear()
            self._overflowed = True
            return
        self._lines.append(line)
        self._character_count += added

    def finish(self) -> str:
        if self._overflowed:
            raise ValueError(
                'story exceeds the accepted maximum of '
                f'{_SESSION_REQUEST_MAXIMUM_CHARACTERS} characters; '
                'nothing was submitted'
            )
        return _validate_session_request_text(
            '\n'.join(self._lines),
            label='story',
        )


class _SessionStoryState:
    '''Disposable normalized story and deterministic in-session plan cache.'''

    def __init__(self) -> None:
        self._text: str | None = None
        self._fingerprint: str | None = None
        self._plans: dict[str, StoryPlan] = {}

    @property
    def text(self) -> str | None:
        return self._text

    @property
    def fingerprint(self) -> str | None:
        return self._fingerprint

    def load(self, text: str) -> None:
        normalized = normalize_story_text(text)
        self._text = normalized
        self._fingerprint = story_fingerprint(normalized)
        self._plans.clear()

    def plan(self, request: StoryPlanningRequest) -> StoryPlan | None:
        return self._plans.get(request.plan_fingerprint)

    def retain(self, plan: StoryPlan) -> None:
        self._plans[plan.plan_fingerprint] = plan


def _validate_session_request_text(text: str, *, label: str) -> str:
    if not isinstance(text, str):
        raise TypeError('session request input must be text')
    if len(text) > _SESSION_REQUEST_MAXIMUM_CHARACTERS:
        raise ValueError(
            f'{label} contains {len(text)} characters; accepted maximum is '
            f'{_SESSION_REQUEST_MAXIMUM_CHARACTERS} characters'
        )
    if not text.strip():
        raise ValueError(f'{label} is blank; nothing was submitted')
    if any(
        (ord(character) < 32 and character not in {'\t', '\n', '\r'})
        or ord(character) == 127
        for character in text
    ):
        raise ValueError(f'{label} is not UTF-8 plain text')
    return text


def _parse_session_file_path(line: str, command: str) -> Path:
    payload = line.removeprefix(command).strip()
    if not payload:
        raise ValueError(f'usage: {command} <path>')
    if (
        len(payload) >= 2
        and payload[0] == payload[-1]
        and payload[0] in {chr(39), chr(34)}
    ):
        payload = payload[1:-1]
    if not payload:
        raise ValueError(f'usage: {command} <path>')
    return Path(payload)


def _read_session_request_file(path: Path) -> _SessionFileInput:
    try:
        metadata = path.stat()
    except FileNotFoundError as exc:
        raise ValueError(f'input file does not exist: {path}') from exc
    except OSError as exc:
        raise ValueError(f'input file is not readable: {path}') from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f'input path is not a regular file: {path}')
    if metadata.st_size > _SESSION_REQUEST_MAXIMUM_BYTES:
        raise ValueError(
            f'input file contains {metadata.st_size} bytes; accepted maximum is '
            f'{_SESSION_REQUEST_MAXIMUM_BYTES} bytes and '
            f'{_SESSION_REQUEST_MAXIMUM_CHARACTERS} characters'
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f'input file is not readable: {path}') from exc
    if len(payload) > _SESSION_REQUEST_MAXIMUM_BYTES:
        raise ValueError(
            f'input file contains {len(payload)} bytes; accepted maximum is '
            f'{_SESSION_REQUEST_MAXIMUM_BYTES} bytes and '
            f'{_SESSION_REQUEST_MAXIMUM_CHARACTERS} characters'
        )
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('input file is not valid UTF-8 plain text') from exc
    return _SessionFileInput(
        path,
        _validate_session_request_text(text, label='input file'),
        len(payload),
    )


def _read_agent_story_file(path: Path) -> _SessionFileInput:
    try:
        metadata = path.stat()
    except FileNotFoundError as exc:
        raise ValueError(f'agent story file does not exist: {path}') from exc
    except OSError as exc:
        raise ValueError(f'agent story file is not readable: {path}') from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f'agent story path is not a regular file: {path}')
    if metadata.st_size > _AGENT_STORY_MAXIMUM_BYTES:
        raise ValueError(
            f'agent story file contains {metadata.st_size} bytes; accepted maximum '
            f'is {_AGENT_STORY_MAXIMUM_BYTES} bytes (256 KiB)'
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError(f'agent story file is not readable: {path}') from exc
    if len(payload) > _AGENT_STORY_MAXIMUM_BYTES:
        raise ValueError(
            f'agent story file contains {len(payload)} bytes; accepted maximum '
            f'is {_AGENT_STORY_MAXIMUM_BYTES} bytes (256 KiB)'
        )
    try:
        text = payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('agent story file is not valid UTF-8 plain text') from exc
    normalized = normalize_story_text(text)
    if len(normalized) > _AGENT_STORY_MAXIMUM_CHARACTERS:
        raise ValueError(
            f'agent story contains {len(normalized)} normalized characters; '
            f'accepted maximum is {_AGENT_STORY_MAXIMUM_CHARACTERS} characters'
        )
    if any(
        (ord(character) < 32 and character not in {'\t', '\n'})
        or ord(character) == 127
        for character in normalized
    ):
        raise ValueError('agent story file is not UTF-8 plain text')
    return _SessionFileInput(path, normalized, len(payload))


@dataclass(frozen=True, slots=True)
class _SessionSearchResult:
    canonical_subject_id: str
    project: str | None
    qualified_name: str
    kind: str
    language: str
    exact_java_method: bool = False


class _SessionSubjectDiscovery:
    '''Bounded, non-semantic selection state for one interactive session.'''

    def __init__(self) -> None:
        self._results: tuple[_SessionSearchResult, ...] = ()

    @property
    def results(self) -> tuple[_SessionSearchResult, ...]:
        return self._results

    def replace(self, results: tuple[_SessionSearchResult, ...]) -> None:
        if len(results) > _SESSION_SEARCH_MAXIMUM_LIMIT:
            raise ValueError('session search result state exceeds its bound')
        self._results = tuple(results)

    def select(self, ordinal: int) -> _SessionSearchResult:
        if not self._results:
            raise ValueError('run /search before /use')
        if ordinal < 1 or ordinal > len(self._results):
            raise ValueError(
                f'search result must be between 1 and {len(self._results)}'
            )
        return self._results[ordinal - 1]

    def clear(self) -> None:
        self._results = ()


def _parse_session_search(line: str) -> tuple[str, int]:
    payload = line.removeprefix('/search').strip()
    if not payload:
        raise ValueError('usage: /search <text> [limit]')
    query = payload
    limit = _SESSION_SEARCH_DEFAULT_LIMIT
    parts = payload.rsplit(maxsplit=1)
    if len(parts) == 2:
        candidate = parts[1]
        explicit_limit = candidate.startswith('limit=')
        raw_limit = candidate.removeprefix('limit=') if explicit_limit else candidate
        numeric_limit = raw_limit.lstrip('+-').isdigit()
        if explicit_limit or numeric_limit:
            if not numeric_limit:
                raise ValueError('search limit must be an integer between 1 and 20')
            query = parts[0].strip()
            limit = int(raw_limit)
    if not query:
        raise ValueError('usage: /search <text> [limit]')
    if not 1 <= limit <= _SESSION_SEARCH_MAXIMUM_LIMIT:
        raise ValueError('search limit must be between 1 and 20')
    return query, limit


def _authoritative_session_search_result(runtime, hit) -> _SessionSearchResult:
    projected = (
        hit
        if isinstance(hit, _SessionSearchResult)
        else _SessionSearchResult(
            hit.canonical_subject_id,
            hit.project,
            hit.qualified_name,
            hit.kind.value,
            hit.language,
        )
    )
    if projected.canonical_subject_id.startswith(('method:', 'constructor:')):
        java = runtime.java_code_intelligence.query(
            projected.canonical_subject_id,
            configuration=_SESSION_SEARCH_CONFIGURATION,
        )
        subject = java.resolution.subject
        if (
            java.resolution.status is CodeSubjectResolutionStatus.RESOLVED
            and subject is not None
        ):
            parameters = subject.normalized_key.rpartition('(')[2].removesuffix(')')
            parameter_display = '...' if parameters else ''
            qualified_name = (
                f'{subject.owner_type}#{subject.name}({parameter_display})'
            )
            return _SessionSearchResult(
                subject.canonical_id,
                subject.project,
                qualified_name,
                subject.kind.value,
                'java',
                subject.kind.value == 'method',
            )
    return projected


def _exact_session_search(
    runtime,
    query: str,
) -> tuple[_SessionSearchResult, ...] | None:
    '''Resolve the exact-identity branch without projecting the full search index.'''

    request = SemanticSearchRequest(query, limit=1)
    interpretation = interpret_query(request)
    if (
        interpretation.intents != (SearchIntent.EXACT_IDENTITY,)
        or interpretation.concepts
        or interpretation.subject_terms
        or interpretation.relation is not None
        or interpretation.filters
        or interpretation.ambiguous
    ):
        return None
    resolution = runtime.resolver.resolve(SubjectQuery(query))
    if (
        resolution.status is not ResolutionStatus.RESOLVED
        or resolution.subject is None
    ):
        return None
    subject = resolution.subject
    return (_authoritative_session_search_result(
        runtime,
        _SessionSearchResult(
            subject.canonical_id,
            subject.project,
            subject.qualified_name,
            subject.kind.value,
            subject.language,
        ),
    ),)


def _emit_session_search_results(
    results: tuple[_SessionSearchResult, ...],
    *,
    total_candidate_count: int,
    omitted_count: int,
) -> None:
    if not results:
        typer.echo('No canonical subjects found.')
        return
    for ordinal, result in enumerate(results, start=1):
        project = result.project or 'unknown'
        typer.echo(
            f'{ordinal}.\n'
            f'  id: {result.canonical_subject_id}\n'
            f'  project: {project}\n'
            f'  name: {result.qualified_name}\n'
            f'  kind: {result.kind}\n'
            f'  language: {result.language}'
        )
    typer.echo(f'showing {len(results)} of {total_candidate_count} results')
    if omitted_count:
        typer.echo(
            'request more with /search <text> <limit> (maximum 20)'
        )


def _session_search(
    session: RepositoryRuntimeSession,
    snapshot,
    query: str,
    limit: int,
) -> tuple[_SessionSearchResult, ...]:
    runtime = session.runtime_for(snapshot)
    exact = _exact_session_search(runtime, query)
    if exact is not None:
        _emit_session_search_results(
            exact,
            total_candidate_count=1,
            omitted_count=0,
        )
        return exact
    response = runtime.semantic_search.search_semantic(
        SemanticSearchRequest(query, limit=limit),
    )
    results = tuple(
        _authoritative_session_search_result(runtime, hit)
        for hit in response.hits
    )
    _emit_session_search_results(
        results,
        total_candidate_count=response.total_candidate_count,
        omitted_count=response.omitted_count,
    )
    return results


def _session_use(
    session: RepositoryRuntimeSession,
    snapshot,
    selection: _SessionSearchResult,
) -> tuple[str, str]:
    if not selection.exact_java_method or selection.project is None:
        raise ValueError(
            'selected result is not an exact represented Java method'
        )
    result = session.runtime_for(snapshot).java_code_intelligence.query(
        selection.canonical_subject_id,
        kind='method',
        project=selection.project,
        configuration=_SESSION_SEARCH_CONFIGURATION,
    )
    subject = result.resolution.subject
    if (
        result.resolution.status is not CodeSubjectResolutionStatus.RESOLVED
        or subject is None
        or subject.canonical_id != selection.canonical_subject_id
        or subject.project != selection.project
    ):
        raise ValueError(
            'selected result no longer matches authoritative Java identity'
        )
    return subject.canonical_id, subject.project


def _session_explain(
    engine: ExplainEngine,
    snapshot,
    subject: str | None,
    project: str | None,
    language: str | None,
) -> None:
    if subject is None:
        typer.echo('error: set an exact subject with /subject first', err=True)
        return
    result = engine.explain(
        snapshot,
        ExplainRequest(
            subject=subject,
            kind='method',
            project=project,
            language=language,
            narrative=False,
        ),
    )
    typer.echo(result.markdown)


def _session_impact(
    session: RepositoryRuntimeSession,
    snapshot,
    subject: str | None,
    project: str | None,
    result_limit: int,
) -> None:
    if subject is None:
        typer.echo('error: set an exact subject with /subject first', err=True)
        return
    result = session.runtime_for(snapshot).java_code_intelligence.query(
        subject,
        project=project,
        configuration=CodeIntelligenceConfiguration(
            max_depth=8,
            max_nodes=4_096,
            max_direct_relationships=result_limit,
            max_paths_per_section=result_limit,
            max_limitation_representatives=min(result_limit, 16),
        ),
    )
    typer.echo(render_code_intelligence(result), nl=False)


def _engineering_answer_name_resolver(
    service: JavaCodeIntelligenceService,
) -> EngineeringAnswerNameResolver:
    index = service.callable_index
    entries = index.entries if index is not None else ()

    def resolve(canonical_id: str) -> str | None:
        lower = 0
        upper = len(entries)
        while lower < upper:
            middle = (lower + upper) // 2
            candidate = entries[middle]
            if candidate.canonical_subject_id < canonical_id:
                lower = middle + 1
            else:
                upper = middle
        if (
            lower < len(entries)
            and entries[lower].canonical_subject_id == canonical_id
        ):
            return entries[lower].identity.normalized_key
        return None

    return resolve


def _session_answer(
    session: RepositoryRuntimeSession,
    snapshot,
    subject: str | None,
    project: str | None,
    result_limit: int,
    view: EngineeringAnswerView,
) -> None:
    if subject is None:
        typer.echo('error: set an exact subject with /subject first', err=True)
        return
    runtime = session.runtime_for(snapshot)
    result = EngineeringAnswerService(
        runtime.java_code_intelligence,
        measurement=runtime.measurement,
    ).query(
        subject,
        project=project,
        configuration=EngineeringAnswerConfiguration(
            max_depth=8,
            max_nodes=4_096,
            max_representatives_per_section=result_limit,
            max_limitation_representatives=min(result_limit, 4),
            max_candidates_per_call_site=min(result_limit, 5),
            max_inspect_items=min(16, max(4, result_limit * 2)),
        ),
    )
    typer.echo(
        render_engineering_answer(
            result,
            view=view,
            name_resolver=_engineering_answer_name_resolver(
                runtime.java_code_intelligence,
            ),
        ),
        nl=False,
    )


def _session_ask(
    engine: AskEngine,
    snapshot,
    question: str,
    conversation_id: int | None,
    subject: str | None,
    project: str | None,
    language: str | None,
    capability: list[str] | None,
    maximum_input_tokens: int,
    result_limit: int,
) -> int | None:
    try:
        result = engine.ask(
            snapshot,
            AskRequest(
                question,
                conversation_id,
                12,
                subject,
                None,
                project,
                language,
                tuple(capability or ()),
                maximum_input_tokens,
                result_limit,
            ),
        )
    except (LlmProviderError, ValueError) as exc:
        typer.echo(f'error: {exc}', err=True)
        return conversation_id
    typer.echo(result.answer)
    return result.conversation_id


def _session_plan(
    planner: StoryPlanningService,
    snapshot,
    state: _SessionStoryState,
    subject: str | None,
    project: str | None,
    view: StoryPlanView,
) -> StoryPlan | None:
    if state.text is None:
        typer.echo(
            'error: no story loaded; use /story or /story-file first',
            err=True,
        )
        return None
    request = StoryPlanningRequest(
        state.text,
        snapshot.snapshot_id,
        subject,
        project,
    )
    plan = state.plan(request)
    if plan is None:
        plan = planner.plan(snapshot, request)
        state.retain(plan)
    typer.echo(render_story_plan(plan, view=view), nl=False)
    return plan


def _current_session_story_plan(
    snapshot,
    state: _SessionStoryState,
    subject: str | None,
    project: str | None,
) -> StoryPlan | None:
    if state.text is None:
        return None
    return state.plan(StoryPlanningRequest(
        state.text,
        snapshot.snapshot_id,
        subject,
        project,
    ))


@ai_app.command('session')
def ai_session_command(
    root: Annotated[Path, typer.Argument(help='Workspace root.')] = Path('.'),
    snapshot: Annotated[
        Path | None,
        typer.Option('--snapshot', help='Specific validated .ass snapshot.'),
    ] = None,
    subject: Annotated[
        str | None,
        typer.Option('--subject', help='Initial exact canonical subject.'),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option('--project', help='Initial authoritative project constraint.'),
    ] = None,
    language: Annotated[
        str | None,
        typer.Option('--language', help='Subject language constraint.'),
    ] = 'java',
    capability: Annotated[
        list[str] | None,
        typer.Option('--capability', help='Capability requested on each Ask turn.'),
    ] = None,
    result_limit: Annotated[
        int,
        typer.Option('--limit', min=1, max=20),
    ] = 8,
    maximum_input_tokens: Annotated[
        int,
        typer.Option('--max-input-tokens', min=1024),
    ] = 7000,
) -> None:
    '''Run the experimental engineering-agent runtime over a validated snapshot.'''

    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        provider = (_ai_provider_factory or OllamaProvider)()
        runtime_session = RepositoryRuntimeSession(workspace_root=root)
        discovery = _SessionSubjectDiscovery()
        current_subject = subject
        current_project = project
        conversation_id = None
        story_buffer: _SessionStoryBuffer | None = None
        story_state = _SessionStoryState()
        engineering_proposal: EngineeringPatchProposal | None = None
        try:
            context_builder = EngineeringChatContextBuilder(
                runtime_session=runtime_session,
            )
            ask_engine = AskEngine(
                LlmClient(provider),
                memory=ConversationMemoryStore(root),
                context_builder=context_builder,
            )
            explain_engine = ExplainEngine(runtime_session=runtime_session)
            story_planner = StoryPlanningService(
                runtime_session,
                workspace_root=root,
                llm_client=LlmClient(provider),
            )
            engineering_agent = EngineeringAgentRuntime(
                runtime_session,
                workspace_root=root,
                llm_client=LlmClient(
                    provider,
                    RetryPolicy(maximum_attempts=1, timeout_seconds=120.0),
                ),
            )
            typer.echo(
                'Experimental engineering-agent runtime ready. Use /help, '
                '/search, /subject, /project, '
                '/ask-file, /story, /plan [detail], /implement, /apply, '
                '/verify, /diff, /answer [detail|full], /explain, /impact, '
                '/stats, or /exit.'
            )
            while True:
                if story_buffer is not None:
                    raw_line = typer.prompt(
                        'story',
                        default='',
                        show_default=False,
                        prompt_suffix='> ',
                    )
                else:
                    raw_line = typer.prompt('atlas', prompt_suffix='> ')
                line = raw_line.strip()
                if story_buffer is not None:
                    if line == '/cancel':
                        story_buffer = None
                        typer.echo('story canceled; no request submitted.')
                        continue
                    if line == '/end':
                        completed_story = story_buffer
                        story_buffer = None
                        try:
                            question = completed_story.finish()
                        except ValueError as exc:
                            typer.echo(f'error: {exc}', err=True)
                            continue
                        typer.echo(
                            f'story loaded: {len(question)} characters'
                        )
                        story_state.load(question)
                        typer.echo(
                            'processing story against current subject...'
                        )
                        _session_ask(
                            ask_engine, loaded, question, None,
                            current_subject, current_project, language,
                            capability, maximum_input_tokens, result_limit,
                        )
                        continue
                    story_buffer.append(raw_line)
                    continue
                if not line:
                    continue
                if line in {'/exit', '/quit'}:
                    discovery.clear()
                    typer.echo('Atlas session closed.')
                    break
                if line == '/help':
                    typer.echo(
                        '/search <text> [limit] find canonical subjects; '
                        '/use <n> select a Java method from the latest search; '
                        '/subject <canonical-id>; /project <project>; '
                        '/ask-file <path> ask using a text file as one request; '
                        '/story enter multiline story mode; finish with /end; '
                        '/story-file <path> load a story from a text file; '
                        '/plan [detail] reconcile the loaded story with repository evidence; '
                        '/implement [experimental] create a preview-only bounded patch proposal; '
                        '/apply [experimental] apply only inside an isolated linked Git worktree; '
                        '/verify [experimental] show validation commands without running them; '
                        '/diff review current changes against the proposal; '
                        '/cancel cancel multiline story entry; '
                        '/answer [summary|detail|full]; /explain; /impact; '
                        '/stats; /exit; or enter a question.'
                    )
                    continue
                if line == '/story':
                    story_buffer = _SessionStoryBuffer()
                    typer.echo(
                        'story mode: enter text; finish with /end or discard '
                        'with /cancel.'
                    )
                    continue
                if line in {'/end', '/cancel'}:
                    typer.echo(
                        f'error: {line} is available only in story mode',
                        err=True,
                    )
                    continue
                if line == '/ask-file' or line.startswith('/ask-file '):
                    try:
                        file_input = _read_session_request_file(
                            _parse_session_file_path(line, '/ask-file')
                        )
                    except ValueError as exc:
                        typer.echo(f'error: {exc}', err=True)
                        continue
                    typer.echo(
                        f'request loaded: {len(file_input.text)} characters '
                        f'({file_input.byte_count} bytes)'
                    )
                    typer.echo(
                        'processing request against current subject...'
                    )
                    _session_ask(
                        ask_engine, loaded, file_input.text, None,
                        current_subject, current_project, language,
                        capability, maximum_input_tokens, result_limit,
                    )
                    continue
                if line == '/story-file' or line.startswith('/story-file '):
                    try:
                        file_input = _read_session_request_file(
                            _parse_session_file_path(line, '/story-file')
                        )
                    except ValueError as exc:
                        typer.echo(f'error: {exc}', err=True)
                        continue
                    typer.echo(
                        f'story loaded: {len(file_input.text)} characters '
                        f'({file_input.byte_count} bytes)'
                    )
                    story_state.load(file_input.text)
                    typer.echo(
                        'processing story against current subject...'
                    )
                    _session_ask(
                        ask_engine, loaded, file_input.text, None,
                        current_subject, current_project, language,
                        capability, maximum_input_tokens, result_limit,
                    )
                    continue
                if line == '/plan' or line.startswith('/plan '):
                    raw_view = line.removeprefix('/plan').strip() or 'summary'
                    try:
                        plan_view = StoryPlanView(raw_view.casefold())
                    except ValueError:
                        typer.echo(
                            'error: usage: /plan [detail]',
                            err=True,
                        )
                    else:
                        try:
                            _session_plan(
                                story_planner,
                                loaded,
                                story_state,
                                current_subject,
                                current_project,
                                plan_view,
                            )
                        except ValueError as exc:
                            typer.echo(f'error: {exc}', err=True)
                    continue
                if line == '/implement':
                    if story_state.text is None:
                        typer.echo(
                            'error: no story loaded; use /story or /story-file first',
                            err=True,
                        )
                        continue
                    current_plan = _current_session_story_plan(
                        loaded,
                        story_state,
                        current_subject,
                        current_project,
                    )
                    if current_plan is None:
                        typer.echo(
                            'error: no current story plan; run /plan first',
                            err=True,
                        )
                        continue
                    try:
                        proposed = engineering_agent.propose(loaded, current_plan)
                    except (EngineeringAgentError, EngineeringProviderFailure) as exc:
                        typer.echo(f'error: {exc}', err=True)
                    else:
                        engineering_proposal = proposed
                        typer.echo(
                            render_implementation_proposal(proposed),
                            nl=False,
                        )
                    continue
                if line == '/apply':
                    if engineering_proposal is None:
                        typer.echo(
                            'error: no validated implementation proposal; run /implement first',
                            err=True,
                        )
                        continue
                    current_plan = _current_session_story_plan(
                        loaded,
                        story_state,
                        current_subject,
                        current_project,
                    )
                    if current_plan is None:
                        typer.echo(
                            'error: implementation proposal is stale; run /plan and /implement again',
                            err=True,
                        )
                        continue
                    try:
                        applied = engineering_agent.apply(
                            current_plan,
                            engineering_proposal,
                        )
                    except (EngineeringAgentError, EngineeringApplyError) as exc:
                        typer.echo(f'error: {exc}', err=True)
                    else:
                        typer.echo(render_apply_result(applied), nl=False)
                    continue
                if line == '/verify' or line.startswith('/verify '):
                    option = line.removeprefix('/verify').strip()
                    if option not in {'', 'run'}:
                        typer.echo('error: usage: /verify [run]', err=True)
                        continue
                    current_plan = _current_session_story_plan(
                        loaded,
                        story_state,
                        current_subject,
                        current_project,
                    )
                    if current_plan is None:
                        typer.echo(
                            'error: no current story plan; run /plan first',
                            err=True,
                        )
                        continue
                    verification = engineering_agent.verification_plan(current_plan)
                    typer.echo(render_verification_plan(verification), nl=False)
                    if option == 'run':
                        typer.echo(
                            'error: /verify run is intentionally unavailable in PR173; '
                            'review and run the displayed argv explicitly',
                            err=True,
                        )
                    continue
                if line == '/diff':
                    if engineering_proposal is None:
                        typer.echo(
                            'error: no validated implementation proposal; run /implement first',
                            err=True,
                        )
                        continue
                    current_plan = _current_session_story_plan(
                        loaded,
                        story_state,
                        current_subject,
                        current_project,
                    )
                    if current_plan is None:
                        typer.echo(
                            'error: implementation proposal is stale; run /plan and /implement again',
                            err=True,
                        )
                        continue
                    try:
                        report = engineering_agent.diff_report(
                            current_plan,
                            engineering_proposal,
                        )
                    except (EngineeringAgentError, EngineeringApplyError) as exc:
                        typer.echo(f'error: {exc}', err=True)
                    else:
                        typer.echo(render_engineering_diff(report), nl=False)
                    continue
                if line == '/search' or line.startswith('/search '):
                    discovery.clear()
                    try:
                        query, search_limit = _parse_session_search(line)
                        discovery.replace(_session_search(
                            runtime_session, loaded, query, search_limit,
                        ))
                    except ValueError as exc:
                        typer.echo(f'error: {exc}', err=True)
                    continue
                if line == '/use' or line.startswith('/use '):
                    try:
                        raw_ordinal = line.removeprefix('/use').strip()
                        if not raw_ordinal or not raw_ordinal.isdigit():
                            raise ValueError('usage: /use <result-number>')
                        selection = discovery.select(int(raw_ordinal))
                        selected_subject, selected_project = _session_use(
                            runtime_session, loaded, selection,
                        )
                    except ValueError as exc:
                        typer.echo(f'error: {exc}', err=True)
                    else:
                        current_subject = selected_subject
                        current_project = selected_project
                        typer.echo(f'subject={current_subject}')
                        typer.echo(f'project={current_project}')
                    continue
                if line.startswith('/subject '):
                    current_subject = line.removeprefix('/subject ').strip() or None
                    typer.echo('subject=' + (current_subject or 'none'))
                    continue
                if line.startswith('/project '):
                    current_project = line.removeprefix('/project ').strip() or None
                    typer.echo('project=' + (current_project or 'none'))
                    continue
                if line == '/stats':
                    typer.echo(_runtime_statistics_json(
                        runtime_session,
                        engineering_agent.telemetry,
                    ))
                    continue
                if line == '/explain':
                    _session_explain(
                        explain_engine, loaded, current_subject,
                        current_project, language,
                    )
                    continue
                if line == '/impact':
                    _session_impact(
                        runtime_session, loaded, current_subject,
                        current_project, result_limit,
                    )
                    continue
                if line == '/answer' or line.startswith('/answer '):
                    raw_view = line.removeprefix('/answer').strip() or 'summary'
                    try:
                        answer_view = EngineeringAnswerView(raw_view.casefold())
                    except ValueError:
                        typer.echo(
                            'error: usage: /answer [summary|detail|full]',
                            err=True,
                        )
                    else:
                        _session_answer(
                            runtime_session, loaded, current_subject,
                            current_project, result_limit, answer_view,
                        )
                    continue
                question = line.removeprefix('/ask ').strip()
                conversation_id = _session_ask(
                    ask_engine, loaded, question, conversation_id,
                    current_subject, current_project, language,
                    capability, maximum_input_tokens, result_limit,
                )
        finally:
            discovery.clear()
            runtime_session.close()
            close = getattr(provider, 'close', None)
            if callable(close):
                close()

    _run_command(operation)


def main() -> None:
    """Run the unified Atlas CLI."""
    app()


if __name__ == "__main__":
    main()
