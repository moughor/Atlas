"""Stable, versioned public API for Atlas embedders.

Everything outside this module remains importable for backwards compatibility,
but is not covered by the public compatibility policy.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping

from moughorai.api import AnalysisApiService, AnalysisRequest, AnalysisResult
from moughorai.plugin_sdk import PluginContext, PluginManifest, PluginRegistry
from moughorai.project_index import PersistentProjectIndex, ProjectFileIndexer
from moughorai.rule_sdk import RuleContext, RuleFinding, RuleRegistry, RuleRunner
from moughorai.semantic_search import (
    SemanticSearchRequest,
    SemanticSearchResponse,
    SemanticSearchService,
)
from moughorai.workspace import (
    Project,
    ResolvedConfiguration,
    Workspace,
    WorkspaceAnalysisOrchestrator,
    WorkspaceEventBus,
)

PUBLIC_API_VERSION = "1.0"

PUBLIC_API_SIGNATURES: Mapping[str, str] = {
    "AnalysisApiService": "(analyzer: 'Callable[[AnalysisRequest], Any]', *, id_factory: 'Callable[[], str] | None' = None) -> 'None'",
    "AnalysisRequest": "(project: 'str', targets: 'tuple[str, ...]' = (), options: 'tuple[tuple[str, str], ...]' = (), request_id: 'str' = '') -> None",
    "AnalysisResult": "(findings: 'tuple[Mapping[str, Any], ...]' = (), metrics: 'tuple[tuple[str, int | float | str], ...]' = ()) -> None",
    "PersistentProjectIndex": "(indexer: 'ProjectFileIndexer | None' = None, store: 'ProjectIndexStore | None' = None) -> 'None'",
    "PluginContext": "(services: 'Mapping[str, Any] | None' = None) -> 'None'",
    "PluginManifest": "(plugin_id: 'str', version: 'str', api_version: 'str', name: 'str', extensions: 'tuple[PluginExtension, ...]', description: 'str' = '', requires: 'tuple[str, ...]' = (), permissions: 'tuple[str, ...]' = (), metadata: 'Mapping[str, Any]' = <factory>) -> None",
    "PluginRegistry": "(*, api_version: 'str' = '1.0.0') -> 'None'",
    "Project": "(name: 'str', path: 'Path', dependencies: 'tuple[str, ...]' = (), include: 'tuple[str, ...]' = ('**/*',), exclude: 'tuple[str, ...]' = (), options: 'tuple[tuple[str, str], ...]' = ()) -> None",
    "ProjectFileIndexer": "(scanner: 'ProjectScanner | None' = None, *, chunk_size: 'int' = 1048576) -> 'None'",
    "ResolvedConfiguration": "(values: 'Mapping[str, Any]', provenance: 'Mapping[str, str]', layers: 'tuple[str, ...]') -> None",
    "RuleContext": "(path: 'Path', source: 'str', language: 'str', configuration: 'Mapping[str, Any]') -> None",
    "RuleFinding": "(rule_id: 'str', message: 'str', severity: 'RuleSeverity', location: 'RuleLocation', data: 'tuple[tuple[str, Any], ...]' = ()) -> None",
    "RuleRegistry": "(rules: 'Iterable[Rule]' = ()) -> 'None'",
    "RuleRunner": "()",
    "SemanticSearchRequest": "(text: 'str', kinds: 'tuple[KnowledgeKind, ...]' = (), project: 'str | None' = None, module: 'str | None' = None, package: 'str | None' = None, language: 'str | None' = None, relation: 'KnowledgeRelation | None' = None, minimum_confidence: 'float' = 0.0, limit: 'int' = 20) -> None",
    "SemanticSearchResponse": "(request: 'SemanticSearchRequest', interpretation: 'QueryInterpretation', hits: 'tuple[StructuredSearchHit, ...]', total_candidate_count: 'int', omitted_count: 'int', capabilities: 'tuple[SearchCapability, ...]', index_id: 'str', evidence_index: 'EvidenceIndex' = <factory>, limitations: 'tuple[str, ...]' = (), producer: 'str' = 'atlas-pr135/1', schema_version: 'int' = 1) -> None",
    "SemanticSearchService": "(symbols: 'GlobalSymbolDatabase', graph: 'DependencyGraph | None' = None) -> 'None'",
    "Workspace": "(root: 'Path', projects: 'tuple[Project, ...]', config_path: 'Path | None' = None, options: 'tuple[tuple[str, str], ...]' = ()) -> None",
    "WorkspaceAnalysisOrchestrator": "(service: 'WorkspaceService', *, planner: 'IncrementalWorkspacePlanner | None' = None) -> 'None'",
    "WorkspaceEventBus": "(*, history_limit: 'int' = 100, correlation_id: 'str | None' = None) -> 'None'",
}


def public_api_manifest() -> dict[str, str]:
    """Return the current deterministic constructor signature manifest."""
    namespace = globals()
    return {
        name: str(inspect.signature(namespace[name]))
        for name in sorted(PUBLIC_API_SIGNATURES)
        if name in namespace
    }


def public_api_compatibility_issues(expected: Mapping[str, str] = PUBLIC_API_SIGNATURES) -> tuple[str, ...]:
    """Report removed exports and changed constructor signatures."""
    actual = public_api_manifest()
    issues: list[str] = []
    for name, signature in sorted(expected.items()):
        if name not in actual:
            issues.append(f"removed public export: {name}")
        elif actual[name] != signature:
            issues.append(f"changed public signature: {name}: {signature} -> {actual[name]}")
    return tuple(issues)


__all__ = [
    "AnalysisApiService",
    "AnalysisRequest",
    "AnalysisResult",
    "PUBLIC_API_SIGNATURES",
    "PUBLIC_API_VERSION",
    "PersistentProjectIndex",
    "PluginContext",
    "PluginManifest",
    "PluginRegistry",
    "Project",
    "ProjectFileIndexer",
    "ResolvedConfiguration",
    "RuleContext",
    "RuleFinding",
    "RuleRegistry",
    "RuleRunner",
    "SemanticSearchRequest",
    "SemanticSearchResponse",
    "SemanticSearchService",
    "Workspace",
    "WorkspaceAnalysisOrchestrator",
    "WorkspaceEventBus",
    "public_api_compatibility_issues",
    "public_api_manifest",
]
