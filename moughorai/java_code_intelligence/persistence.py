'''Strict source-safe persistence for Java callable-index artifacts.'''

from __future__ import annotations

from collections.abc import Mapping

from .callable_index import create_callable_index
from .models import (
    CALLABLE_INDEX_FORMAT,
    CALLABLE_INDEX_PRODUCER,
    CALLABLE_INDEX_SCHEMA_VERSION,
    CallableIndexDiagnostic,
    CallableIndexEntry,
    CallableKind,
    CallableSourceReference,
    JavaCallableIndex,
    NormalizedCallableIdentity,
    ParameterResolution,
    PathScope,
    SourceClassification,
)


_ROOT_FIELDS = {
    'format',
    'schema_version',
    'producer_version',
    'lineage',
    'path_scope',
    'entries',
    'diagnostics',
    'coverage',
    'digest',
    'input_fingerprint',
}
_ENTRY_FIELDS = {
    'canonical_subject_id',
    'project_id',
    'callable_kind',
    'owner_type',
    'name',
    'parameter_count',
    'normalized_parameter_types',
    'parameter_resolutions',
    'raw_signature',
    'normalized_key',
    'source_classification',
    'source',
    'type_kind',
    'limitations',
}
_DIAGNOSTIC_FIELDS = {
    'code', 'message', 'project_id', 'subject_id',
    'source_path', 'line', 'column',
}
_COVERAGE_FIELDS = {
    'selected_source_files',
    'parsed_source_files',
    'represented_callables',
    'indexed_callables',
    'unindexed_callables',
    'methods',
    'constructors',
    'classifications',
    'diagnostic_count',
    'omitted_diagnostic_count',
}


def callable_index_to_dict(value: JavaCallableIndex) -> dict[str, object]:
    if not isinstance(value, JavaCallableIndex):
        raise TypeError('callable-index artifact is invalid')
    return value.to_dict()


def callable_index_from_dict(value: object) -> JavaCallableIndex:
    root = _mapping(value, 'callable-index artifact')
    _exact_fields(root, _ROOT_FIELDS, 'callable-index artifact')
    if (
        root['format'] != CALLABLE_INDEX_FORMAT
        or root['producer_version'] != CALLABLE_INDEX_PRODUCER
        or _integer(root['schema_version'], 'callable-index schema')
        != CALLABLE_INDEX_SCHEMA_VERSION
    ):
        raise ValueError('unsupported callable-index producer or schema')

    raw_entries = _sequence(root['entries'], 'callable entries')
    raw_diagnostics = _sequence(
        root['diagnostics'],
        'callable diagnostics',
    )
    entries = tuple(_entry(item) for item in raw_entries)
    diagnostics = tuple(_diagnostic(item) for item in raw_diagnostics)
    coverage = _mapping(root['coverage'], 'callable-index coverage')
    _exact_fields(coverage, _COVERAGE_FIELDS, 'callable-index coverage')
    classifications = _mapping(
        coverage['classifications'],
        'source-classification coverage',
    )
    represented = _integer(
        coverage['represented_callables'],
        'represented callable count',
    )
    indexed = _integer(
        coverage['indexed_callables'],
        'indexed callable count',
    )
    if indexed != len(entries):
        raise ValueError('serialized callable entry count is inconsistent')
    if _integer(
        coverage['diagnostic_count'],
        'callable diagnostic count',
    ) != len(diagnostics):
        raise ValueError('serialized callable diagnostic count is inconsistent')
    if sum(
        _integer(item, 'source-classification count')
        for item in classifications.values()
    ) != indexed:
        raise ValueError('serialized source-classification coverage is inconsistent')

    rebuilt = create_callable_index(
        lineage=_string(root['lineage'], 'callable-index lineage'),
        path_scope=PathScope(_string(root['path_scope'], 'path scope')),
        entries=entries,
        diagnostics=diagnostics,
        selected_source_files=_integer(
            coverage['selected_source_files'],
            'selected source count',
        ),
        parsed_source_files=_integer(
            coverage['parsed_source_files'],
            'parsed source count',
        ),
        represented_callables=represented,
        unindexed_callables=_integer(
            coverage['unindexed_callables'],
            'unindexed callable count',
        ),
        represented_methods=_integer(
            coverage['methods'],
            'represented method count',
        ),
        represented_constructors=_integer(
            coverage['constructors'],
            'represented constructor count',
        ),
        omitted_diagnostic_count=_integer(
            coverage['omitted_diagnostic_count'],
            'omitted diagnostic count',
        ),
    )
    if (
        rebuilt.digest != root['digest']
        or rebuilt.input_fingerprint != root['input_fingerprint']
        or rebuilt.lineage != root['lineage']
        or rebuilt.path_scope.value != root['path_scope']
        or rebuilt.coverage.to_dict() != dict(coverage)
        or any(
            item.to_dict() != dict(_mapping(raw, 'callable-index entry'))
            for item, raw in zip(
                rebuilt.entries,
                raw_entries,
                strict=True,
            )
        )
        or any(
            item.to_dict() != dict(_mapping(raw, 'callable-index diagnostic'))
            for item, raw in zip(
                rebuilt.diagnostics,
                raw_diagnostics,
                strict=True,
            )
        )
    ):
        raise ValueError('callable-index digest, ordering, or coverage is inconsistent')
    return rebuilt


def _entry(value: object) -> CallableIndexEntry:
    raw = _mapping(value, 'callable-index entry')
    _exact_fields(raw, _ENTRY_FIELDS, 'callable-index entry')
    parameters = tuple(
        _string(item, 'normalized parameter')
        for item in _sequence(
            raw['normalized_parameter_types'],
            'normalized parameters',
        )
    )
    resolutions = tuple(
        ParameterResolution(_string(item, 'parameter resolution'))
        for item in _sequence(
            raw['parameter_resolutions'],
            'parameter resolutions',
        )
    )
    count = _integer(raw['parameter_count'], 'parameter count')
    if count != len(parameters) or len(parameters) != len(resolutions):
        raise ValueError('callable parameter coverage is inconsistent')
    limitations = tuple(
        _string(item, 'callable limitation')
        for item in _sequence(raw['limitations'], 'callable limitations')
    )
    identity = NormalizedCallableIdentity(
        _string(raw['owner_type'], 'callable owner'),
        CallableKind(_string(raw['callable_kind'], 'callable kind')),
        _string(raw['name'], 'callable name'),
        parameters,
        resolutions,
        _string(raw['raw_signature'], 'raw callable signature'),
        _string(raw['normalized_key'], 'normalized callable key'),
        limitations,
    )
    source = CallableSourceReference.from_dict(
        dict(_mapping(raw['source'], 'callable source'))
    )
    return CallableIndexEntry(
        _string(raw['canonical_subject_id'], 'canonical callable ID'),
        _string(raw['project_id'], 'callable project ID'),
        identity,
        SourceClassification(_string(
            raw['source_classification'],
            'source classification',
        )),
        source,
        _string(raw['type_kind'], 'Java type kind'),
    )


def _diagnostic(value: object) -> CallableIndexDiagnostic:
    raw = _mapping(value, 'callable-index diagnostic')
    _exact_fields(raw, _DIAGNOSTIC_FIELDS, 'callable-index diagnostic')
    return CallableIndexDiagnostic(
        _string(raw['code'], 'diagnostic code'),
        _string(raw['message'], 'diagnostic message'),
        _string(raw['project_id'], 'diagnostic project'),
        (
            _string(raw['subject_id'], 'diagnostic subject')
            if raw['subject_id'] is not None
            else None
        ),
        (
            _string(raw['source_path'], 'diagnostic source path')
            if raw['source_path'] is not None
            else None
        ),
        (
            _integer(raw['line'], 'diagnostic line')
            if raw['line'] is not None
            else None
        ),
        (
            _integer(raw['column'], 'diagnostic column')
            if raw['column'] is not None
            else None
        ),
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f'{label} must be an object')
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f'{label} keys must be strings')
    return value


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f'{label} must be an array')
    return tuple(value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f'{label} must be a non-empty string')
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f'{label} must be a non-negative integer')
    return value


def _exact_fields(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f'{label} contains missing or unknown fields')
