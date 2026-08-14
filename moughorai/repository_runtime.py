'''Bounded in-process reuse of validated repository intelligence.'''

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import TypeVar

from moughorai.code_intelligence import JavaCodeIntelligenceService
from moughorai.impact_analysis import ImpactPredictionService
from moughorai.measurement import MeasurementSession
from moughorai.semantic_search import SemanticSearchService
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver


_T = TypeVar('_T')
_LINEAGE_FIELDS = (
    'format', 'schema_version', 'producer_version', 'input_fingerprint',
    'digest', 'lineage', 'callable_index_fingerprint', 'graph_digest',
    'snapshot_lineage', 'configuration_fingerprint',
)
_ARTIFACT_KEYS = (
    'semantic_graph', 'java_callable_index', 'java_code_graph',
    'java_test_evidence', 'reachability',
)


@dataclass(frozen=True, slots=True)
class RepositoryRuntimeIdentity:
    '''Immutable authority key for one already-validated snapshot.'''

    snapshot_id: str
    schema_version: int
    workspace_fingerprint: str
    analyzer_version: str
    workspace_root: str | None
    artifacts: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        workspace_root: str | Path | None = None,
    ) -> RepositoryRuntimeIdentity:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError('repository runtime requires a validated snapshot')
        root = (
            Path(workspace_root).expanduser().resolve().as_posix()
            if workspace_root is not None else None
        )
        return cls(
            snapshot.snapshot_id,
            snapshot.schema_version,
            snapshot.workspace_fingerprint,
            snapshot.analyzer_version,
            root,
            tuple(
                (key, _artifact_lineage(snapshot.semantic_context.get(key)))
                for key in _ARTIFACT_KEYS
            ),
        )


@dataclass(frozen=True, slots=True)
class RepositoryRuntimeStatistics:
    runtime_build_count: int
    reuse_count: int
    component_build_counts: tuple[tuple[str, int], ...]
    current_identity: RepositoryRuntimeIdentity | None


class RepositoryIntelligenceRuntime:
    '''Own one snapshot's lazily reconstructed immutable authorities.'''

    def __init__(
        self,
        snapshot: AtlasSemanticSnapshot,
        *,
        identity: RepositoryRuntimeIdentity | None = None,
        workspace_root: str | Path | None = None,
        measurement: MeasurementSession | None = None,
    ) -> None:
        actual = RepositoryRuntimeIdentity.from_snapshot(
            snapshot, workspace_root=workspace_root,
        )
        if identity is not None and identity != actual:
            raise ValueError('repository runtime identity does not match snapshot lineage')
        self.snapshot = snapshot
        self.identity = actual
        self.measurement = measurement or MeasurementSession()
        self._lock = RLock()
        self._closed = False
        self._components: dict[str, object] = {}
        self._structured: dict[bool, object] = {}
        self._build_counts: dict[str, int] = {}

    def require_snapshot(self, snapshot: AtlasSemanticSnapshot) -> None:
        if self._closed:
            raise RuntimeError('repository runtime is closed')
        actual = RepositoryRuntimeIdentity.from_snapshot(
            snapshot, workspace_root=self.identity.workspace_root,
        )
        if actual != self.identity:
            raise ValueError('repository runtime does not match supplied snapshot lineage')

    @property
    def resolver(self) -> CanonicalSubjectResolver:
        return self._materialize(
            'canonical_subject_resolver',
            lambda: CanonicalSubjectResolver.from_snapshot(self.snapshot),
        )

    @property
    def java_code_intelligence(self) -> JavaCodeIntelligenceService:
        return self._materialize(
            'java_code_intelligence',
            lambda: JavaCodeIntelligenceService.from_snapshot(self.snapshot),
        )

    @property
    def semantic_search(self) -> SemanticSearchService:
        return self._materialize(
            'semantic_search',
            lambda: SemanticSearchService._from_runtime(
                self.snapshot,
                resolver=self.resolver,
                measurement=self.measurement,
            ),
        )

    @property
    def impact_prediction(self) -> ImpactPredictionService:
        return self._materialize(
            'impact_prediction',
            lambda: ImpactPredictionService(
                self.resolver,
                snapshot_id=self.snapshot.snapshot_id,
                analyzer_version=self.snapshot.analyzer_version,
                semantic_context=self.snapshot.semantic_context,
                measurement=self.measurement,
            ),
        )

    def structured_explanation(self, *, include_code_intelligence: bool = True):
        if not isinstance(include_code_intelligence, bool):
            raise TypeError('include_code_intelligence must be a boolean')
        with self._lock:
            if self._closed:
                raise RuntimeError('repository runtime is closed')
            existing = self._structured.get(include_code_intelligence)
            if existing is not None:
                return existing
            from moughorai.structured_explanation import StructuredExplanationService

            service = StructuredExplanationService(
                self.snapshot,
                runtime=self,
                include_code_intelligence=include_code_intelligence,
            )
            self._structured[include_code_intelligence] = service
            name = f'structured_explanation:{str(include_code_intelligence).lower()}'
            self._build_counts[name] = self._build_counts.get(name, 0) + 1
            return service

    @property
    def component_build_counts(self) -> tuple[tuple[str, int], ...]:
        with self._lock:
            return tuple(sorted(self._build_counts.items()))

    def _materialize(self, name: str, factory: Callable[[], _T]) -> _T:
        with self._lock:
            if self._closed:
                raise RuntimeError('repository runtime is closed')
            existing = self._components.get(name)
            if existing is not None:
                return existing  # type: ignore[return-value]
            value = factory()
            self._components[name] = value
            self._build_counts[name] = self._build_counts.get(name, 0) + 1
            return value

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._components.clear()
            self._structured.clear()


class RepositoryRuntimeSession:
    '''Retain at most one validated repository runtime per process session.'''

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.workspace_root = workspace_root
        self.measurement = measurement or MeasurementSession()
        self._lock = RLock()
        self._runtime: RepositoryIntelligenceRuntime | None = None
        self._runtime_build_count = 0
        self._reuse_count = 0

    def runtime_for(
        self,
        snapshot: AtlasSemanticSnapshot,
    ) -> RepositoryIntelligenceRuntime:
        identity = RepositoryRuntimeIdentity.from_snapshot(
            snapshot, workspace_root=self.workspace_root,
        )
        with self._lock:
            if self._runtime is not None and self._runtime.identity == identity:
                self._runtime.require_snapshot(snapshot)
                self._reuse_count += 1
                return self._runtime
            if self._runtime is not None:
                self._runtime.close()
            self._runtime = RepositoryIntelligenceRuntime(
                snapshot,
                identity=identity,
                workspace_root=self.workspace_root,
                measurement=self.measurement,
            )
            self._runtime_build_count += 1
            return self._runtime

    @property
    def statistics(self) -> RepositoryRuntimeStatistics:
        with self._lock:
            runtime = self._runtime
            return RepositoryRuntimeStatistics(
                self._runtime_build_count,
                self._reuse_count,
                runtime.component_build_counts if runtime is not None else (),
                runtime.identity if runtime is not None else None,
            )

    def close(self) -> None:
        with self._lock:
            if self._runtime is not None:
                self._runtime.close()
            self._runtime = None

    def __enter__(self) -> RepositoryRuntimeSession:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def _artifact_lineage(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        return (('state', 'unavailable'),)
    lineage = [
        (name, str(value[name]))
        for name in _LINEAGE_FIELDS
        if name in value
    ]
    if not lineage:
        lineage.append(('state', 'present-without-lineage'))
    if value is not None and 'nodes' in value:
        nodes = value.get('nodes')
        edges = value.get('edges')
        lineage.extend((
            ('node_count', str(len(nodes)) if isinstance(nodes, list) else 'invalid'),
            ('edge_count', str(len(edges)) if isinstance(edges, list) else 'invalid'),
        ))
    return tuple(sorted(lineage))
