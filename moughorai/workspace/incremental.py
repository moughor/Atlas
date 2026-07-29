from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .events import FileEvent
from .event_bus import WorkspaceEventKind
from .models import Project
from .service import WorkspaceService


@dataclass(frozen=True, slots=True)
class IncrementalPlan:
    events: tuple[FileEvent, ...]
    directly_changed: tuple[str, ...]
    invalidated: tuple[str, ...]
    analysis_order: tuple[Project, ...]

    def to_dict(self) -> dict[str, object]:
        root = self.analysis_order[0].path.parent if self.analysis_order else None
        return {
            "events": [event.to_dict(root=root) for event in self.events],
            "directly_changed": list(self.directly_changed),
            "invalidated": list(self.invalidated),
            "analysis_order": [project.name for project in self.analysis_order],
        }


class IncrementalWorkspacePlanner:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service
        self._valid_projects: set[str] = set(service.workspace.names())

    @property
    def valid_projects(self) -> tuple[str, ...]:
        return tuple(sorted(self._valid_projects))

    def plan(self, events: tuple[FileEvent, ...]) -> IncrementalPlan:
        changed = tuple(sorted({event.project for event in events if event.project is not None}))
        if not changed:
            return IncrementalPlan(events, (), (), ())
        impacted = self.service.impacted_projects(changed)
        invalidated = tuple(project.name for project in impacted)
        self.invalidate(invalidated)
        plan = IncrementalPlan(events, changed, invalidated, impacted)
        self.service.events.emit(
            WorkspaceEventKind.PLAN_CREATED,
            source="workspace.incremental",
            payload=plan.to_dict(),
        )
        return plan

    def invalidate(self, projects: tuple[str, ...] | list[str] | set[str]) -> tuple[str, ...]:
        removed = tuple(sorted(self._valid_projects.intersection(projects)))
        self._valid_projects.difference_update(projects)
        if removed:
            self.service.events.emit(
                WorkspaceEventKind.CACHE_INVALIDATED,
                source="workspace.incremental",
                payload={"projects": list(removed)},
            )
        return removed

    def mark_valid(self, project: str) -> None:
        self.service.project(project)
        self._valid_projects.add(project)

    def mark_plan_valid(self, plan: IncrementalPlan) -> None:
        for project in plan.analysis_order:
            self._valid_projects.add(project.name)
