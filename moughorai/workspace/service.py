from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from moughorai.measurement import MeasurementPhase, MeasurementSession

from .cache import WorkspaceCache, WorkspaceSnapshot
from .discovery import WorkspaceDiscovery
from .graph import DependencyGraph
from .models import Project, Workspace
from .configuration import ResolvedConfiguration, WorkspaceConfigurationResolver
from .event_bus import WorkspaceEventBus, WorkspaceEventKind


class WorkspaceService:
    def __init__(
        self,
        root: Path | str,
        *,
        max_depth: int = 4,
        event_bus: WorkspaceEventBus | None = None,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.measurement = measurement or MeasurementSession()
        with self.measurement.scope(
            MeasurementPhase.WORKSPACE_DISCOVERY,
            consumer="workspace-service",
            sample_key="workspace",
        ) as scope:
            self.workspace = WorkspaceDiscovery(
                measurement=self.measurement,
            ).discover(root, max_depth=max_depth)
            scope.add_units(len(self.workspace.projects))
            scope.add_objects_produced(len(self.workspace.projects))
        with self.measurement.scope(
            MeasurementPhase.PROJECT_OWNERSHIP,
            consumer="workspace-service",
            sample_key="workspace",
        ) as scope:
            self.graph = DependencyGraph(self.workspace)
            scope.add_units(len(self.workspace.projects))
            scope.add_objects_produced(len(self.workspace.projects))
        self.cache = WorkspaceCache(measurement=self.measurement)
        self.events = event_bus or WorkspaceEventBus()

    def project(self, name: str) -> Project:
        return self.workspace.get(name)

    def analysis_order(self, projects: Iterable[str] | None = None, *, include_dependencies: bool = True) -> tuple[Project, ...]:
        if projects is None:
            names = self.graph.order()
        else:
            selected = set(projects)
            if include_dependencies:
                for name in tuple(selected):
                    selected.update(self.graph.dependencies_of(name))
            names = self.graph.order(selected)
        return tuple(self.workspace.get(name) for name in names)

    def impacted_projects(self, changed: Iterable[str]) -> tuple[Project, ...]:
        selected = set(changed)
        for name in tuple(selected):
            selected.update(self.graph.dependents(name))
        return tuple(self.workspace.get(name) for name in self.graph.order(selected))

    def resolved_configuration(self, project: str, *, global_values=None, cli_overrides=None) -> ResolvedConfiguration:
        target = self.project(project)
        resolved = WorkspaceConfigurationResolver().for_project(
            global_values=global_values,
            workspace_values=dict(self.workspace.options),
            project_values=dict(target.options),
            cli_overrides=cli_overrides,
        )
        self.events.emit(
            WorkspaceEventKind.CONFIGURATION_RESOLVED,
            project=project,
            source="workspace.configuration",
            payload={"keys": sorted(resolved.values)},
        )
        return resolved

    def snapshot(self) -> WorkspaceSnapshot:
        return self.cache.snapshot(self.workspace)

    def changed_projects(self, before: WorkspaceSnapshot | None) -> tuple[Project, ...]:
        after = self.snapshot()
        return tuple(self.workspace.get(name) for name in self.cache.changed(before, after))
