"""Deterministic framework detection from parsed Maven metadata."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from moughorai.project_inventory.framework_models import (
    DetectedFramework,
    FrameworkEvidence,
    FrameworkReport,
)
from moughorai.project_inventory.framework_rules import (
    FRAMEWORK_RULES,
    FrameworkRule,
)
from moughorai.project_inventory.maven_models import (
    MavenDependency,
    MavenPlugin,
    MavenProject,
)


class MavenFrameworkDetector:
    """Detect frameworks and supporting technologies from a Maven project."""

    def __init__(
        self,
        rules: tuple[FrameworkRule, ...] = FRAMEWORK_RULES,
    ) -> None:
        self._rules = rules

    def detect(self, project: MavenProject) -> FrameworkReport:
        """Return a deterministic framework report for one Maven project."""

        evidence_by_rule: dict[
            FrameworkRule,
            list[FrameworkEvidence],
        ] = defaultdict(list)

        for dependency in (
            project.dependencies + project.managed_dependencies
        ):
            self._match_dependency(
                dependency=dependency,
                source=project.pom_path,
                evidence_by_rule=evidence_by_rule,
            )

        for plugin in project.plugins:
            self._match_plugin(
                plugin=plugin,
                source=project.pom_path,
                evidence_by_rule=evidence_by_rule,
            )

        technologies = tuple(
            sorted(
                (
                    DetectedFramework(
                        name=rule.name,
                        category=rule.category,
                        confidence=rule.confidence,
                        evidence=self._deduplicate_evidence(items),
                    )
                    for rule, items in evidence_by_rule.items()
                ),
                key=lambda technology: (
                    technology.category.value,
                    technology.name.casefold(),
                ),
            )
        )

        return FrameworkReport(
            source=project.pom_path,
            technologies=technologies,
        )

    def detect_many(
        self,
        projects: tuple[MavenProject, ...] | list[MavenProject],
    ) -> tuple[FrameworkReport, ...]:
        """Detect frameworks for multiple projects in path order."""

        return tuple(
            self.detect(project)
            for project in sorted(
                projects,
                key=lambda item: item.pom_path.as_posix().casefold(),
            )
        )

    def _match_dependency(
        self,
        *,
        dependency: MavenDependency,
        source: Path,
        evidence_by_rule: dict[
            FrameworkRule,
            list[FrameworkEvidence],
        ],
    ) -> None:
        for rule in self._rules:
            if rule.matches(
                dependency.group_id,
                dependency.artifact_id,
            ):
                evidence_by_rule[rule].append(
                    FrameworkEvidence(
                        coordinate=dependency.identifier,
                        source=source,
                        version=dependency.version,
                        scope=dependency.scope,
                        kind="dependency",
                    )
                )

    def _match_plugin(
        self,
        *,
        plugin: MavenPlugin,
        source: Path,
        evidence_by_rule: dict[
            FrameworkRule,
            list[FrameworkEvidence],
        ],
    ) -> None:
        for rule in self._rules:
            if rule.matches(plugin.group_id, plugin.artifact_id):
                evidence_by_rule[rule].append(
                    FrameworkEvidence(
                        coordinate=plugin.identifier,
                        source=source,
                        version=plugin.version,
                        kind="plugin",
                    )
                )

    @staticmethod
    def _deduplicate_evidence(
        evidence: list[FrameworkEvidence],
    ) -> tuple[FrameworkEvidence, ...]:
        unique = {
            (
                item.coordinate,
                item.source,
                item.version,
                item.scope,
                item.kind,
            ): item
            for item in evidence
        }

        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.coordinate.casefold(),
                    item.kind.casefold(),
                    item.version or "",
                    item.scope or "",
                ),
            )
        )
