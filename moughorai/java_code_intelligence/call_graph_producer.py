'''Production and workspace consolidation for represented Java call evidence.'''

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path, PurePosixPath

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.java_architecture import (
    ArchitectureEdgeKind,
    JavaArchitectureGraph,
)
from moughorai.java_ast.ast_nodes import CompilationUnit

from .call_resolution import CallResolver
from .call_sites import CallSiteExtractor
from .code_graph import (
    CodeGraphDiagnostic,
    JavaCodeGraph,
    create_code_graph,
)
from .models import (
    JavaCallableIndex,
    PathScope,
    SourcePosition,
    SourceRange,
)


class JavaCodeGraphProducer:
    '''Build direct represented call evidence without reachability claims.'''

    def __init__(self) -> None:
        self._extractor = CallSiteExtractor()

    def build(
        self,
        units: Sequence[CompilationUnit],
        sources: Sequence[Path],
        callable_index: JavaCallableIndex,
        architecture: JavaArchitectureGraph,
        *,
        project_root: Path,
        lineage: str,
    ) -> JavaCodeGraph:
        parents = _architecture_parents(architecture)
        extraction = self._extractor.extract(
            units,
            sources,
            callable_index,
            project_root=project_root,
            parents=parents,
        )
        resolver = CallResolver(callable_index.entries, parents=parents)
        sites = tuple(
            resolver.resolve(request) for request in extraction.requests
        )
        diagnostics: list[CodeGraphDiagnostic] = []
        parse_failures = max(
            0,
            callable_index.coverage.selected_source_files
            - callable_index.coverage.parsed_source_files,
        )
        for diagnostic in callable_index.diagnostics:
            if diagnostic.code != 'parse_failure':
                continue
            source_range = (
                SourceRange(
                    SourcePosition(diagnostic.line, diagnostic.column),
                    SourcePosition(diagnostic.line, diagnostic.column),
                )
                if diagnostic.line is not None and diagnostic.column is not None
                else None
            )
            diagnostics.append(CodeGraphDiagnostic(
                'call_site_parse_failure',
                'Call-site extraction was unavailable for a source file that '
                'did not produce a represented Java syntax tree.',
                callable_index.lineage.removeprefix('project:'),
                source_path=(
                    diagnostic.source_path if source_range is not None else None
                ),
                source_range=source_range,
            ))
        if extraction.extraction_failures:
            diagnostics.append(CodeGraphDiagnostic(
                'call_site_extraction_failure',
                f'{extraction.extraction_failures} callable declaration(s) '
                'could not be mapped to authoritative PR156 identities.',
                callable_index.lineage.removeprefix('project:'),
            ))
        if parse_failures and not any(
            item.code == 'call_site_parse_failure' for item in diagnostics
        ):
            diagnostics.append(CodeGraphDiagnostic(
                'call_site_parse_failure',
                f'Call-site extraction was unavailable for {parse_failures} '
                'selected source file(s) without represented Java syntax trees.',
                callable_index.lineage.removeprefix('project:'),
            ))
        return create_code_graph(
            lineage=lineage,
            path_scope=PathScope.PROJECT,
            callable_index=callable_index,
            call_sites=sites,
            diagnostics=diagnostics,
            callable_bodies_examined=extraction.callable_bodies_examined,
            callable_bodies_unavailable=extraction.callable_bodies_unavailable,
            extraction_failures=(
                extraction.extraction_failures + parse_failures
            ),
        )


def merge_code_graphs(
    graphs: Mapping[str, JavaCodeGraph],
    *,
    callable_index: JavaCallableIndex,
    workspace_root: Path,
    project_paths: Mapping[str, Path],
    canonical_symbols: Sequence[GlobalSymbol],
    lineage: str,
) -> JavaCodeGraph:
    '''Rebase project call sites and resolve them against workspace callables.'''

    prefixes: dict[str, str] = {}
    for project_id, project_path in project_paths.items():
        try:
            relative = project_path.resolve().relative_to(
                workspace_root.resolve()
            )
        except (OSError, RuntimeError, ValueError):
            continue
        prefixes[project_id] = (
            '' if relative == Path('.') else relative.as_posix()
        )

    parents = _canonical_parents(canonical_symbols)
    resolver = CallResolver(callable_index.entries, parents=parents)
    sites = []
    diagnostics: list[CodeGraphDiagnostic] = []
    examined = unavailable = failures = omitted = 0

    for project_id, graph in sorted(graphs.items()):
        prefix = prefixes.get(project_id)
        rebased_paths: dict[str, str] = {}
        examined += graph.coverage.callable_bodies_examined
        unavailable += graph.coverage.callable_bodies_unavailable
        failures += graph.coverage.extraction_failures
        omitted += graph.coverage.omitted_diagnostic_count
        if prefix is None:
            failures += len(graph.call_sites)
            diagnostics.append(CodeGraphDiagnostic(
                'workspace_call_path_unavailable',
                'Project call-site paths cannot be made workspace-relative.',
                project_id,
            ))
            continue
        for site in graph.call_sites:
            source_path = site.request.source_path
            rebased_path = rebased_paths.get(source_path)
            if rebased_path is None:
                rebased_path = _join_relative(prefix, source_path)
                rebased_paths[source_path] = rebased_path
            request = site.as_request().with_source_path(
                rebased_path,
            )
            sites.append(resolver.resolve(request))
        for diagnostic in graph.diagnostics:
            if diagnostic.mandatory:
                continue
            diagnostics.append(replace(
                diagnostic,
                source_path=(
                    _join_relative(prefix, diagnostic.source_path)
                    if diagnostic.source_path is not None else None
                ),
            ))

    return create_code_graph(
        lineage=lineage,
        path_scope=PathScope.WORKSPACE,
        callable_index=callable_index,
        call_sites=sites,
        diagnostics=diagnostics,
        callable_bodies_examined=examined,
        callable_bodies_unavailable=unavailable,
        extraction_failures=failures,
        omitted_diagnostic_count=omitted,
    )


def _architecture_parents(
    architecture: JavaArchitectureGraph,
) -> dict[str, tuple[str, ...]]:
    parents: dict[str, set[str]] = {}
    for edge in architecture.edges:
        if edge.kind in {
            ArchitectureEdgeKind.EXTENDS,
            ArchitectureEdgeKind.IMPLEMENTS,
        }:
            parents.setdefault(edge.source, set()).add(edge.target)
    return {
        owner: tuple(sorted(values)) for owner, values in parents.items()
    }


def _canonical_parents(
    symbols: Sequence[GlobalSymbol],
) -> dict[str, tuple[str, ...]]:
    parents: dict[str, tuple[str, ...]] = {}
    for symbol in symbols:
        if symbol.kind is not GlobalSymbolKind.TYPE:
            continue
        metadata = dict(symbol.metadata)
        inherited = tuple(sorted(set(
            item for item in metadata.get('inherits', '').split(',') if item
        )))
        if inherited:
            parents[symbol.qualified_name] = inherited
    return parents


def _join_relative(prefix: str, path: str) -> str:
    if not prefix:
        return PurePosixPath(path).as_posix()
    return PurePosixPath(prefix, path).as_posix()
