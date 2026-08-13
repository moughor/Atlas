'''Immutable contracts for deterministic represented Java callable identity.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
import re

from ._validation import validated_text


CALLABLE_INDEX_FORMAT = 'moughorai.java-callable-index.v1'
CALLABLE_INDEX_PRODUCER = 'atlas-pr156/1'
CALLABLE_INDEX_SCHEMA_VERSION = 1
MAXIMUM_CALLABLE_DIAGNOSTICS = 4_096

_DIGEST = re.compile(r'[0-9a-f]{64}\Z')


class CallableKind(str, Enum):
    METHOD = 'method'
    CONSTRUCTOR = 'constructor'


class SourceClassification(str, Enum):
    PRODUCTION = 'production'
    TEST = 'test'
    GENERATED = 'generated'
    UNKNOWN = 'unknown'


class ParameterResolution(str, Enum):
    RESOLVED = 'resolved'
    EXTERNAL = 'external'
    PRIMITIVE = 'primitive'
    TYPE_VARIABLE = 'type_variable'
    AMBIGUOUS = 'ambiguous'
    UNRESOLVED = 'unresolved'


class PathScope(str, Enum):
    PROJECT = 'project'
    WORKSPACE = 'workspace'


def _text(value: object, label: str, *, maximum: int = 4_096) -> str:
    return validated_text(value, label, maximum)


def _relative_path(value: object, label: str) -> str:
    text = _text(value, label, maximum=2_048)
    if '\\' in text:
        raise ValueError(f'{label} must use workspace-relative POSIX form')
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or any(part in {'', '.', '..'} for part in path.parts)
        or any(':' in part for part in path.parts)
    ):
        raise ValueError(f'{label} must be workspace-relative')
    return path.as_posix()


@dataclass(frozen=True, order=True, slots=True)
class SourcePosition:
    line: int
    column: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.line, bool)
            or isinstance(self.column, bool)
            or not isinstance(self.line, int)
            or not isinstance(self.column, int)
            or self.line < 1
            or self.column < 1
        ):
            raise ValueError('source positions must be positive integers')

    def to_dict(self) -> dict[str, int]:
        return {'line': self.line, 'column': self.column}

    @classmethod
    def from_dict(cls, value: object) -> SourcePosition:
        if not isinstance(value, dict) or set(value) != {'line', 'column'}:
            raise TypeError('source position must contain line and column')
        return cls(value['line'], value['column'])


@dataclass(frozen=True, order=True, slots=True)
class SourceRange:
    start: SourcePosition
    end: SourcePosition

    def __post_init__(self) -> None:
        if not isinstance(self.start, SourcePosition) or not isinstance(
            self.end, SourcePosition
        ):
            raise TypeError('source range positions are invalid')
        if self.end < self.start:
            raise ValueError('source range end precedes its start')

    def to_dict(self) -> dict[str, object]:
        return {'start': self.start.to_dict(), 'end': self.end.to_dict()}

    @classmethod
    def from_dict(cls, value: object) -> SourceRange:
        if not isinstance(value, dict) or set(value) != {'start', 'end'}:
            raise TypeError('source range must contain start and end')
        return cls(
            SourcePosition.from_dict(value['start']),
            SourcePosition.from_dict(value['end']),
        )


@dataclass(frozen=True, order=True, slots=True)
class CallableSourceReference:
    path: str
    declaration: SourceRange
    body: SourceRange | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            'path',
            _relative_path(self.path, 'callable source path'),
        )
        if not isinstance(self.declaration, SourceRange):
            raise TypeError('callable declaration range is invalid')
        if self.body is not None and not isinstance(self.body, SourceRange):
            raise TypeError('callable body range is invalid')
        if self.body is not None and (
            self.body.start < self.declaration.start
            or self.body.end > self.declaration.end
        ):
            raise ValueError('callable body must be contained by its declaration')

    def to_dict(self) -> dict[str, object]:
        return {
            'path': self.path,
            'declaration': self.declaration.to_dict(),
            'body': self.body.to_dict() if self.body is not None else None,
        }

    @classmethod
    def from_dict(cls, value: object) -> CallableSourceReference:
        if not isinstance(value, dict) or set(value) != {
            'path', 'declaration', 'body'
        }:
            raise TypeError('callable source reference has invalid fields')
        body = value['body']
        return cls(
            value['path'],
            SourceRange.from_dict(value['declaration']),
            SourceRange.from_dict(body) if body is not None else None,
        )


@dataclass(frozen=True, order=True, slots=True)
class NormalizedCallableIdentity:
    owner_type: str
    kind: CallableKind
    name: str
    parameter_types: tuple[str, ...]
    parameter_resolutions: tuple[ParameterResolution, ...]
    raw_signature: str
    normalized_key: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        owner = _text(self.owner_type, 'callable owner', maximum=1_024)
        name = _text(self.name, 'callable name', maximum=256)
        if not isinstance(self.kind, CallableKind):
            raise TypeError('callable kind is invalid')
        parameters = tuple(
            _text(item, 'normalized parameter', maximum=1_024)
            for item in self.parameter_types
        )
        resolutions = tuple(self.parameter_resolutions)
        if len(parameters) != len(resolutions) or any(
            not isinstance(item, ParameterResolution) for item in resolutions
        ):
            raise ValueError('parameter resolution coverage is inconsistent')
        raw = _text(self.raw_signature, 'raw callable signature')
        key = _text(self.normalized_key, 'normalized callable key')
        separator = ','
        expected_key = (
            f'java-callable:v1:{owner}#{name}'
            f'({separator.join(parameters)})'
        )
        if key != expected_key:
            raise ValueError('normalized callable key is inconsistent')
        if (
            self.kind is CallableKind.CONSTRUCTOR
            and name != '<init>'
        ) or (
            self.kind is CallableKind.METHOD
            and name == '<init>'
        ):
            raise ValueError('callable name and kind are inconsistent')
        limitations = tuple(sorted(set(
            _text(item, 'callable limitation') for item in self.limitations
        )))
        object.__setattr__(self, 'owner_type', owner)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'parameter_types', parameters)
        object.__setattr__(self, 'parameter_resolutions', resolutions)
        object.__setattr__(self, 'raw_signature', raw)
        object.__setattr__(self, 'normalized_key', key)
        object.__setattr__(self, 'limitations', limitations)


@dataclass(frozen=True, order=True, slots=True)
class CallableIndexEntry:
    canonical_subject_id: str
    project_id: str
    identity: NormalizedCallableIdentity
    source_classification: SourceClassification
    source: CallableSourceReference
    type_kind: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            'canonical_subject_id',
            _text(self.canonical_subject_id, 'canonical callable ID', maximum=256),
        )
        object.__setattr__(
            self,
            'project_id',
            _text(self.project_id, 'callable project ID', maximum=256),
        )
        if not isinstance(self.identity, NormalizedCallableIdentity):
            raise TypeError('normalized callable identity is invalid')
        if not isinstance(self.source_classification, SourceClassification):
            raise TypeError('source classification is invalid')
        if not isinstance(self.source, CallableSourceReference):
            raise TypeError('callable source reference is invalid')
        type_kind = _text(self.type_kind, 'Java type kind', maximum=32)
        if type_kind not in {
            'class', 'interface', 'enum', 'record', 'annotation',
        }:
            raise ValueError('Java type kind is unsupported')
        if not self.canonical_subject_id.startswith(
            f'{self.identity.kind.value}:'
        ):
            raise ValueError('canonical callable ID kind is inconsistent')
        object.__setattr__(self, 'type_kind', type_kind)

    def to_dict(self) -> dict[str, object]:
        return {
            'canonical_subject_id': self.canonical_subject_id,
            'project_id': self.project_id,
            'callable_kind': self.identity.kind.value,
            'owner_type': self.identity.owner_type,
            'name': self.identity.name,
            'parameter_count': len(self.identity.parameter_types),
            'normalized_parameter_types': list(self.identity.parameter_types),
            'parameter_resolutions': [
                item.value for item in self.identity.parameter_resolutions
            ],
            'raw_signature': self.identity.raw_signature,
            'normalized_key': self.identity.normalized_key,
            'source_classification': self.source_classification.value,
            'source': self.source.to_dict(),
            'type_kind': self.type_kind,
            'limitations': list(self.identity.limitations),
        }


@dataclass(frozen=True, order=True, slots=True)
class CallableIndexDiagnostic:
    code: str
    message: str
    project_id: str
    subject_id: str | None = None
    source_path: str | None = None
    line: int | None = None
    column: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'code', _text(self.code, 'diagnostic code', maximum=64))
        object.__setattr__(self, 'message', _text(self.message, 'diagnostic message', maximum=512))
        object.__setattr__(self, 'project_id', _text(self.project_id, 'diagnostic project', maximum=256))
        if self.subject_id is not None:
            object.__setattr__(self, 'subject_id', _text(self.subject_id, 'diagnostic subject', maximum=256))
        if self.source_path is not None:
            object.__setattr__(self, 'source_path', _relative_path(self.source_path, 'diagnostic source path'))
        positions = (self.line, self.column)
        if any(item is not None for item in positions) and (
            any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in positions)
        ):
            raise ValueError('diagnostic line and column must both be positive integers')

    def to_dict(self) -> dict[str, object]:
        return {
            'code': self.code,
            'message': self.message,
            'project_id': self.project_id,
            'subject_id': self.subject_id,
            'source_path': self.source_path,
            'line': self.line,
            'column': self.column,
        }


def callable_diagnostic_sort_key(
    item: CallableIndexDiagnostic,
) -> tuple[str, str, str, int, int, str, str]:
    '''Return a total deterministic ordering for optional diagnostic fields.'''

    return (
        item.code,
        item.project_id,
        item.source_path or '',
        item.line or 0,
        item.column or 0,
        item.subject_id or '',
        item.message,
    )


@dataclass(frozen=True, slots=True)
class CallableIndexCoverage:
    selected_source_files: int
    parsed_source_files: int
    represented_callables: int
    indexed_callables: int
    unindexed_callables: int
    methods: int
    constructors: int
    classifications: tuple[tuple[str, int], ...]
    diagnostic_count: int
    omitted_diagnostic_count: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.selected_source_files,
            self.parsed_source_files,
            self.represented_callables,
            self.indexed_callables,
            self.unindexed_callables,
            self.methods,
            self.constructors,
            self.diagnostic_count,
            self.omitted_diagnostic_count,
        )
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in counts
        ):
            raise ValueError('callable-index coverage counts must be non-negative integers')
        if self.parsed_source_files > self.selected_source_files:
            raise ValueError('parsed source count exceeds selected source count')
        if self.indexed_callables + self.unindexed_callables != self.represented_callables:
            raise ValueError('represented callable coverage is inconsistent')
        if self.methods + self.constructors != self.represented_callables:
            raise ValueError('represented callable-kind coverage is inconsistent')
        normalized = tuple(sorted(
            (
                _text(name, 'classification name', maximum=32),
                count,
            )
            for name, count in self.classifications
        ))
        if len({name for name, _ in normalized}) != len(normalized) or any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for _, count in normalized
        ):
            raise ValueError('source-classification coverage is invalid')
        if any(
            name not in {item.value for item in SourceClassification}
            for name, _ in normalized
        ):
            raise ValueError('source-classification coverage is unsupported')
        if sum(count for _, count in normalized) != self.indexed_callables:
            raise ValueError('source-classification coverage is incomplete')
        object.__setattr__(self, 'classifications', normalized)

    def to_dict(self) -> dict[str, object]:
        return {
            'selected_source_files': self.selected_source_files,
            'parsed_source_files': self.parsed_source_files,
            'represented_callables': self.represented_callables,
            'indexed_callables': self.indexed_callables,
            'unindexed_callables': self.unindexed_callables,
            'methods': self.methods,
            'constructors': self.constructors,
            'classifications': dict(self.classifications),
            'diagnostic_count': self.diagnostic_count,
            'omitted_diagnostic_count': self.omitted_diagnostic_count,
        }


@dataclass(frozen=True, slots=True)
class JavaCallableIndex:
    lineage: str
    path_scope: PathScope
    entries: tuple[CallableIndexEntry, ...]
    diagnostics: tuple[CallableIndexDiagnostic, ...]
    coverage: CallableIndexCoverage
    digest: str
    input_fingerprint: str
    producer_version: str = CALLABLE_INDEX_PRODUCER
    schema_version: int = CALLABLE_INDEX_SCHEMA_VERSION
    format: str = CALLABLE_INDEX_FORMAT

    def __post_init__(self) -> None:
        lineage = _text(self.lineage, 'callable-index lineage', maximum=512)
        if not isinstance(self.path_scope, PathScope):
            raise TypeError('callable-index path scope is invalid')
        entries = tuple(sorted(self.entries, key=lambda item: (
            item.canonical_subject_id,
            item.identity.normalized_key,
        )))
        diagnostics = tuple(sorted(
            self.diagnostics,
            key=callable_diagnostic_sort_key,
        ))
        if any(not isinstance(item, CallableIndexEntry) for item in entries):
            raise TypeError('callable-index entry is invalid')
        if any(not isinstance(item, CallableIndexDiagnostic) for item in diagnostics):
            raise TypeError('callable-index diagnostic is invalid')
        if len({item.canonical_subject_id for item in entries}) != len(entries):
            raise ValueError('callable-index canonical subjects must be unique')
        if not isinstance(self.coverage, CallableIndexCoverage):
            raise TypeError('callable-index coverage is invalid')
        if self.coverage.indexed_callables != len(entries):
            raise ValueError('callable-index entry count is inconsistent')
        if self.coverage.diagnostic_count != len(diagnostics):
            raise ValueError('callable-index diagnostic count is inconsistent')
        if self.path_scope is PathScope.WORKSPACE:
            accounting_subjects = tuple(
                item.subject_id for item in diagnostics
                if item.code == 'represented_callable_unindexed'
            )
            indexed_subjects = {
                item.canonical_subject_id for item in entries
            }
            if (
                len(accounting_subjects) != self.coverage.unindexed_callables
                or any(subject is None for subject in accounting_subjects)
                or len(set(accounting_subjects)) != len(accounting_subjects)
                or any(
                    subject in indexed_subjects
                    for subject in accounting_subjects
                )
            ):
                raise ValueError(
                    'workspace unindexed-callable accounting is inconsistent'
                )
        if not isinstance(self.digest, str) or _DIGEST.fullmatch(self.digest) is None:
            raise ValueError('callable-index digest is malformed')
        fingerprint = _text(self.input_fingerprint, 'callable-index fingerprint', maximum=128)
        if fingerprint != f'java-callable-index:{self.digest}':
            raise ValueError('callable-index fingerprint is inconsistent')
        if (
            self.producer_version != CALLABLE_INDEX_PRODUCER
            or self.schema_version != CALLABLE_INDEX_SCHEMA_VERSION
            or self.format != CALLABLE_INDEX_FORMAT
        ):
            raise ValueError('unsupported callable-index producer or schema')
        object.__setattr__(self, 'lineage', lineage)
        object.__setattr__(self, 'entries', entries)
        object.__setattr__(self, 'diagnostics', diagnostics)
        object.__setattr__(self, 'input_fingerprint', fingerprint)

    def to_dict(self) -> dict[str, object]:
        return {
            'format': self.format,
            'schema_version': self.schema_version,
            'producer_version': self.producer_version,
            'lineage': self.lineage,
            'path_scope': self.path_scope.value,
            'entries': [item.to_dict() for item in self.entries],
            'diagnostics': [item.to_dict() for item in self.diagnostics],
            'coverage': self.coverage.to_dict(),
            'digest': self.digest,
            'input_fingerprint': self.input_fingerprint,
        }
