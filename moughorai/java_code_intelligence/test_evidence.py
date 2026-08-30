'''Deterministic represented Java TEST-root evidence.'''

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
import json

from .models import (
    CallableKind,
    JavaCallableIndex,
    PathScope,
    SourceClassification,
)


JAVA_TEST_EVIDENCE_FORMAT = 'moughorai.java-test-evidence.v1'
JAVA_TEST_EVIDENCE_PRODUCER = 'atlas-pr158/1'
JAVA_TEST_EVIDENCE_SCHEMA_VERSION = 1

_QUALIFIED_TEST_ANNOTATIONS = frozenset({
    'org.junit.Test',
    'org.junit.jupiter.api.RepeatedTest',
    'org.junit.jupiter.api.Test',
    'org.junit.jupiter.api.TestFactory',
    'org.junit.jupiter.api.TestTemplate',
    'org.junit.jupiter.params.ParameterizedTest',
    'org.testng.annotations.Test',
})
_SIMPLE_TEST_ANNOTATIONS = frozenset(
    item.rsplit('.', 1)[-1] for item in _QUALIFIED_TEST_ANNOTATIONS
)


class TestRootKind(str, Enum):
    TEST_METHOD_ROOT = 'test_method_root'
    TEST_APPLICATION_ROOT = 'test_application_root'
    UNKNOWN_TEST_ROOT = 'unknown_test_root'


@dataclass(frozen=True, order=True, slots=True)
class RepresentedTestCallable:
    subject_id: str
    root_kind: TestRootKind
    evidence_id: str
    annotation_identities: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise ValueError('test evidence subject is invalid')
        if not isinstance(self.root_kind, TestRootKind):
            raise TypeError('test root kind is invalid')
        if (
            not isinstance(self.evidence_id, str)
            or not self.evidence_id.startswith('evidence:')
            or len(self.evidence_id) != 73
        ):
            raise ValueError('test-root evidence ID is malformed')
        annotations = tuple(sorted(set(
            _text(item, 'test annotation', maximum=256)
            for item in self.annotation_identities
        )))
        limitations = tuple(sorted(set(
            _text(item, 'test-root limitation', maximum=512)
            for item in self.limitations
        )))
        if (
            self.root_kind is TestRootKind.TEST_METHOD_ROOT
            and not annotations
        ):
            raise ValueError('test method root requires annotation evidence')
        if (
            self.root_kind is not TestRootKind.TEST_METHOD_ROOT
            and annotations
        ):
            raise ValueError('non-method test root cannot contain annotations')
        object.__setattr__(self, 'annotation_identities', annotations)
        object.__setattr__(self, 'limitations', limitations)

    @property
    def is_root(self) -> bool:
        return self.root_kind is not TestRootKind.UNKNOWN_TEST_ROOT

    def to_dict(self) -> dict[str, object]:
        return {
            'subject_id': self.subject_id,
            'root_kind': self.root_kind.value,
            'evidence_id': self.evidence_id,
            'annotation_identities': list(self.annotation_identities),
            'limitations': list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class JavaTestEvidenceCoverage:
    represented_callables: int
    represented_test_callables: int
    represented_test_roots: int
    test_method_roots: int
    test_application_roots: int
    unknown_test_callables: int
    production_root_candidates: int
    projects_with_test_callables: int
    projects_with_test_roots: int
    projects_without_test_roots: int

    def __post_init__(self) -> None:
        values = tuple(self.to_dict().values())
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in values
        ):
            raise ValueError('test-evidence coverage counts must be non-negative')
        if (
            self.test_method_roots + self.test_application_roots
            != self.represented_test_roots
            or self.represented_test_roots + self.unknown_test_callables
            != self.represented_test_callables
            or self.projects_with_test_roots > self.projects_with_test_callables
        ):
            raise ValueError('test-evidence coverage accounting is inconsistent')

    def to_dict(self) -> dict[str, int]:
        return {
            'represented_callables': self.represented_callables,
            'represented_test_callables': self.represented_test_callables,
            'represented_test_roots': self.represented_test_roots,
            'test_method_roots': self.test_method_roots,
            'test_application_roots': self.test_application_roots,
            'unknown_test_callables': self.unknown_test_callables,
            'production_root_candidates': self.production_root_candidates,
            'projects_with_test_callables': self.projects_with_test_callables,
            'projects_with_test_roots': self.projects_with_test_roots,
            'projects_without_test_roots': self.projects_without_test_roots,
        }


@dataclass(frozen=True, slots=True)
class JavaTestEvidence:
    lineage: str
    path_scope: PathScope
    callable_index_fingerprint: str
    records: tuple[RepresentedTestCallable, ...]
    coverage: JavaTestEvidenceCoverage
    digest: str
    input_fingerprint: str
    producer_version: str = JAVA_TEST_EVIDENCE_PRODUCER
    schema_version: int = JAVA_TEST_EVIDENCE_SCHEMA_VERSION
    format: str = JAVA_TEST_EVIDENCE_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, str) or not self.lineage.strip():
            raise ValueError('test-evidence lineage is invalid')
        if not isinstance(self.path_scope, PathScope):
            raise TypeError('test-evidence path scope is invalid')
        if (
            not isinstance(self.callable_index_fingerprint, str)
            or not self.callable_index_fingerprint.startswith(
                'java-callable-index:'
            )
            or len(self.callable_index_fingerprint) != 84
        ):
            raise ValueError('test-evidence callable-index binding is malformed')
        records = tuple(sorted(self.records))
        if len({item.subject_id for item in records}) != len(records):
            raise ValueError('test callables must be represented exactly once')
        if len({item.evidence_id for item in records}) != len(records):
            raise ValueError('test evidence IDs must be unique')
        if self.coverage.represented_test_callables != len(records):
            raise ValueError('test callable coverage is inconsistent')
        if self.coverage.represented_test_roots != sum(
            item.is_root for item in records
        ):
            raise ValueError('test root coverage is inconsistent')
        if (
            not isinstance(self.digest, str) or len(self.digest) != 64
            or self.input_fingerprint != f'java-test-evidence:{self.digest}'
        ):
            raise ValueError('test-evidence digest or fingerprint is malformed')
        if (
            self.format != JAVA_TEST_EVIDENCE_FORMAT
            or self.producer_version != JAVA_TEST_EVIDENCE_PRODUCER
            or self.schema_version != JAVA_TEST_EVIDENCE_SCHEMA_VERSION
        ):
            raise ValueError('unsupported Java test-evidence schema')
        object.__setattr__(self, 'records', records)

    @property
    def roots(self) -> tuple[RepresentedTestCallable, ...]:
        return tuple(item for item in self.records if item.is_root)

    def to_dict(self) -> dict[str, object]:
        projection = _projection(
            self.lineage,
            self.path_scope,
            self.callable_index_fingerprint,
            self.records,
            self.coverage,
        )
        if _digest(projection) != self.digest:
            raise ValueError('test-evidence digest is inconsistent')
        return {
            'format': self.format,
            'schema_version': self.schema_version,
            'producer_version': self.producer_version,
            **projection,
            'digest': self.digest,
            'input_fingerprint': self.input_fingerprint,
        }


def create_java_test_evidence(
    callable_index: JavaCallableIndex,
    symbol_metadata: Sequence[Mapping[str, object]],
    *,
    lineage: str | None = None,
) -> JavaTestEvidence:
    '''Classify TEST-scoped callables without source-name heuristics.'''

    if not isinstance(callable_index, JavaCallableIndex):
        raise TypeError('authoritative callable index is required')
    metadata = _metadata_by_subject(symbol_metadata)
    records: list[RepresentedTestCallable] = []
    test_projects: set[str] = set()
    root_projects: set[str] = set()
    projects = {item.project_id for item in callable_index.entries}
    production_roots = 0

    for entry in callable_index.entries:
        values = metadata.get(entry.canonical_subject_id, {})
        entry_point = str(values.get('entry_point', ''))
        if (
            entry.source_classification is not SourceClassification.TEST
            and entry_point
        ):
            production_roots += 1
        if entry.source_classification is not SourceClassification.TEST:
            continue
        test_projects.add(entry.project_id)
        kind = TestRootKind.UNKNOWN_TEST_ROOT
        annotations: tuple[str, ...] = ()
        limitations: tuple[str, ...] = (
            'TEST source classification alone does not prove a test entry root.',
        )
        if entry.identity.kind is CallableKind.METHOD and entry_point:
            kind = TestRootKind.TEST_APPLICATION_ROOT
            limitations = (
                'A TEST-scoped application root proves represented source entry semantics, not runtime execution.',
            )
        elif entry.identity.kind is CallableKind.METHOD:
            annotations, simple = _recognized_annotations(
                values.get('annotations'),
            )
            if annotations:
                kind = TestRootKind.TEST_METHOD_ROOT
                limitations = (
                    'A represented test annotation identifies a TEST root but does not prove runtime execution or behavioral coverage.',
                    *(
                        ('The annotation simple name is represented but its import binding is unavailable.',)
                        if simple else ()
                    ),
                )
        if kind is not TestRootKind.UNKNOWN_TEST_ROOT:
            root_projects.add(entry.project_id)
        evidence_id = _record_evidence_id(
            callable_index.input_fingerprint,
            entry.canonical_subject_id,
            kind,
            annotations,
            limitations,
        )
        records.append(RepresentedTestCallable(
            entry.canonical_subject_id,
            kind,
            evidence_id,
            annotations,
            limitations,
        ))

    ordered = tuple(sorted(records))
    method_roots = sum(
        item.root_kind is TestRootKind.TEST_METHOD_ROOT for item in ordered
    )
    application_roots = sum(
        item.root_kind is TestRootKind.TEST_APPLICATION_ROOT for item in ordered
    )
    unknown = sum(
        item.root_kind is TestRootKind.UNKNOWN_TEST_ROOT for item in ordered
    )
    coverage = JavaTestEvidenceCoverage(
        callable_index.coverage.represented_callables,
        len(ordered),
        method_roots + application_roots,
        method_roots,
        application_roots,
        unknown,
        production_roots,
        len(test_projects),
        len(root_projects),
        len(projects - root_projects),
    )
    artifact_lineage = lineage or callable_index.lineage
    projection = _projection(
        artifact_lineage,
        callable_index.path_scope,
        callable_index.input_fingerprint,
        ordered,
        coverage,
    )
    digest = _digest(projection)
    return JavaTestEvidence(
        artifact_lineage,
        callable_index.path_scope,
        callable_index.input_fingerprint,
        ordered,
        coverage,
        digest,
        f'java-test-evidence:{digest}',
    )


def java_test_evidence_from_dict(
    value: object,
    callable_index: JavaCallableIndex,
) -> JavaTestEvidence:
    '''Strictly decode and validate persisted TEST-root evidence.'''

    if not isinstance(callable_index, JavaCallableIndex):
        raise TypeError('authoritative callable index is required')
    root = _mapping(value, 'Java test evidence')
    expected = {
        'format', 'schema_version', 'producer_version', 'lineage',
        'path_scope', 'callable_index_fingerprint', 'records', 'coverage',
        'digest', 'input_fingerprint',
    }
    if set(root) != expected:
        raise ValueError('Java test evidence contains missing or unknown fields')
    if (
        root['format'] != JAVA_TEST_EVIDENCE_FORMAT
        or root['producer_version'] != JAVA_TEST_EVIDENCE_PRODUCER
        or root['schema_version'] != JAVA_TEST_EVIDENCE_SCHEMA_VERSION
    ):
        raise ValueError('unsupported Java test-evidence schema')
    if root['callable_index_fingerprint'] != callable_index.input_fingerprint:
        raise ValueError('test-evidence callable-index binding is inconsistent')
    entries = {
        item.canonical_subject_id: item for item in callable_index.entries
    }
    records = tuple(_record(item) for item in _array(root['records'], 'records'))
    for item in records:
        entry = entries.get(item.subject_id)
        if (
            entry is None
            or entry.source_classification is not SourceClassification.TEST
            or item.evidence_id != _record_evidence_id(
                callable_index.input_fingerprint,
                item.subject_id,
                item.root_kind,
                item.annotation_identities,
                item.limitations,
            )
        ):
            raise ValueError('test evidence conflicts with callable identity')
    expected_test_subjects = {
        item.canonical_subject_id for item in callable_index.entries
        if item.source_classification is SourceClassification.TEST
    }
    if {item.subject_id for item in records} != expected_test_subjects:
        raise ValueError('test callable accounting is incomplete')
    coverage = _coverage(root['coverage'])
    artifact = JavaTestEvidence(
        _text(root['lineage'], 'lineage'),
        PathScope(_text(root['path_scope'], 'path scope')),
        str(root['callable_index_fingerprint']),
        records,
        coverage,
        str(root['digest']),
        str(root['input_fingerprint']),
    )
    if artifact.to_dict() != dict(root):
        raise ValueError('test-evidence digest, ordering, or coverage is inconsistent')
    return artifact


def _recognized_annotations(value: object) -> tuple[tuple[str, ...], bool]:
    if isinstance(value, str):
        tokens = tuple(item.strip() for item in value.split(',') if item.strip())
    elif isinstance(value, (list, tuple)):
        tokens = tuple(str(item).strip() for item in value if str(item).strip())
    else:
        tokens = ()
    qualified = tuple(sorted(set(
        item for item in tokens if item in _QUALIFIED_TEST_ANNOTATIONS
    )))
    if qualified:
        return qualified, False
    simple = tuple(sorted(set(
        item for item in tokens if item in _SIMPLE_TEST_ANNOTATIONS
    )))
    return simple, bool(simple)


def _metadata_by_subject(
    values: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for item in values:
        subject_id = str(item.get('id', ''))
        raw = item.get('metadata', {})
        if subject_id and isinstance(raw, Mapping):
            result[subject_id] = raw
    return result


def _record_evidence_id(
    binding: str,
    subject_id: str,
    kind: TestRootKind,
    annotations: tuple[str, ...],
    limitations: tuple[str, ...],
) -> str:
    data = {
        "producer": JAVA_TEST_EVIDENCE_PRODUCER,
        "callable_index_fingerprint": binding,
        "subject_id": subject_id,
        "root_kind": kind.value,
        "annotation_identities": list(sorted(set(annotations))),
        "limitations": list(sorted(set(limitations))),
    }
    return f'evidence:{_digest(data)}'


def _projection(
    lineage: str,
    path_scope: PathScope,
    binding: str,
    records: tuple[RepresentedTestCallable, ...],
    coverage: JavaTestEvidenceCoverage,
) -> dict[str, object]:
    return {
        'lineage': lineage,
        'path_scope': path_scope.value,
        'callable_index_fingerprint': binding,
        'records': [item.to_dict() for item in records],
        'coverage': coverage.to_dict(),
    }


def _record(value: object) -> RepresentedTestCallable:
    raw = _mapping(value, 'test callable record')
    if set(raw) != {
        'subject_id', 'root_kind', 'evidence_id',
        'annotation_identities', 'limitations',
    }:
        raise ValueError('test callable record contains invalid fields')
    return RepresentedTestCallable(
        _text(raw['subject_id'], 'test subject'),
        TestRootKind(_text(raw['root_kind'], 'test root kind')),
        _text(raw['evidence_id'], 'test evidence ID'),
        tuple(_text(item, 'test annotation') for item in _array(
            raw['annotation_identities'], 'test annotations',
        )),
        tuple(_text(item, 'test limitation') for item in _array(
            raw['limitations'], 'test limitations',
        )),
    )


def _coverage(value: object) -> JavaTestEvidenceCoverage:
    raw = _mapping(value, 'test-evidence coverage')
    names = tuple(JavaTestEvidenceCoverage.__dataclass_fields__)
    if set(raw) != set(names):
        raise ValueError('test-evidence coverage contains invalid fields')
    return JavaTestEvidenceCoverage(*(
        _non_negative(raw[name], name) for name in names
    ))


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f'{label} must be an object')
    return value


def _array(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f'{label} must be an array')
    return tuple(value)


def _text(value: object, label: str, maximum: int = 1_024) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{label} must be a string')
    result = value.strip()
    if not result or len(result) > maximum or any(
        ord(character) < 32 for character in result
    ):
        raise ValueError(f'{label} is invalid')
    return result


def _non_negative(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError(f'{label} must be a non-negative integer')
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('utf-8')).hexdigest()
