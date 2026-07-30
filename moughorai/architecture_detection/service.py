from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from moughorai.java_architecture import JavaArchitectureGraph

from .models import ArchitectureEvidence, ArchitectureFinding, ArchitectureReport


@dataclass(frozen=True, slots=True)
class _ArchitectureFacts:
    summary: Mapping[str, Any]
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    java_graph: JavaArchitectureGraph | None

    @property
    def searchable(self) -> tuple[tuple[str, str], ...]:
        values = [
            (str(node.get("id", "")), str(node.get("qualified_name", "")).casefold())
            for node in self.nodes
        ]
        values.extend(
            (
                f"project:{project.get('name', '')}",
                " ".join((
                    str(project.get("name", "")),
                    str(project.get("path", "")),
                    " ".join(project.get("frameworks", ())),
                    " ".join(project.get("entry_points", ())),
                )).casefold(),
            )
            for project in self.summary.get("projects", ())
        )
        return tuple(values)


class ArchitecturePatternDetector(Protocol):
    name: str

    def detect(self, facts: _ArchitectureFacts) -> ArchitectureFinding | None: ...


class _TokenDetector:
    def __init__(
        self,
        name: str,
        groups: tuple[tuple[str, ...], ...],
        *,
        minimum_groups: int,
        base_confidence: float,
    ) -> None:
        self.name = name
        self.groups = groups
        self.minimum_groups = minimum_groups
        self.base_confidence = base_confidence

    def detect(self, facts: _ArchitectureFacts) -> ArchitectureFinding | None:
        evidence: list[ArchitectureEvidence] = []
        matched_groups = 0
        for group in self.groups:
            group_matches = [
                ArchitectureEvidence("semantic-name", reference, token)
                for reference, value in facts.searchable
                for token in group
                if token in value
            ]
            if group_matches:
                matched_groups += 1
                evidence.extend(group_matches[:2])
        if matched_groups < self.minimum_groups:
            return None
        confidence = min(0.98, self.base_confidence + 0.06 * (matched_groups - self.minimum_groups))
        return ArchitectureFinding(self.name, confidence, tuple(sorted(set(evidence))))


class _ModularMonolithDetector:
    name = "modular-monolith"

    def detect(self, facts: _ArchitectureFacts) -> ArchitectureFinding | None:
        hierarchy = facts.summary.get("module_hierarchy", ())
        children = [
            item for item in hierarchy
            if item.get("parent") is not None
        ]
        if len(children) < 2:
            return None
        evidence = tuple(
            ArchitectureEvidence(
                "module-hierarchy",
                str(item["project"]),
                f"parent={item['parent']}",
            )
            for item in children
        )
        return ArchitectureFinding(self.name, 0.82, evidence)


class _MicroservicesDetector:
    name = "microservices"

    def detect(self, facts: _ArchitectureFacts) -> ArchitectureFinding | None:
        services = [
            project for project in facts.summary.get("projects", ())
            if project.get("entry_points")
        ]
        if len(services) < 2:
            return None
        evidence = tuple(
            ArchitectureEvidence(
                "project-entry-point",
                str(project["name"]),
                str(project["entry_points"][0]),
            )
            for project in services
        )
        return ArchitectureFinding(self.name, 0.8, evidence)


class ArchitectureDetectionService:
    """Detect repository architecture from published, source-free Atlas facts."""

    def __init__(
        self,
        detectors: tuple[ArchitecturePatternDetector, ...] | None = None,
    ) -> None:
        self.detectors = detectors or (
            _TokenDetector(
                "layered",
                (("controller", "api"), ("service", "application"), ("repository", "dao", "persistence")),
                minimum_groups=2,
                base_confidence=0.72,
            ),
            _ModularMonolithDetector(),
            _MicroservicesDetector(),
            _TokenDetector(
                "hexagonal",
                (("port",), ("adapter",), ("domain",)),
                minimum_groups=2,
                base_confidence=0.76,
            ),
            _TokenDetector(
                "clean-architecture",
                (("domain", "entity"), ("application", "usecase"), ("infrastructure",), ("interface", "presenter")),
                minimum_groups=3,
                base_confidence=0.78,
            ),
            _TokenDetector(
                "cqrs",
                (("command", "commandhandler"), ("query", "queryhandler")),
                minimum_groups=2,
                base_confidence=0.82,
            ),
            _TokenDetector(
                "event-driven",
                (("event",), ("listener", "subscriber", "consumer"), ("publisher", "producer")),
                minimum_groups=2,
                base_confidence=0.76,
            ),
            _TokenDetector(
                "plugin-architecture",
                (("plugin",), ("extension",), ("provider",)),
                minimum_groups=2,
                base_confidence=0.74,
            ),
        )

    def detect(
        self,
        repository_summary: Mapping[str, Any],
        semantic_graph: Mapping[str, Any],
        *,
        java_graph: JavaArchitectureGraph | None = None,
    ) -> ArchitectureReport:
        facts = _ArchitectureFacts(
            repository_summary,
            tuple(semantic_graph.get("nodes", ())),
            tuple(semantic_graph.get("edges", ())),
            java_graph,
        )
        findings = tuple(sorted(
            (
                finding
                for detector in self.detectors
                if (finding := detector.detect(facts)) is not None
            ),
            key=lambda item: item.architecture,
        ))
        directions = self._directions(facts)
        names = tuple(
            (str(node.get("id", "")), str(node.get("qualified_name", "")))
            for node in facts.nodes
        )
        return ArchitectureReport(
            findings,
            directions,
            self._cycles(directions),
            self._bounded_contexts(facts),
            self._matching(names, ("port",)),
            self._matching(names, ("adapter",)),
            self._matching(names, ("infrastructure", "persistence", "repository")),
        )

    @staticmethod
    def _directions(facts: _ArchitectureFacts) -> tuple[tuple[str, str], ...]:
        nodes = {str(node.get("id")): node for node in facts.nodes}
        values: set[tuple[str, str]] = set()
        for edge in facts.edges:
            if edge.get("kind") != "imports":
                continue
            source = nodes.get(str(edge.get("source")))
            target = nodes.get(str(edge.get("target")))
            if source is None or target is None:
                continue
            source_project = source.get("project_id")
            target_project = target.get("project_id")
            if source_project and target_project and source_project != target_project:
                values.add((str(source_project), str(target_project)))
        if facts.java_graph is not None:
            values.update(
                (edge.source, edge.target)
                for edge in facts.java_graph.edges
            )
        return tuple(sorted(values))

    @staticmethod
    def _cycles(edges: tuple[tuple[str, str], ...]) -> tuple[tuple[str, ...], ...]:
        adjacency: dict[str, set[str]] = {}
        for source, target in edges:
            adjacency.setdefault(source, set()).add(target)
        cycles: set[tuple[str, ...]] = set()

        def visit(start: str, current: str, path: tuple[str, ...]) -> None:
            for target in sorted(adjacency.get(current, ())):
                if target == start and len(path) > 1:
                    cycle = path
                    rotations = tuple(cycle[index:] + cycle[:index] for index in range(len(cycle)))
                    cycles.add(min(rotations))
                elif target not in path:
                    visit(start, target, path + (target,))

        for node in sorted(adjacency):
            visit(node, node, (node,))
        return tuple(sorted(cycles))

    @staticmethod
    def _bounded_contexts(facts: _ArchitectureFacts) -> tuple[str, ...]:
        projects = {
            str(node.get("project_id"))
            for node in facts.nodes
            if node.get("project_id")
        }
        return tuple(sorted(projects))

    @staticmethod
    def _matching(
        names: tuple[tuple[str, str], ...],
        tokens: tuple[str, ...],
    ) -> tuple[str, ...]:
        return tuple(sorted(
            name for _, name in names
            if any(token in name.casefold() for token in tokens)
        ))
