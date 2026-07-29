from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from .models import Workspace


class WorkspaceDependencyError(ValueError):
    pass


class DependencyGraph:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.dependencies = {project.name: project.dependencies for project in workspace.projects}
        names = set(self.dependencies)
        missing = sorted({dep for deps in self.dependencies.values() for dep in deps if dep not in names})
        if missing:
            raise WorkspaceDependencyError(f"unknown project dependencies: {', '.join(missing)}")
        self._dependents: dict[str, tuple[str, ...]] = self._build_dependents()
        self._order = self._topological_order()

    def _build_dependents(self) -> dict[str, tuple[str, ...]]:
        values: dict[str, list[str]] = defaultdict(list)
        for project, dependencies in self.dependencies.items():
            for dependency in dependencies:
                values[dependency].append(project)
        return {name: tuple(sorted(values.get(name, ()))) for name in self.dependencies}

    def _topological_order(self) -> tuple[str, ...]:
        indegree = {name: len(deps) for name, deps in self.dependencies.items()}
        ready = deque(sorted(name for name, degree in indegree.items() if degree == 0))
        result: list[str] = []
        while ready:
            name = ready.popleft()
            result.append(name)
            for dependent in self._dependents[name]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
            ready = deque(sorted(ready))
        if len(result) != len(indegree):
            cycle = sorted(name for name, degree in indegree.items() if degree > 0)
            raise WorkspaceDependencyError(f"project dependency cycle: {', '.join(cycle)}")
        return tuple(result)

    def order(self, projects: Iterable[str] | None = None) -> tuple[str, ...]:
        if projects is None:
            return self._order
        selected = set(projects)
        unknown = selected.difference(self.dependencies)
        if unknown:
            raise KeyError(f"unknown projects: {', '.join(sorted(unknown))}")
        return tuple(name for name in self._order if name in selected)

    def dependents(self, name: str, *, transitive: bool = True) -> tuple[str, ...]:
        if name not in self.dependencies:
            raise KeyError(f"unknown project: {name}")
        if not transitive:
            return self._dependents[name]
        seen: set[str] = set()
        pending = list(self._dependents[name])
        while pending:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self._dependents[current])
        return tuple(item for item in self._order if item in seen)

    def dependencies_of(self, name: str, *, transitive: bool = True) -> tuple[str, ...]:
        if name not in self.dependencies:
            raise KeyError(f"unknown project: {name}")
        if not transitive:
            return self.dependencies[name]
        seen: set[str] = set()
        pending = list(self.dependencies[name])
        while pending:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self.dependencies[current])
        return tuple(item for item in self._order if item in seen)
