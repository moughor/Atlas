"""Unified Atlas command-line interface introduced in PR75."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from .plugin_sdk import PluginDiscovery
from .workspace import (
    Project,
    WorkspaceAnalysisOrchestrator,
    WorkspaceConfigurationError,
    WorkspaceRecoveryManager,
    WorkspaceRunReport,
    WorkspaceService,
    WorkspaceStateError,
    WorkspaceWatcher,
)


app = typer.Typer(
    name="atlas",
    help="Atlas modular static-analysis platform.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class AtlasCliContext:
    root: Path
    service: WorkspaceService


Analyzer = Callable[[Project, Mapping[str, Any]], Any]
_analyzer_factory: Callable[[WorkspaceService], Analyzer] | None = None


def _default_analyzer(service: WorkspaceService) -> Analyzer:
    def analyze(project: Project, dependencies: Mapping[str, Any]) -> dict[str, Any]:
        files = {
            path.resolve()
            for pattern in project.include
            for path in project.path.glob(pattern)
            if path.is_file()
        }
        excluded = {
            path.resolve()
            for pattern in project.exclude
            for path in project.path.glob(pattern)
            if path.is_file()
        }
        return {
            "project": project.name,
            "files": len(files - excluded),
            "dependencies": sorted(dependencies),
        }

    return analyze


def _context(root: Path) -> AtlasCliContext:
    resolved = root.expanduser().resolve()
    return AtlasCliContext(resolved, WorkspaceService(resolved))


def _analyzer(service: WorkspaceService) -> Analyzer:
    return (_analyzer_factory or _default_analyzer)(service)


def _emit_report(report: WorkspaceRunReport) -> None:
    for run in report.runs:
        typer.echo(f"{run.project}: {run.status.value}")
    typer.echo(f"projects: {len(report.runs)}")
    typer.echo(f"succeeded: {'yes' if report.succeeded else 'no'}")


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
        manager = WorkspaceRecoveryManager(context.service)
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
) -> None:
    """Analyze a workspace."""
    _run_command(lambda: _emit_report(_execute(_context(root), projects=tuple(project or ()), workers=workers, force=force, recover=recover)))


@app.command()
def check(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
    project: Annotated[list[str] | None, typer.Option("--project", "-p", help="Project to check.")] = None,
    workers: Annotated[int, typer.Option("--workers", "-j", min=1, help="Maximum concurrent projects.")] = 1,
) -> None:
    """Analyze a workspace and fail when project analysis fails."""
    def operation() -> None:
        report = _execute(_context(root), projects=tuple(project or ()), workers=workers, force=False, recover=True)
        _emit_report(report)
        if not report.succeeded:
            raise typer.Exit(code=1)

    _run_command(operation)


@app.command()
def watch(
    root: Annotated[Path, typer.Argument(help="Workspace root.")] = Path("."),
) -> None:
    """Initialize workspace watching and print its deterministic snapshot."""
    def operation() -> None:
        context = _context(root)
        snapshot = WorkspaceWatcher(context.service.workspace, event_bus=context.service.events).start()
        typer.echo(f"workspace: {context.root.as_posix()}")
        typer.echo(f"projects: {len(context.service.workspace.projects)}")
        typer.echo(f"tracked_files: {len(snapshot.files)}")
        typer.echo("status: ready")

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
    ) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc


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
