"""Unified Atlas command-line interface introduced in PR75."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import logging
from pathlib import Path
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
from .adaptive_scheduler import AdaptiveWorkspaceScheduler
from .governance import GovernanceAuditLog, GovernanceError
from .structured_logging import LogFormat, LogLevel, configure_logging, get_logger, log_event
from .semantic_snapshot import SemanticSnapshotError, SemanticSnapshotStore
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


def _default_analyzer(service: WorkspaceService) -> Analyzer:
    return AnalyzerRegistry()


def _context(root: Path) -> AtlasCliContext:
    resolved = root.expanduser().resolve()
    return AtlasCliContext(resolved, WorkspaceService(resolved))


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
) -> None:
    """Analyze a workspace."""
    def operation() -> None:
        context = _context(root)
        selected = tuple(project or ())
        actual_workers = _adaptive_workers(context, selected, workers) if adaptive else workers
        report = _execute(context, projects=selected, workers=actual_workers, force=force, recover=recover)
        report = _apply_baseline_options(report, baseline=baseline, write_baseline=write_baseline)
        report = _apply_diff_options(report, root, enabled=diff, base=diff_base, head=diff_head, staged=staged)
        history = HistoryDatabase(root)
        run_id = history.record(report)
        if report.succeeded:
            collected = SemanticContextCollector(context.service).collect(report)
            store = SemanticSnapshotStore(context.service.workspace)
            store.save(store.capture(collected.context, history_reference=run_id))
        _emit_report(report, output_format)

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


def _load_ai_snapshot(root: Path, snapshot: Path | None):
    context = _context(root)
    store = SemanticSnapshotStore(context.service.workspace)
    loaded = store.load(snapshot)
    if loaded is None:
        target = snapshot or store.latest_path
        raise SemanticSnapshotError(
            f"semantic snapshot not found: {target}; run analysis snapshot creation first"
        )
    return loaded


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
) -> None:
    """Render a repository report or explain a targeted semantic subject."""
    def operation() -> None:
        loaded = _load_ai_snapshot(root, snapshot)
        request = ExplainRequest(subject=subject)
        if ExplainEngine._is_repository_default(request):
            result = ExplainEngine(
                memory=ConversationMemoryStore(root),
            ).explain(loaded, request)
            typer.echo(result.markdown)
            return
        provider = (_ai_provider_factory or OllamaProvider)()
        try:
            result = ExplainEngine(
                LlmClient(provider),
                memory=ConversationMemoryStore(root),
            ).explain(loaded, request)
            typer.echo(result.markdown)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

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
    for historical in HistoryDatabase(context.root).list(limit=20):
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
