'''Build and merge compact deterministic Java callable-index artifacts.'''

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Protocol

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.java_ast.ast_nodes import CompilationUnit
from moughorai.java_ast.models import SourceSpan
from moughorai.java_symbols import (
    CallableSymbol,
    ConstructorSymbol,
    JavaSymbolIndex,
    SymbolKind,
    TypeSymbol,
)

from .identity import (
    CallableIdentityNormalizer,
    SourceClassificationResult,
    classify_source,
)
from .models import (
    CallableIndexCoverage,
    CallableIndexDiagnostic,
    CallableIndexEntry,
    CallableKind,
    CallableSourceReference,
    JavaCallableIndex,
    MAXIMUM_CALLABLE_DIAGNOSTICS,
    PathScope,
    SourceClassification,
    SourcePosition,
    SourceRange,
    callable_diagnostic_sort_key,
)


class _Digest(Protocol):
    def update(self, value: bytes) -> object:
        ...


_MANDATORY_ACCOUNTING_DIAGNOSTIC_CODES = frozenset({
    'callable_identity_mismatch',
    'canonical_subject_not_in_workspace',
    'canonical_subject_unavailable',
    'duplicate_canonical_callable',
    'duplicate_workspace_callable',
    'owner_type_kind_unavailable',
    'represented_callable_unindexed',
    'source_context_unavailable',
    'source_range_unavailable',
    'unsupported_declaration',
    'workspace_path_unavailable',
})


class CallableIndexBuilder:
    '''Index represented methods and constructors exactly once when possible.'''

    def build(
        self,
        index: JavaSymbolIndex,
        units: Sequence[CompilationUnit],
        sources: Sequence[Path],
        canonical_symbols: Sequence[GlobalSymbol],
        *,
        project_id: str,
        project_root: Path,
        source_roots: Iterable[object] = (),
        lineage: str,
        selected_source_files: int | None = None,
        diagnostics: Iterable[CallableIndexDiagnostic] = (),
    ) -> JavaCallableIndex:
        if len(units) != len(sources):
            raise ValueError('callable-index units and sources must align')
        roots = tuple(source_roots)
        unit_by_source = {
            source.resolve(): unit
            for source, unit in zip(sources, units, strict=True)
        }
        classifications = {
            source.resolve(): classify_source(source, project_root, roots)
            for source in sources
        }
        canonical = {
            (item.kind.value, item.qualified_name): item
            for item in canonical_symbols
        }
        type_kinds = {
            item.qualified_name: item.type_kind.value
            for item in index.by_kind(SymbolKind.TYPE)
            if isinstance(item, TypeSymbol)
        }
        normalizer = CallableIdentityNormalizer(index)
        entries: list[CallableIndexEntry] = []
        findings = list(diagnostics)
        unindexed = 0
        seen: set[str] = set()

        callables = tuple(
            item for item in index.symbols
            if isinstance(item, CallableSymbol)
        )
        for symbol in sorted(
            callables,
            key=lambda item: (
                item.qualified_name,
                item.kind.value,
                str(item.source or ''),
            ),
        ):
            expected_kind = (
                GlobalSymbolKind.CONSTRUCTOR
                if isinstance(symbol, ConstructorSymbol)
                else GlobalSymbolKind.METHOD
            )
            canonical_symbol = canonical.get((
                expected_kind.value,
                symbol.qualified_name,
            ))
            if canonical_symbol is None:
                unindexed += 1
                findings.append(_diagnostic(
                    'canonical_subject_unavailable',
                    'Callable has no matching existing canonical subject ID.',
                    project_id,
                    symbol,
                    project_root,
                ))
                continue
            subject_id = str(canonical_symbol.id)
            if subject_id in seen:
                unindexed += 1
                findings.append(_diagnostic(
                    'duplicate_canonical_callable',
                    'Duplicate callable mapped to an existing canonical subject ID.',
                    project_id,
                    symbol,
                    project_root,
                    subject_id=subject_id,
                ))
                continue
            if symbol.source is None or symbol.declaration_span is None:
                unindexed += 1
                findings.append(_diagnostic(
                    'source_range_unavailable',
                    'Callable declaration range is unavailable.',
                    project_id,
                    symbol,
                    project_root,
                    subject_id=subject_id,
                ))
                continue
            resolved_source = symbol.source.resolve()
            unit = unit_by_source.get(resolved_source)
            classification = classifications.get(resolved_source)
            if unit is None or classification is None or classification.relative_path is None:
                unindexed += 1
                findings.append(_diagnostic(
                    'source_context_unavailable',
                    'Callable source context is unavailable or outside the project.',
                    project_id,
                    symbol,
                    project_root,
                    subject_id=subject_id,
                ))
                continue
            type_kind = type_kinds.get(symbol.owner or '')
            if type_kind is None:
                unindexed += 1
                findings.append(_diagnostic(
                    'owner_type_kind_unavailable',
                    'Callable owner type kind is unavailable.',
                    project_id,
                    symbol,
                    project_root,
                    subject_id=subject_id,
                ))
                continue
            try:
                identity = normalizer.normalize(symbol, unit)
            except (TypeError, ValueError):
                unindexed += 1
                findings.append(_diagnostic(
                    'unsupported_declaration',
                    'Callable declaration cannot be normalized deterministically.',
                    project_id,
                    symbol,
                    project_root,
                    subject_id=subject_id,
                ))
                continue
            entries.append(CallableIndexEntry(
                subject_id,
                project_id,
                identity,
                classification.classification,
                CallableSourceReference(
                    classification.relative_path,
                    _source_range(symbol.declaration_span),
                    (
                        _source_range(symbol.body_span)
                        if symbol.body_span is not None
                        else None
                    ),
                ),
                type_kind,
            ))
            seen.add(subject_id)
            findings.extend(self._entry_diagnostics(
                entries[-1],
                classification,
            ))

        findings.extend(self._implicit_constructor_diagnostics(
            index,
            canonical,
            classifications,
            project_root,
            project_id,
        ))
        return create_callable_index(
            lineage=lineage,
            path_scope=PathScope.PROJECT,
            entries=entries,
            diagnostics=findings,
            selected_source_files=(
                len(sources)
                if selected_source_files is None
                else selected_source_files
            ),
            parsed_source_files=len(sources),
            represented_callables=len(callables),
            unindexed_callables=unindexed,
            represented_methods=sum(
                not isinstance(item, ConstructorSymbol)
                for item in callables
            ),
            represented_constructors=sum(
                isinstance(item, ConstructorSymbol) for item in callables
            ),
        )

    @staticmethod
    def _entry_diagnostics(
        entry: CallableIndexEntry,
        classification: SourceClassificationResult,
    ) -> tuple[CallableIndexDiagnostic, ...]:
        findings: list[CallableIndexDiagnostic] = []
        source = entry.source
        position = source.declaration.start
        if source.body is None:
            findings.append(CallableIndexDiagnostic(
                'body_unavailable',
                'Callable has no represented executable body.',
                entry.project_id,
                entry.canonical_subject_id,
                source.path,
                position.line,
                position.column,
            ))
        if entry.source_classification is SourceClassification.UNKNOWN:
            code = (
                'source_classification_ambiguous'
                if classification.evidence.startswith('ambiguous-')
                else 'source_classification_unknown'
            )
            findings.append(CallableIndexDiagnostic(
                code,
                'Callable source classification is unknown.',
                entry.project_id,
                entry.canonical_subject_id,
                source.path,
                position.line,
                position.column,
            ))
        if entry.source_classification is SourceClassification.GENERATED:
            findings.append(CallableIndexDiagnostic(
                'generated_callable',
                'Callable is represented from generated source.',
                entry.project_id,
                entry.canonical_subject_id,
                source.path,
                position.line,
                position.column,
            ))
        for limitation in sorted(set(classification.limitations)):
            findings.append(CallableIndexDiagnostic(
                'source_classification_limitation',
                limitation,
                entry.project_id,
                entry.canonical_subject_id,
                source.path,
                position.line,
                position.column,
            ))
        for limitation in entry.identity.limitations:
            findings.append(CallableIndexDiagnostic(
                _identity_limitation_code(limitation),
                limitation,
                entry.project_id,
                entry.canonical_subject_id,
                source.path,
                position.line,
                position.column,
            ))
        return tuple(findings)
    @staticmethod
    def _implicit_constructor_diagnostics(
        index: JavaSymbolIndex,
        canonical: Mapping[tuple[str, str], GlobalSymbol],
        classifications: Mapping[Path, object],
        project_root: Path,
        project_id: str,
    ) -> tuple[CallableIndexDiagnostic, ...]:
        explicit_owners = {
            item.owner for item in index.by_kind(SymbolKind.CONSTRUCTOR)
            if isinstance(item, ConstructorSymbol)
        }
        findings: list[CallableIndexDiagnostic] = []
        for symbol in index.by_kind(SymbolKind.TYPE):
            if (
                not isinstance(symbol, TypeSymbol)
                or symbol.type_kind.value not in {'class', 'record', 'enum'}
                or symbol.qualified_name in explicit_owners
            ):
                continue
            canonical_symbol = canonical.get((
                GlobalSymbolKind.TYPE.value,
                symbol.qualified_name,
            ))
            source_path = None
            if symbol.source is not None:
                classification = classifications.get(symbol.source.resolve())
                source_path = getattr(classification, 'relative_path', None)
            findings.append(CallableIndexDiagnostic(
                'implicit_constructor_unrepresented',
                'Implicit constructor has no represented callable declaration.',
                project_id,
                (
                    str(canonical_symbol.id)
                    if canonical_symbol is not None
                    else None
                ),
                source_path,
            ))
        return tuple(findings)


def _source_range(span: SourceSpan) -> SourceRange:
    return SourceRange(
        SourcePosition(span.start.line, span.start.column),
        SourcePosition(span.end.line, span.end.column),
    )


def _identity_limitation_code(limitation: str) -> str:
    if limitation == 'Parameter type resolution is ambiguous.':
        return 'ambiguous_parameter_type'
    if limitation == 'Parameter type syntax is unsupported.':
        return 'unsupported_parameter_type'
    if limitation == 'Generic type syntax was not balanced.':
        return 'unbalanced_generic_parameter_type'
    if limitation.startswith('Parameter type'):
        return 'unresolved_parameter_type'
    return 'callable_identity_limitation'


def _diagnostic(
    code: str,
    message: str,
    project_id: str,
    symbol: CallableSymbol,
    project_root: Path,
    *,
    subject_id: str | None = None,
) -> CallableIndexDiagnostic:
    path = None
    if symbol.source is not None:
        try:
            path = symbol.source.resolve().relative_to(
                project_root.resolve()
            ).as_posix()
        except (OSError, RuntimeError, ValueError):
            path = None
    position = (
        symbol.declaration_span.start
        if symbol.declaration_span is not None
        else None
    )
    return CallableIndexDiagnostic(
        code,
        message,
        project_id,
        subject_id,
        path,
        position.line if position is not None else None,
        position.column if position is not None else None,
    )


def create_callable_index(
    *,
    lineage: str,
    path_scope: PathScope,
    entries: Iterable[CallableIndexEntry],
    diagnostics: Iterable[CallableIndexDiagnostic],
    selected_source_files: int,
    parsed_source_files: int,
    represented_callables: int,
    unindexed_callables: int,
    represented_methods: int,
    represented_constructors: int,
    omitted_diagnostic_count: int = 0,
) -> JavaCallableIndex:
    ordered_entries = tuple(sorted(
        entries,
        key=lambda item: (
            item.canonical_subject_id,
            item.identity.normalized_key,
        ),
    ))
    unique_diagnostics = tuple(sorted(
        set(diagnostics),
        key=callable_diagnostic_sort_key,
    ))
    mandatory_diagnostics = tuple(
        item for item in unique_diagnostics
        if item.code in _MANDATORY_ACCOUNTING_DIAGNOSTIC_CODES
    )
    ordinary_diagnostics = tuple(
        item for item in unique_diagnostics
        if item.code not in _MANDATORY_ACCOUNTING_DIAGNOSTIC_CODES
    )
    retained_diagnostics = tuple(sorted(
        (
            *mandatory_diagnostics,
            *ordinary_diagnostics[:MAXIMUM_CALLABLE_DIAGNOSTICS],
        ),
        key=callable_diagnostic_sort_key,
    ))
    omitted = (
        omitted_diagnostic_count
        + len(ordinary_diagnostics)
        - min(len(ordinary_diagnostics), MAXIMUM_CALLABLE_DIAGNOSTICS)
    )
    classifications = Counter(
        item.source_classification.value for item in ordered_entries
    )
    coverage = CallableIndexCoverage(
        selected_source_files,
        parsed_source_files,
        represented_callables,
        len(ordered_entries),
        unindexed_callables,
        represented_methods,
        represented_constructors,
        tuple(classifications.items()),
        len(retained_diagnostics),
        omitted,
    )
    digest_builder = hashlib.sha256()
    _digest_value(digest_builder, ('lineage', lineage))
    _digest_value(digest_builder, ('path_scope', path_scope.value))
    for item in ordered_entries:
        _digest_value(digest_builder, ('entry', item.to_dict()))
    for item in retained_diagnostics:
        _digest_value(digest_builder, ('diagnostic', item.to_dict()))
    _digest_value(digest_builder, ('coverage', coverage.to_dict()))
    digest = digest_builder.hexdigest()
    return JavaCallableIndex(
        lineage,
        path_scope,
        ordered_entries,
        retained_diagnostics,
        coverage,
        digest,
        f'java-callable-index:{digest}',
    )


def _digest_value(digest: _Digest, value: object) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')
    digest.update(len(payload).to_bytes(8, 'big'))
    digest.update(payload)


def merge_callable_indices(
    indices: Mapping[str, JavaCallableIndex],
    *,
    workspace_root: Path,
    project_paths: Mapping[str, Path],
    canonical_symbols: Sequence[GlobalSymbol],
    lineage: str,
) -> JavaCallableIndex:
    '''Rebase project artifacts and reconcile all represented Java callables.'''

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

    expected = {
        str(symbol.id): symbol
        for symbol in canonical_symbols
        if (
            symbol.kind in {
                GlobalSymbolKind.METHOD,
                GlobalSymbolKind.CONSTRUCTOR,
            }
            and symbol.source is not None
            and symbol.source.suffix.casefold() == '.java'
        )
    }
    entries: dict[str, CallableIndexEntry] = {}
    diagnostics: list[CallableIndexDiagnostic] = []
    selected_sources = 0
    parsed_sources = 0
    omitted_diagnostics = 0

    for project_id, index in sorted(indices.items()):
        selected_sources += index.coverage.selected_source_files
        parsed_sources += index.coverage.parsed_source_files
        omitted_diagnostics += index.coverage.omitted_diagnostic_count
        prefix = prefixes.get(project_id)
        for entry in index.entries:
            canonical = expected.get(entry.canonical_subject_id)
            if canonical is None:
                diagnostics.append(CallableIndexDiagnostic(
                    'canonical_subject_not_in_workspace',
                    'Project callable is absent from the final canonical symbol set.',
                    project_id,
                    entry.canonical_subject_id,
                ))
                continue
            if (
                entry.project_id != project_id
                or canonical.project_id != project_id
                or canonical.qualified_name
                != entry.identity.raw_signature.replace('...', '')
            ):
                diagnostics.append(CallableIndexDiagnostic(
                    'callable_identity_mismatch',
                    'Callable identity does not match its canonical workspace subject.',
                    project_id,
                    entry.canonical_subject_id,
                ))
                continue
            if prefix is None:
                diagnostics.append(CallableIndexDiagnostic(
                    'workspace_path_unavailable',
                    'Project path cannot be made workspace-relative.',
                    project_id,
                    entry.canonical_subject_id,
                ))
                continue
            rebased = replace(
                entry,
                source=replace(
                    entry.source,
                    path=_join_relative(prefix, entry.source.path),
                ),
            )
            previous = entries.get(entry.canonical_subject_id)
            if previous is None:
                entries[entry.canonical_subject_id] = rebased
            elif previous != rebased:
                diagnostics.append(CallableIndexDiagnostic(
                    'duplicate_workspace_callable',
                    'Multiple project entries map to one canonical callable ID.',
                    project_id,
                    entry.canonical_subject_id,
                    rebased.source.path,
                    rebased.source.declaration.start.line,
                    rebased.source.declaration.start.column,
                ))
        for finding in index.diagnostics:
            path = (
                _join_relative(prefix, finding.source_path)
                if prefix is not None and finding.source_path is not None
                else None
            )
            diagnostics.append(replace(finding, source_path=path))

    for subject_id, symbol in sorted(expected.items()):
        if subject_id in entries:
            continue
        path = _workspace_relative_source(symbol.source, workspace_root)
        diagnostics.append(CallableIndexDiagnostic(
            'represented_callable_unindexed',
            'Represented Java callable has no callable-index entry.',
            symbol.project_id or 'unknown',
            subject_id,
            path,
        ))

    ordered_entries = tuple(entries.values())
    return create_callable_index(
        lineage=lineage,
        path_scope=PathScope.WORKSPACE,
        entries=ordered_entries,
        diagnostics=diagnostics,
        selected_source_files=selected_sources,
        parsed_source_files=parsed_sources,
        represented_callables=len(expected),
        unindexed_callables=len(expected) - len(ordered_entries),
        represented_methods=sum(
            item.kind is GlobalSymbolKind.METHOD
            for item in expected.values()
        ),
        represented_constructors=sum(
            item.kind is GlobalSymbolKind.CONSTRUCTOR
            for item in expected.values()
        ),
        omitted_diagnostic_count=omitted_diagnostics,
    )


def _join_relative(prefix: str, path: str) -> str:
    if not prefix:
        return PurePosixPath(path).as_posix()
    return PurePosixPath(prefix, path).as_posix()


def _workspace_relative_source(
    source: Path | None,
    workspace_root: Path,
) -> str | None:
    if source is None:
        return None
    try:
        return source.resolve().relative_to(
            workspace_root.resolve()
        ).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
