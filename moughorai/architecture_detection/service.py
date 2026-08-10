from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Protocol

from moughorai.java_architecture import JavaArchitectureGraph

from .models import (
    ArchitectureDependencyDirection,
    ArchitectureDependencyEvidenceClass,
    ArchitectureDependencyPair,
    ArchitectureDependencyPairClassification,
    ArchitectureDependencyTopology,
    ArchitectureEvidence,
    ArchitectureFinding,
    ArchitectureReport,
)


@dataclass(frozen=True, slots=True)
class _ArchitectureFacts:
    summary: Mapping[str, Any]
    nodes: tuple[Mapping[str, Any], ...]
    edges: tuple[Mapping[str, Any], ...]
    java_graph: JavaArchitectureGraph | None

    @property
    def searchable(self) -> tuple[tuple[str, str], ...]:
        values = [
            (str(node.get("id", "")), str(node.get("qualified_name", "")))
            for node in self.nodes
            if node.get("kind") in (None, "package", "type")
        ]
        values.extend(
            (
                f"project:{project.get('name', '')}",
                " ".join((
                    str(project.get("name", "")),
                    str(project.get("path", "")),
                    " ".join(project.get("frameworks", ())),
                    " ".join(project.get("entry_points", ())),
                )),
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
        require_relationship: bool = False,
    ) -> None:
        self.name = name
        self.groups = groups
        self.minimum_groups = minimum_groups
        self.base_confidence = base_confidence
        self.require_relationship = require_relationship

    def detect(self, facts: _ArchitectureFacts) -> ArchitectureFinding | None:
        evidence: list[ArchitectureEvidence] = []
        matched_groups = 0
        for group in self.groups:
            group_matches = [
                ArchitectureEvidence("semantic-name", reference, token)
                for reference, value in facts.searchable
                for token in group
                if token.casefold() in _terms(value)
            ]
            if group_matches:
                matched_groups += 1
                evidence.extend(group_matches[:2])
        if matched_groups < self.minimum_groups:
            return None
        references = {item.reference for item in evidence}
        if self.require_relationship and not any(
            str(edge.get("source")) in references
            and str(edge.get("target")) in references
            for edge in facts.edges
        ):
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
        server_frameworks = {
            "spring", "quarkus", "micronaut", "flask", "fastapi",
            "django", "nestjs",
        }
        services = [
            project for project in facts.summary.get("projects", ())
            if project.get("entry_points")
            and server_frameworks.intersection(
                str(item).casefold() for item in project.get("frameworks", ())
            )
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
                base_confidence=0.58,
                require_relationship=True,
            ),
            _ModularMonolithDetector(),
            _MicroservicesDetector(),
            _TokenDetector(
                "hexagonal",
                (("port",), ("adapter",), ("domain",)),
                minimum_groups=2,
                base_confidence=0.62,
                require_relationship=True,
            ),
            _TokenDetector(
                "clean-architecture",
                (("domain", "entity"), ("application", "usecase"), ("infrastructure",), ("interface", "presenter")),
                minimum_groups=3,
                base_confidence=0.6,
                require_relationship=True,
            ),
            _TokenDetector(
                "cqrs",
                (("command",), ("query",), ("handler",)),
                minimum_groups=3,
                base_confidence=0.72,
                require_relationship=True,
            ),
            _TokenDetector(
                "event-driven",
                (("event",), ("listener", "subscriber", "consumer"), ("publisher", "producer")),
                minimum_groups=2,
                base_confidence=0.56,
                require_relationship=True,
            ),
            _TokenDetector(
                "plugin-architecture",
                (("plugin",), ("extension",), ("provider",)),
                minimum_groups=2,
                base_confidence=0.6,
                require_relationship=True,
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
        conflicts = self._conflicts(findings)
        build_topology = self._build_topology(facts)
        import_topology = self._import_topology(facts)
        return ArchitectureReport(
            findings,
            directions,
            self._cycles(directions),
            self._bounded_contexts(facts),
            self._matching(names, ("port",)),
            self._matching(names, ("adapter",)),
            self._matching(names, ("infrastructure", "persistence", "repository")),
            bool(directions),
            len(directions),
            conflicts,
            build_dependency_topology=build_topology,
            import_dependency_topology=import_topology,
            dependency_pair_classifications=self._pair_classifications(
                build_topology,
                import_topology,
            ),
        )

    @classmethod
    def _build_topology(
        cls,
        facts: _ArchitectureFacts,
    ) -> ArchitectureDependencyTopology:
        projects = {
            str(node.get("id")): str(
                node.get("qualified_name") or node.get("name") or node.get("id")
            )
            for node in facts.nodes
            if node.get("kind") == "project"
        }
        evidence: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for edge in facts.edges:
            if edge.get("kind") != "depends_on":
                continue
            source = projects.get(str(edge.get("source")))
            target = projects.get(str(edge.get("target")))
            if source is None or target is None:
                continue
            evidence.setdefault((source, target), []).append(edge)
        return cls._topology(
            ArchitectureDependencyEvidenceClass.BUILD_MODULE,
            evidence,
            default_provenance="semantic_graph",
        )

    @classmethod
    def _import_topology(
        cls,
        facts: _ArchitectureFacts,
    ) -> ArchitectureDependencyTopology:
        nodes = {str(node.get("id")): node for node in facts.nodes}
        evidence: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
        for edge in facts.edges:
            if edge.get("kind") != "imports":
                continue
            source = nodes.get(str(edge.get("source")))
            target = nodes.get(str(edge.get("target")))
            if source is None or target is None:
                continue
            source_project = source.get("project_id")
            target_project = target.get("project_id")
            if (
                source_project
                and target_project
                and source_project != target_project
            ):
                evidence.setdefault(
                    (str(source_project), str(target_project)),
                    [],
                ).append(edge)
        return cls._topology(
            ArchitectureDependencyEvidenceClass.SOURCE_IMPORT,
            evidence,
            default_provenance="semantic_graph",
        )

    @classmethod
    def _topology(
        cls,
        evidence_class: ArchitectureDependencyEvidenceClass,
        evidence: Mapping[tuple[str, str], list[Mapping[str, Any]]],
        *,
        default_provenance: str,
    ) -> ArchitectureDependencyTopology:
        directions = tuple(
            ArchitectureDependencyDirection(
                source,
                target,
                evidence_class,
                sum(cls._evidence_count(edge) for edge in edges),
                tuple(sorted({
                    cls._provenance(edge, default_provenance)
                    for edge in edges
                })),
            )
            for (source, target), edges in sorted(evidence.items())
        )
        pairs = tuple(
            (direction.source_project, direction.target_project)
            for direction in directions
        )
        return ArchitectureDependencyTopology(
            evidence_class,
            directions,
            cls._topology_cycles(pairs),
        )

    @staticmethod
    def _evidence_count(edge: Mapping[str, Any]) -> int:
        evidence = edge.get("evidence")
        if isinstance(evidence, (list, tuple)):
            return max(1, len(evidence))
        return 1

    @staticmethod
    def _provenance(edge: Mapping[str, Any], default: str) -> str:
        raw = edge.get("evidence")
        values = raw if isinstance(raw, (list, tuple)) else ()
        if any(str(item).startswith("workspace.projects:") for item in values):
            return "workspace.projects"
        if any(str(item).startswith("global_symbol.metadata:") for item in values):
            return "global_symbol.metadata"
        if any(str(item).startswith("java-architecture:") for item in values):
            return "java-architecture"
        return default

    @staticmethod
    def _pair_classifications(
        build: ArchitectureDependencyTopology,
        imports: ArchitectureDependencyTopology,
    ) -> tuple[ArchitectureDependencyPair, ...]:
        build_pairs = {
            (item.source_project, item.target_project)
            for item in build.directions
        }
        import_pairs = {
            (item.source_project, item.target_project)
            for item in imports.directions
        }
        return tuple(
            ArchitectureDependencyPair(
                source,
                target,
                (
                    ArchitectureDependencyPairClassification.CORROBORATED
                    if pair in build_pairs and pair in import_pairs
                    else ArchitectureDependencyPairClassification.BUILD_ONLY
                    if pair in build_pairs
                    else ArchitectureDependencyPairClassification.IMPORT_ONLY
                ),
            )
            for pair in sorted(build_pairs | import_pairs)
            for source, target in (pair,)
        )

    @classmethod
    def _topology_cycles(
        cls,
        edges: tuple[tuple[str, str], ...],
    ) -> tuple[tuple[str, ...], ...]:
        if not edges:
            return ()
        nodes = {value for edge in edges for value in edge}
        indegree = {node: 0 for node in nodes}
        adjacency: dict[str, set[str]] = {}
        for source, target in edges:
            adjacency.setdefault(source, set()).add(target)
            indegree[target] += 1
        ready = sorted(node for node, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            current = ready.pop(0)
            visited += 1
            for target in sorted(adjacency.get(current, ())):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
            ready.sort()
        return () if visited == len(nodes) else cls._cycles(edges)

    @staticmethod
    def _conflicts(
        findings: tuple[ArchitectureFinding, ...],
    ) -> tuple[str, ...]:
        names = {item.architecture for item in findings}
        conflicts = []
        if {"modular-monolith", "microservices"} <= names:
            conflicts.append(
                "modular-monolith and microservices evidence coexist; deployment boundaries require manual confirmation"
            )
        return tuple(conflicts)

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
            if any(token.casefold() in _terms(name) for token in tokens)
        ))


def _terms(value: str) -> frozenset[str]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return frozenset(
        token.casefold()
        for token in re.split(r"[^A-Za-z0-9]+", separated)
        if token
    )
