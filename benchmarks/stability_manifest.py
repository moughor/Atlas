"""Versioned deterministic manifests for Atlas repository benchmarks.

The manifest records volatile observations such as timestamps and durations without
mixing them into correctness identity. Raw snapshot hashes remain integrity checks;
semantic payload, repository report, project order, and provider-free explanation
hashes are the repeatability gates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median
from urllib.parse import quote, unquote

from moughorai.ai_explain import ExplainEngine
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import Workspace


MANIFEST_FORMAT = "atlas-benchmark-manifest"
MANIFEST_SCHEMA_VERSION = 2
PORTABLE_SNAPSHOT_FORMAT = "atlas-portable-semantic-snapshot"
PORTABLE_SNAPSHOT_VERSION = 1
_SUPPORTED_MANIFEST_SCHEMAS = frozenset({1, MANIFEST_SCHEMA_VERSION})
_PORTABLE_REPOSITORY_ROOT = "REPOSITORY_ROOT"
_PORTABLE_WORKSPACE_FINGERPRINT = "PATH_SCOPED_WORKSPACE_FINGERPRINT"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_BENCHMARK_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
# A UNC root is complete only when both server and share components are present.
# Requiring that shape avoids treating escaped language text such as ``'\\\\'``
# as a machine path while retaining the source-free publication boundary.
_MACHINE_PATH = re.compile(
    r"(?ix)(?:"
    r"file://[^\s,;\)\]\}]+"
    r"|(?<![A-Za-z0-9._-])[A-Z]:[\\/][^\s,;\)\]\}]+"
    r"|(?<![:A-Za-z0-9\\/])(?:\\\\|//)[^\\/\s,;\)\]\}]+[\\/][^\\/\s,;\)\]\}]+"
    r"|(?:^|[\s=:\(\[\{])/(?![/*])[^\s,;\)\]\}]+"
    r")"
)


class BenchmarkMode(str, Enum):
    FRESH_ANALYSIS = "fresh-analysis"
    SNAPSHOT_REPLAY = "snapshot-replay"


class ComparisonStatus(str, Enum):
    MATCH = "match"
    WARNING = "warning"
    PERFORMANCE_CANDIDATE = "performance-candidate"
    REGRESSION = "regression"
    INCOMPARABLE = "incomparable"


class ResultsSource(str, Enum):
    ANALYSIS_REPORT = "analysis-report"
    DECLARED_HISTORICAL = "declared-historical"
    LINKED_FRESH_MANIFEST = "linked-fresh-analysis-manifest"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without materializing it as a second in-memory copy."""

    _positive_integer(chunk_size, "hash chunk size")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_digest(value: object) -> str:
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def canonical_text_digest(value: str) -> str:
    """Hash portable UTF-8 text with LF endings and one final newline."""

    if not isinstance(value, str):
        raise ValueError("canonical text must be a string")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.rstrip("\n") + "\n"
    return sha256_bytes(normalized.encode("utf-8"))


def normalize_observed_at(value: str) -> str:
    """Return one canonical UTC timestamp or reject ambiguous observations."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("benchmark observation timestamp must not be empty")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("benchmark observation timestamp must be ISO-8601 UTC") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("benchmark observation timestamp must use UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def utc_observation_time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True, slots=True)
class SnapshotArtifacts:
    snapshot_size_bytes: int
    snapshot_sha256: str
    snapshot_id: str
    semantic_payload_sha256: str
    repository_report_sha256: str | None
    analysis_report_sha256: str | None
    explain_sha256: str
    project_count: int
    workspace_project_order_sha256: str
    analysis_order_sha256: str | None
    portable_semantic_sha256: str | None = None
    risk_sha256: str | None = None
    knowledge_graph_sha256: str | None = None
    deterministic_ordering_sha256: str | None = None
    analysis_order: tuple[str, ...] = ()
    workspace_projects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_negative_integer(self.snapshot_size_bytes, "snapshot size")
        _non_negative_integer(self.project_count, "snapshot project count")
        for name in (
            "snapshot_sha256",
            "snapshot_id",
            "semantic_payload_sha256",
            "explain_sha256",
            "workspace_project_order_sha256",
        ):
            _hash(getattr(self, name), name)
        if self.repository_report_sha256 is not None:
            _hash(self.repository_report_sha256, "repository report hash")
        if self.analysis_report_sha256 is not None:
            _hash(self.analysis_report_sha256, "analysis report hash")
        if self.analysis_order_sha256 is not None:
            _hash(self.analysis_order_sha256, "analysis order hash")
        for name in (
            "portable_semantic_sha256",
            "risk_sha256",
            "knowledge_graph_sha256",
            "deterministic_ordering_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hash(value, name)
        if (
            not isinstance(self.analysis_order, Sequence)
            or isinstance(self.analysis_order, (str, bytes, bytearray))
            or any(
                not isinstance(item, str) or not item.strip()
                for item in self.analysis_order
            )
        ):
            raise ValueError("benchmark analysis order must contain non-empty strings")
        normalized_order = tuple(self.analysis_order)
        if len(set(normalized_order)) != len(normalized_order):
            raise ValueError("benchmark analysis order must not contain duplicates")
        object.__setattr__(self, "analysis_order", normalized_order)
        if normalized_order:
            if self.analysis_order_sha256 is None:
                raise ValueError("benchmark analysis order requires its hash")
            if canonical_digest(normalized_order) != self.analysis_order_sha256:
                raise ValueError("benchmark analysis order does not match its hash")
        if (
            not isinstance(self.workspace_projects, Sequence)
            or isinstance(self.workspace_projects, (str, bytes, bytearray))
            or any(
                not isinstance(item, str) or not item.strip()
                for item in self.workspace_projects
            )
        ):
            raise ValueError(
                "benchmark workspace projects must contain non-empty strings"
            )
        normalized_projects = tuple(self.workspace_projects)
        if len(set(normalized_projects)) != len(normalized_projects):
            raise ValueError("benchmark workspace projects must not contain duplicates")
        object.__setattr__(self, "workspace_projects", normalized_projects)
        if normalized_projects and canonical_digest(
            normalized_projects
        ) != self.workspace_project_order_sha256:
            raise ValueError(
                "benchmark workspace projects do not match their order hash"
            )


def collect_snapshot_artifacts(
    path: Path,
    *,
    repository_root: Path | None = None,
) -> SnapshotArtifacts:
    """Validate one ASS artifact and compute precisely defined deterministic hashes."""

    target = path.expanduser().resolve()
    before = target.stat()
    store = SemanticSnapshotStore(Workspace(target.parent, ()), target.parent)
    snapshot = store.load(target)
    if snapshot is None:
        raise ValueError(f"semantic snapshot not found: {target}")
    context = dict(snapshot.semantic_context)
    report = context.get("repository_report")
    report_hash = canonical_digest(report) if isinstance(report, Mapping) else None
    explanation = ExplainEngine().explain(snapshot).markdown
    semantic_payload = {
        "schema_version": snapshot.schema_version,
        "workspace_fingerprint": snapshot.workspace_fingerprint,
        "analyzer_version": snapshot.analyzer_version,
        "semantic_context": context,
    }
    projects = _workspace_projects(context)
    raw_hash = sha256_file(target)
    after = target.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("semantic snapshot changed while benchmark evidence was collected")
    portable_payload: Mapping[str, object] | None = None
    risk_hash: str | None = None
    graph_hash: str | None = None
    portable_order_hash: str | None = None
    if repository_root is not None:
        portable_payload = portable_snapshot_payload(snapshot, repository_root)
        portable_context = _mapping(
            portable_payload.get("semantic_context"),
            "portable semantic context",
        )
        portable_report = portable_context.get("repository_report")
        report_hash = (
            canonical_digest(portable_report)
            if isinstance(portable_report, Mapping)
            else None
        )
        risk = portable_context.get("risk_analysis")
        graph = portable_context.get("semantic_graph")
        risk_hash = canonical_digest(risk) if isinstance(risk, Mapping) else None
        graph_hash = canonical_digest(graph) if isinstance(graph, Mapping) else None
        portable_projects = _workspace_projects(portable_context)
        portable_order_hash = canonical_digest(
            {
                "analysis_order": None,
                "workspace_projects": portable_projects,
            }
        )
    return SnapshotArtifacts(
        after.st_size,
        raw_hash,
        snapshot.snapshot_id,
        canonical_digest(semantic_payload),
        report_hash,
        None,
        canonical_text_digest(explanation),
        _project_count(context, projects),
        canonical_digest(projects),
        None,
        (
            canonical_digest(portable_payload)
            if portable_payload is not None
            else None
        ),
        risk_hash,
        graph_hash,
        portable_order_hash,
        (),
        projects,
    )


def portable_snapshot_payload(snapshot: object, repository_root: Path) -> dict[str, object]:
    """Project an ASS into a path-independent, versioned golden payload."""

    root = repository_root.expanduser().resolve()
    context = portable_value(dict(snapshot.semantic_context), root)
    payload = {
        "format": PORTABLE_SNAPSHOT_FORMAT,
        "projection_version": PORTABLE_SNAPSHOT_VERSION,
        "snapshot_schema_version": snapshot.schema_version,
        "workspace_fingerprint": _PORTABLE_WORKSPACE_FINGERPRINT,
        "analyzer_version": snapshot.analyzer_version,
        "semantic_context": context,
    }
    violation = _first_machine_path(payload)
    if violation is not None:
        location, sample = violation
        raise ValueError(
            "portable semantic snapshot still contains an absolute machine path "
            f"at {location}: {sample!r}"
        )
    return payload


def contains_machine_path(value: object) -> bool:
    """Detect literal or percent-encoded machine roots without treating globs as paths."""

    if isinstance(value, Mapping):
        return any(
            contains_machine_path(key) or contains_machine_path(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(contains_machine_path(item) for item in value)
    if not isinstance(value, str):
        return False
    candidate = value
    while True:
        if _MACHINE_PATH.search(candidate) is not None:
            return True
        decoded = unquote(candidate)
        if decoded == candidate:
            return False
        candidate = decoded


def _first_machine_path(
    value: object,
    location: str = "$",
) -> tuple[str, str] | None:
    """Return one deterministic, bounded diagnostic for a machine path."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_location = f"{location}[{json.dumps(str(key), ensure_ascii=False)}]"
            if contains_machine_path(key):
                return f"{key_location}.<key>", _bounded_sample(str(key))
            violation = _first_machine_path(item, key_location)
            if violation is not None:
                return violation
        return None
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for index, item in enumerate(value):
            violation = _first_machine_path(item, f"{location}[{index}]")
            if violation is not None:
                return violation
        return None
    if isinstance(value, str) and contains_machine_path(value):
        return location, _bounded_sample(value)
    return None


def _bounded_sample(value: str, *, limit: int = 160) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def portable_value(value: object, repository_root: Path) -> object:
    """Replace the verified checkout root while preserving semantic structure."""

    root = repository_root.expanduser().resolve()
    forward = root.as_posix().rstrip("/")
    backward = str(root).rstrip("\\/")
    root_uri = root.as_uri().rstrip("/")
    encoded = tuple(
        candidate
        for candidate in {
            quote(forward, safe=""),
            quote(backward, safe=""),
        }
        if candidate
    )

    def project(item: object) -> object:
        if isinstance(item, Mapping):
            result: dict[str, object] = {}
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError("portable semantic mapping keys must be strings")
                projected_key = project(key)
                if not isinstance(projected_key, str):
                    raise RuntimeError("portable semantic key projection is invalid")
                if projected_key in result:
                    raise ValueError(
                        "portable semantic path normalization produced a key collision"
                    )
                result[projected_key] = project(nested)
            return result
        if isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            return [project(nested) for nested in item]
        if not isinstance(item, str):
            return item
        result = item
        path_flags = re.IGNORECASE if root.drive else 0
        for candidate in (
            quote(root_uri, safe=""),
            quote(root_uri, safe=":"),
            root_uri,
        ):
            result = re.sub(
                re.escape(candidate) + r"(?=$|[\\/]|%2[fF]|%5[cC])",
                _PORTABLE_REPOSITORY_ROOT,
                result,
                flags=path_flags,
            )
        for candidate in (forward, backward):
            if candidate:
                result = re.sub(
                    re.escape(candidate) + r"(?=$|[\\/])",
                    _PORTABLE_REPOSITORY_ROOT,
                    result,
                    flags=path_flags,
                )
        for candidate in encoded:
            result = re.sub(
                re.escape(candidate) + r"(?=$|%2[fF]|%5[cC])",
                quote(_PORTABLE_REPOSITORY_ROOT, safe=""),
                result,
                flags=path_flags,
            )
        return result

    return project(value)


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    benchmark_id: str
    mode: BenchmarkMode
    repository_name: str
    repository_commit: str | None
    repository_revision_verified: bool
    checkout_identity: str | None
    atlas_commit: str
    atlas_version: str
    python_version: str
    python_implementation: str
    os_name: str
    os_release: str
    architecture: str
    observed_at_utc: str
    workers: int
    cache_mode: str
    measurement_scope: str
    analysis_duration_ms: tuple[int, ...]
    replay_duration_ms: tuple[int, ...]
    project_count: int
    success_count: int
    failure_count: int
    results_source: ResultsSource
    analysis_success_verified: bool
    source_manifest_sha256: str | None
    artifacts: SnapshotArtifacts
    limitations: tuple[str, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION
    format: str = MANIFEST_FORMAT
    benchmark_version: str = "m1.1"
    repository_url: str | None = None
    repository_branch: str | None = None
    repository_tag: str | None = None
    repository_tracked_size_bytes: int | None = None
    repository_tracked_file_count: int | None = None
    repository_submodules: tuple[tuple[str, str], ...] = ()
    repository_lfs_required: bool | None = None
    repository_history_complete: bool | None = None
    runtime_dependencies: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version not in _SUPPORTED_MANIFEST_SCHEMAS
        ):
            raise ValueError("unsupported benchmark manifest schema")
        if not isinstance(self.mode, BenchmarkMode):
            raise ValueError("benchmark mode must use BenchmarkMode")
        if not isinstance(self.results_source, ResultsSource):
            raise ValueError("benchmark results source must use ResultsSource")
        if self.format != MANIFEST_FORMAT:
            raise ValueError("unsupported benchmark manifest format")
        if self.schema_version == 1:
            object.__setattr__(self, "benchmark_version", "m1")
            object.__setattr__(self, "repository_url", None)
            object.__setattr__(self, "repository_branch", None)
            object.__setattr__(self, "repository_tag", None)
            object.__setattr__(self, "repository_tracked_size_bytes", None)
            object.__setattr__(self, "repository_tracked_file_count", None)
            object.__setattr__(self, "repository_submodules", ())
            object.__setattr__(self, "repository_lfs_required", None)
            object.__setattr__(self, "repository_history_complete", None)
            object.__setattr__(self, "runtime_dependencies", ())
        for name in (
            "benchmark_id",
            "repository_name",
            "atlas_version",
            "python_version",
            "python_implementation",
            "os_name",
            "os_release",
            "architecture",
            "cache_mode",
            "measurement_scope",
        ):
            _non_empty(getattr(self, name), name)
        if _BENCHMARK_ID.fullmatch(self.benchmark_id) is None:
            raise ValueError("benchmark identifier must be a lowercase path-safe slug")
        if any(
            character in self.repository_name
            for character in ("/", "\\", "\r", "\n")
        ):
            raise ValueError("repository name must be a display label, not a path")
        if self.repository_commit is not None:
            _git_object(self.repository_commit, "repository commit")
        if self.repository_revision_verified and self.repository_commit is None:
            raise ValueError("a verified repository revision requires a commit")
        _exact_boolean(
            self.repository_revision_verified,
            "repository revision verified",
        )
        _exact_boolean(
            self.analysis_success_verified,
            "analysis success verified",
        )
        if self.checkout_identity is not None:
            if not isinstance(self.checkout_identity, str) or _BENCHMARK_ID.fullmatch(
                self.checkout_identity
            ) is None:
                raise ValueError(
                    "checkout identity must be a lowercase path-safe slug or null"
                )
        _git_object(self.atlas_commit, "Atlas commit")
        if self.schema_version >= 2:
            _non_empty(self.benchmark_version, "benchmark version")
            if self.repository_url is not None:
                _repository_url(self.repository_url)
            for value, name in (
                (self.repository_branch, "repository branch"),
                (self.repository_tag, "repository tag"),
            ):
                if value is not None:
                    _reference_name(value, name)
            if (self.repository_tracked_size_bytes is None) is not (
                self.repository_tracked_file_count is None
            ):
                raise ValueError(
                    "repository tracked size and file count must both be known or null"
                )
            if self.repository_tracked_size_bytes is not None:
                _non_negative_integer(
                    self.repository_tracked_size_bytes,
                    "repository tracked size",
                )
                _non_negative_integer(
                    self.repository_tracked_file_count,
                    "repository tracked file count",
                )
            if self.repository_lfs_required is not None:
                _exact_boolean(self.repository_lfs_required, "repository LFS required")
            if self.repository_history_complete is not None:
                _exact_boolean(
                    self.repository_history_complete,
                    "repository history complete",
                )
            object.__setattr__(
                self,
                "repository_submodules",
                _named_git_objects(self.repository_submodules, "repository submodules"),
            )
            object.__setattr__(
                self,
                "runtime_dependencies",
                _named_versions(self.runtime_dependencies, "runtime dependencies"),
            )
        object.__setattr__(
            self,
            "observed_at_utc",
            normalize_observed_at(self.observed_at_utc),
        )
        _positive_integer(self.workers, "benchmark workers")
        for name, values in (
            ("analysis durations", self.analysis_duration_ms),
            ("replay durations", self.replay_duration_ms),
        ):
            _durations(values, name)
        if self.mode is BenchmarkMode.FRESH_ANALYSIS:
            if not self.analysis_duration_ms:
                raise ValueError("fresh-analysis manifests require analysis durations")
            if self.replay_duration_ms:
                raise ValueError("fresh-analysis manifests cannot contain replay durations")
            if self.artifacts.analysis_report_sha256 is None:
                raise ValueError("fresh-analysis manifests require an analysis report hash")
            if self.artifacts.analysis_order_sha256 is None:
                raise ValueError("fresh-analysis manifests require an analysis order hash")
            if self.results_source is not ResultsSource.ANALYSIS_REPORT:
                raise ValueError("fresh-analysis results must come from an analysis report")
            if not self.analysis_success_verified:
                raise ValueError("fresh-analysis results must be verified")
            if self.source_manifest_sha256 is not None:
                raise ValueError("fresh-analysis manifests cannot link a source manifest")
            if self.schema_version >= 2 and len(self.artifacts.analysis_order) != self.project_count:
                raise ValueError(
                    "fresh-analysis manifests require the complete analysis order"
                )
            if self.schema_version >= 2 and set(
                self.artifacts.analysis_order
            ) != set(self.artifacts.workspace_projects):
                raise ValueError(
                    "fresh-analysis project inventories are inconsistent"
                )
            if self.schema_version >= 2 and self.artifacts.deterministic_ordering_sha256 != canonical_digest(
                {
                    "analysis_order": self.artifacts.analysis_order,
                    "workspace_project_order_sha256": (
                        self.artifacts.workspace_project_order_sha256
                    ),
                }
            ):
                raise ValueError(
                    "fresh-analysis deterministic ordering hash is inconsistent"
                )
        else:
            if self.analysis_duration_ms:
                raise ValueError("snapshot-replay manifests cannot claim analysis durations")
            if not self.replay_duration_ms:
                raise ValueError("snapshot-replay manifests require replay durations")
            if self.artifacts.analysis_report_sha256 is not None:
                raise ValueError("snapshot-replay manifests cannot claim an analysis report hash")
            if self.artifacts.analysis_order_sha256 is not None:
                raise ValueError("snapshot-replay manifests cannot claim an analysis order hash")
            if self.analysis_success_verified:
                if self.results_source is not ResultsSource.LINKED_FRESH_MANIFEST:
                    raise ValueError("verified replay results require a linked fresh manifest")
                if self.source_manifest_sha256 is None:
                    raise ValueError("verified replay results require a source manifest hash")
            elif self.results_source is not ResultsSource.DECLARED_HISTORICAL:
                raise ValueError("unverified replay results must be declared historical")
            elif self.source_manifest_sha256 is not None:
                raise ValueError("unverified replay results cannot link a source manifest")
            if self.schema_version >= 2 and self.artifacts.analysis_order:
                raise ValueError("snapshot-replay manifests cannot claim an analysis order")
            if self.schema_version >= 2 and self.artifacts.deterministic_ordering_sha256 != canonical_digest(
                {
                    "analysis_order": None,
                    "workspace_projects": self.artifacts.workspace_projects,
                }
            ):
                raise ValueError(
                    "snapshot-replay deterministic ordering hash is inconsistent"
                )
        if self.source_manifest_sha256 is not None:
            _hash(self.source_manifest_sha256, "source manifest hash")
        for name in ("project_count", "success_count", "failure_count"):
            _non_negative_integer(getattr(self, name), name)
        if self.success_count + self.failure_count != self.project_count:
            raise ValueError("benchmark project result counts are inconsistent")
        if self.artifacts.project_count != self.project_count:
            raise ValueError("manifest and snapshot project counts disagree")
        if self.schema_version >= 2 and len(
            self.artifacts.workspace_projects
        ) != self.project_count:
            raise ValueError(
                "schema-2 manifests require the complete workspace project inventory"
            )
        normalized = _strings(self.limitations)
        object.__setattr__(self, "limitations", normalized)
        if self.schema_version >= 2 and contains_absolute_path(self.to_dict()):
            raise ValueError("benchmark manifest must not contain absolute machine paths")

    @property
    def baseline_eligible(self) -> bool:
        base = (
            self.repository_revision_verified
            and self.repository_commit is not None
            and self.checkout_identity is not None
            and len(self.analysis_duration_ms or self.replay_duration_ms) >= 3
            and self.analysis_success_verified
            and self.project_count > 0
            and self.success_count == self.project_count
            and self.artifacts.repository_report_sha256 is not None
        )
        if self.schema_version == 1:
            return base
        return (
            base
            and self.repository_url is not None
            and (self.repository_branch is not None or self.repository_tag is not None)
            and self.repository_tracked_size_bytes is not None
            and self.repository_tracked_file_count is not None
            and self.repository_lfs_required is not None
            and self.repository_history_complete is True
            and bool(self.runtime_dependencies)
            and self.artifacts.portable_semantic_sha256 is not None
            and self.artifacts.risk_sha256 is not None
            and self.artifacts.knowledge_graph_sha256 is not None
            and self.artifacts.deterministic_ordering_sha256 is not None
        )

    @property
    def primary_duration_ms(self) -> int:
        values = (
            self.analysis_duration_ms
            if self.mode is BenchmarkMode.FRESH_ANALYSIS
            else self.replay_duration_ms
        )
        observed = median(values)
        return int(observed + 0.5)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "format": self.format,
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "mode": self.mode.value,
            "repository": {
                "name": self.repository_name,
                "commit": self.repository_commit,
                "revision_verified": self.repository_revision_verified,
                "checkout_identity": self.checkout_identity,
            },
            "atlas": {
                "commit": self.atlas_commit,
                "version": self.atlas_version,
            },
            "environment": {
                "python_version": self.python_version,
                "python_implementation": self.python_implementation,
                "os": self.os_name,
                "os_release": self.os_release,
                "architecture": self.architecture,
            },
            "execution": {
                "observed_at_utc": self.observed_at_utc,
                "workers": self.workers,
                "cache_mode": self.cache_mode,
                "measurement_scope": self.measurement_scope,
                "analysis_duration_ms": list(self.analysis_duration_ms),
                "replay_duration_ms": list(self.replay_duration_ms),
                "repeat_count": len(
                    self.analysis_duration_ms or self.replay_duration_ms
                ),
                "median_duration_ms": self.primary_duration_ms,
            },
            "results": {
                "project_count": self.project_count,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "source": self.results_source.value,
                "analysis_success_verified": self.analysis_success_verified,
                "source_manifest_sha256": self.source_manifest_sha256,
            },
            "artifacts": {
                "snapshot_size_bytes": self.artifacts.snapshot_size_bytes,
                "snapshot_sha256": self.artifacts.snapshot_sha256,
                "snapshot_id": self.artifacts.snapshot_id,
                "semantic_payload_sha256": self.artifacts.semantic_payload_sha256,
                "repository_report_sha256": (
                    self.artifacts.repository_report_sha256
                ),
                "analysis_report_sha256": self.artifacts.analysis_report_sha256,
                "explain_sha256": self.artifacts.explain_sha256,
                "workspace_project_order_sha256": (
                    self.artifacts.workspace_project_order_sha256
                ),
                "analysis_order_sha256": self.artifacts.analysis_order_sha256,
            },
            "baseline_eligible": self.baseline_eligible,
            "limitations": list(self.limitations),
        }
        if self.schema_version >= 2:
            result["benchmark_version"] = self.benchmark_version
            repository = result["repository"]
            assert isinstance(repository, dict)
            repository.update(
                {
                    "url": self.repository_url,
                    "branch": self.repository_branch,
                    "tag": self.repository_tag,
                    "content": {
                        "tracked_size_bytes": self.repository_tracked_size_bytes,
                        "tracked_file_count": self.repository_tracked_file_count,
                        "submodules": [
                            {"path": path, "commit": commit}
                            for path, commit in self.repository_submodules
                        ],
                        "lfs_required": self.repository_lfs_required,
                        "history_complete": self.repository_history_complete,
                    },
                }
            )
            environment = result["environment"]
            assert isinstance(environment, dict)
            environment["runtime_dependencies"] = {
                name: version for name, version in self.runtime_dependencies
            }
            artifacts = result["artifacts"]
            assert isinstance(artifacts, dict)
            artifacts.update(
                {
                    "portable_semantic_sha256": (
                        self.artifacts.portable_semantic_sha256
                    ),
                    "risk_sha256": self.artifacts.risk_sha256,
                    "knowledge_graph_sha256": (
                        self.artifacts.knowledge_graph_sha256
                    ),
                    "deterministic_ordering_sha256": (
                        self.artifacts.deterministic_ordering_sha256
                    ),
                    "analysis_order": list(self.artifacts.analysis_order),
                    "workspace_projects": list(self.artifacts.workspace_projects),
                }
            )
        return result

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True,
            allow_nan=False,
        ) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BenchmarkManifest:
        schema_version = _integer(value.get("schema_version"), "schema version")
        if schema_version not in _SUPPORTED_MANIFEST_SCHEMAS:
            raise ValueError("unsupported benchmark manifest schema")
        top_level_keys = {
            "format",
            "schema_version",
            "benchmark_id",
            "mode",
            "repository",
            "atlas",
            "environment",
            "execution",
            "results",
            "artifacts",
            "baseline_eligible",
            "limitations",
        }
        if schema_version >= 2:
            top_level_keys.add("benchmark_version")
        _exact_keys(
            value,
            top_level_keys,
            "manifest",
        )
        repository = _mapping(value.get("repository"), "repository")
        atlas = _mapping(value.get("atlas"), "atlas")
        environment = _mapping(value.get("environment"), "environment")
        execution = _mapping(value.get("execution"), "execution")
        results = _mapping(value.get("results"), "results")
        artifacts = _mapping(value.get("artifacts"), "artifacts")
        repository_keys = {"name", "commit", "revision_verified", "checkout_identity"}
        environment_keys = {
            "python_version",
            "python_implementation",
            "os",
            "os_release",
            "architecture",
        }
        artifact_keys = {
            "snapshot_size_bytes",
            "snapshot_sha256",
            "snapshot_id",
            "semantic_payload_sha256",
            "repository_report_sha256",
            "analysis_report_sha256",
            "explain_sha256",
            "workspace_project_order_sha256",
            "analysis_order_sha256",
        }
        if schema_version >= 2:
            repository_keys.update({"url", "branch", "tag", "content"})
            environment_keys.add("runtime_dependencies")
            artifact_keys.update(
                {
                    "portable_semantic_sha256",
                    "risk_sha256",
                    "knowledge_graph_sha256",
                    "deterministic_ordering_sha256",
                    "analysis_order",
                    "workspace_projects",
                }
            )
        _exact_keys(repository, repository_keys, "repository")
        _exact_keys(atlas, {"commit", "version"}, "Atlas identity")
        _exact_keys(environment, environment_keys, "environment")
        _exact_keys(
            execution,
            {
                "observed_at_utc",
                "workers",
                "cache_mode",
                "measurement_scope",
                "analysis_duration_ms",
                "replay_duration_ms",
                "repeat_count",
                "median_duration_ms",
            },
            "execution",
        )
        _exact_keys(
            results,
            {
                "project_count",
                "success_count",
                "failure_count",
                "source",
                "analysis_success_verified",
                "source_manifest_sha256",
            },
            "results",
        )
        _exact_keys(artifacts, artifact_keys, "artifacts")
        content: Mapping[str, object] = {}
        if schema_version >= 2:
            content = _mapping(repository.get("content"), "repository content")
            _exact_keys(
                content,
                {
                    "tracked_size_bytes",
                    "tracked_file_count",
                    "submodules",
                    "lfs_required",
                    "history_complete",
                },
                "repository content",
            )
        repository_commit = repository.get("commit")
        checkout_identity = repository.get("checkout_identity")
        report_hash = artifacts.get("repository_report_sha256")
        analysis_hash = artifacts.get("analysis_report_sha256")
        analysis_order_hash = artifacts.get("analysis_order_sha256")
        source_manifest_hash = results.get("source_manifest_sha256")
        result = cls(
            benchmark_id=_string(value.get("benchmark_id"), "benchmark identifier"),
            mode=BenchmarkMode(_string(value.get("mode"), "benchmark mode")),
            repository_name=_string(repository.get("name"), "repository name"),
            repository_commit=_optional_string(repository_commit, "repository commit"),
            repository_revision_verified=_boolean(
                repository.get("revision_verified"), "revision verified"
            ),
            checkout_identity=_optional_string(checkout_identity, "checkout identity"),
            atlas_commit=_string(atlas.get("commit"), "Atlas commit"),
            atlas_version=_string(atlas.get("version"), "Atlas version"),
            python_version=_string(environment.get("python_version"), "Python version"),
            python_implementation=_string(
                environment.get("python_implementation"), "Python implementation"
            ),
            os_name=_string(environment.get("os"), "operating system"),
            os_release=_string(environment.get("os_release"), "operating system release"),
            architecture=_string(environment.get("architecture"), "architecture"),
            observed_at_utc=_string(
                execution.get("observed_at_utc"), "observation timestamp"
            ),
            workers=_integer(execution.get("workers"), "workers"),
            cache_mode=_string(execution.get("cache_mode"), "cache mode"),
            measurement_scope=_string(
                execution.get("measurement_scope"), "measurement scope"
            ),
            analysis_duration_ms=_integer_tuple(
                execution.get("analysis_duration_ms"), "analysis durations"
            ),
            replay_duration_ms=_integer_tuple(
                execution.get("replay_duration_ms"), "replay durations"
            ),
            project_count=_integer(results.get("project_count"), "project count"),
            success_count=_integer(results.get("success_count"), "success count"),
            failure_count=_integer(results.get("failure_count"), "failure count"),
            results_source=ResultsSource(
                _string(results.get("source"), "results source")
            ),
            analysis_success_verified=_boolean(
                results.get("analysis_success_verified"),
                "analysis success verified",
            ),
            source_manifest_sha256=_optional_string(
                source_manifest_hash, "source manifest hash"
            ),
            artifacts=SnapshotArtifacts(
                snapshot_size_bytes=_integer(
                    artifacts.get("snapshot_size_bytes"), "snapshot size"
                ),
                snapshot_sha256=_string(
                    artifacts.get("snapshot_sha256"), "snapshot hash"
                ),
                snapshot_id=_string(
                    artifacts.get("snapshot_id"), "snapshot identifier"
                ),
                semantic_payload_sha256=_string(
                    artifacts.get("semantic_payload_sha256"),
                    "semantic payload hash",
                ),
                repository_report_sha256=_optional_string(
                    report_hash, "repository report hash"
                ),
                analysis_report_sha256=_optional_string(
                    analysis_hash, "analysis report hash"
                ),
                explain_sha256=_string(
                    artifacts.get("explain_sha256"), "explain hash"
                ),
                project_count=_integer(
                    results.get("project_count"), "project count"
                ),
                workspace_project_order_sha256=_string(
                    artifacts.get("workspace_project_order_sha256"),
                    "workspace project order hash",
                ),
                analysis_order_sha256=_optional_string(
                    analysis_order_hash, "analysis order hash"
                ),
                portable_semantic_sha256=(
                    _optional_string(
                        artifacts.get("portable_semantic_sha256"),
                        "portable semantic hash",
                    )
                    if schema_version >= 2
                    else None
                ),
                risk_sha256=(
                    _optional_string(artifacts.get("risk_sha256"), "risk hash")
                    if schema_version >= 2
                    else None
                ),
                knowledge_graph_sha256=(
                    _optional_string(
                        artifacts.get("knowledge_graph_sha256"),
                        "knowledge graph hash",
                    )
                    if schema_version >= 2
                    else None
                ),
                deterministic_ordering_sha256=(
                    _optional_string(
                        artifacts.get("deterministic_ordering_sha256"),
                        "deterministic ordering hash",
                    )
                    if schema_version >= 2
                    else None
                ),
                analysis_order=(
                    _ordered_strings(
                        artifacts.get("analysis_order"),
                        "analysis order",
                    )
                    if schema_version >= 2
                    else ()
                ),
                workspace_projects=(
                    _ordered_strings(
                        artifacts.get("workspace_projects"),
                        "workspace projects",
                    )
                    if schema_version >= 2
                    else ()
                ),
            ),
            limitations=_strings(value.get("limitations")),
            benchmark_version=(
                _string(value.get("benchmark_version"), "benchmark version")
                if schema_version >= 2
                else "m1"
            ),
            repository_url=(
                _optional_string(repository.get("url"), "repository URL")
                if schema_version >= 2
                else None
            ),
            repository_branch=(
                _optional_string(repository.get("branch"), "repository branch")
                if schema_version >= 2
                else None
            ),
            repository_tag=(
                _optional_string(repository.get("tag"), "repository tag")
                if schema_version >= 2
                else None
            ),
            repository_tracked_size_bytes=(
                _optional_integer(
                    content.get("tracked_size_bytes"), "repository tracked size"
                )
                if schema_version >= 2
                else None
            ),
            repository_tracked_file_count=(
                _optional_integer(
                    content.get("tracked_file_count"),
                    "repository tracked file count",
                )
                if schema_version >= 2
                else None
            ),
            repository_submodules=(
                _submodule_tuple(content.get("submodules"))
                if schema_version >= 2
                else ()
            ),
            repository_lfs_required=(
                _optional_boolean(content.get("lfs_required"), "repository LFS required")
                if schema_version >= 2
                else None
            ),
            repository_history_complete=(
                _optional_boolean(
                    content.get("history_complete"),
                    "repository history complete",
                )
                if schema_version >= 2
                else None
            ),
            runtime_dependencies=(
                _version_tuple(environment.get("runtime_dependencies"))
                if schema_version >= 2
                else ()
            ),
            schema_version=schema_version,
            format=_string(value.get("format"), "manifest format"),
        )
        if _boolean(
            value.get("baseline_eligible"), "baseline eligibility"
        ) is not result.baseline_eligible:
            raise ValueError("benchmark baseline eligibility is inconsistent")
        if _integer(
            execution.get("median_duration_ms"), "median duration"
        ) != result.primary_duration_ms:
            raise ValueError("benchmark median duration is inconsistent")
        if _integer(execution.get("repeat_count"), "repeat count") != len(
            result.analysis_duration_ms or result.replay_duration_ms
        ):
            raise ValueError("benchmark repeat count is inconsistent")
        return result

    @classmethod
    def from_json(cls, value: str) -> BenchmarkManifest:
        try:
            decoded = json.loads(value, parse_constant=_reject_json_constant)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid benchmark manifest JSON: {exc}") from exc
        if not isinstance(decoded, Mapping):
            raise ValueError("benchmark manifest must be an object")
        return cls.from_dict(decoded)

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        require_canonical: bool = True,
    ) -> BenchmarkManifest:
        """Load UTF-8 JSON and optionally require exact canonical file bytes."""

        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("benchmark manifest must be UTF-8") from exc
        result = cls.from_json(text)
        if require_canonical and raw != result.to_json().encode("utf-8"):
            raise ValueError(
                "benchmark manifest file is not canonical UTF-8 JSON with LF endings"
            )
        return result


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    status: ComparisonStatus
    issues: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    duration_change_percent: float | None = None
    baseline_duration_ms: int | None = None
    current_duration_ms: int | None = None
    absolute_change_ms: int | None = None
    baseline_samples_ms: tuple[int, ...] = ()
    current_samples_ms: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", _strings(self.issues))
        object.__setattr__(self, "warnings", _strings(self.warnings))
        for value, name in (
            (self.baseline_duration_ms, "baseline duration"),
            (self.current_duration_ms, "current duration"),
        ):
            if value is not None:
                _positive_integer(value, name)
        if self.absolute_change_ms is not None and (
            isinstance(self.absolute_change_ms, bool)
            or not isinstance(self.absolute_change_ms, int)
        ):
            raise ValueError("absolute duration change must be an integer")
        _durations(self.baseline_samples_ms, "baseline samples")
        _durations(self.current_samples_ms, "current samples")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
            "performance": {
                "baseline_median_ms": self.baseline_duration_ms,
                "current_median_ms": self.current_duration_ms,
                "absolute_change_ms": self.absolute_change_ms,
                "duration_change_percent": self.duration_change_percent,
                "baseline_samples_ms": list(self.baseline_samples_ms),
                "current_samples_ms": list(self.current_samples_ms),
            },
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True,
            allow_nan=False,
        ) + "\n"


def compare_manifests(
    baseline: BenchmarkManifest,
    current: BenchmarkManifest,
    *,
    warning_percent: float = 15.0,
    warning_absolute_ms: int = 500,
    candidate_percent: float = 30.0,
    candidate_absolute_ms: int = 1_000,
) -> BenchmarkComparison:
    """Compare compatible records; correctness drift is stricter than timing drift."""

    for value, name in (
        (warning_percent, "performance warning percent"),
        (candidate_percent, "performance candidate percent"),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{name} must be non-negative")
    _non_negative_integer(warning_absolute_ms, "performance warning milliseconds")
    _non_negative_integer(candidate_absolute_ms, "performance candidate milliseconds")
    if candidate_percent < warning_percent:
        raise ValueError("performance candidate percent must not be below warning percent")
    if candidate_absolute_ms < warning_absolute_ms:
        raise ValueError(
            "performance candidate milliseconds must not be below warning milliseconds"
        )
    baseline_samples = (
        baseline.analysis_duration_ms or baseline.replay_duration_ms
    )
    current_samples = current.analysis_duration_ms or current.replay_duration_ms
    base_duration = baseline.primary_duration_ms
    current_duration = current.primary_duration_ms
    delta = current_duration - base_duration
    duration_change = (
        (current_duration - base_duration) * 100.0 / base_duration
        if base_duration else None
    )
    eligibility_issues = tuple(
        message
        for eligible, message in (
            (
                baseline.baseline_eligible,
                "baseline record is not eligible for regression comparison",
            ),
            (
                current.baseline_eligible,
                "current record is not eligible for regression comparison",
            ),
        )
        if not eligible
    )
    if eligibility_issues:
        return BenchmarkComparison(
            status=ComparisonStatus.INCOMPARABLE,
            issues=eligibility_issues,
            duration_change_percent=(
                round(duration_change, 6) if duration_change is not None else None
            ),
            baseline_duration_ms=base_duration,
            current_duration_ms=current_duration,
            absolute_change_ms=delta,
            baseline_samples_ms=baseline_samples,
            current_samples_ms=current_samples,
        )
    comparable = (
        ("manifest schema", baseline.schema_version, current.schema_version),
        ("benchmark version", baseline.benchmark_version, current.benchmark_version),
        ("benchmark", baseline.benchmark_id, current.benchmark_id),
        ("mode", baseline.mode.value, current.mode.value),
        ("repository", baseline.repository_name, current.repository_name),
        ("repository URL", baseline.repository_url, current.repository_url),
        ("repository commit", baseline.repository_commit, current.repository_commit),
        ("repository branch", baseline.repository_branch, current.repository_branch),
        ("repository tag", baseline.repository_tag, current.repository_tag),
        (
            "repository tracked size",
            baseline.repository_tracked_size_bytes,
            current.repository_tracked_size_bytes,
        ),
        (
            "repository tracked file count",
            baseline.repository_tracked_file_count,
            current.repository_tracked_file_count,
        ),
        (
            "repository submodules",
            baseline.repository_submodules,
            current.repository_submodules,
        ),
        (
            "repository LFS requirement",
            baseline.repository_lfs_required,
            current.repository_lfs_required,
        ),
        (
            "repository history completeness",
            baseline.repository_history_complete,
            current.repository_history_complete,
        ),
        ("workers", baseline.workers, current.workers),
        ("cache mode", baseline.cache_mode, current.cache_mode),
        ("measurement scope", baseline.measurement_scope, current.measurement_scope),
        ("checkout identity", baseline.checkout_identity, current.checkout_identity),
        ("repeat count", len(baseline.analysis_duration_ms or baseline.replay_duration_ms), len(current.analysis_duration_ms or current.replay_duration_ms)),
        ("Python major/minor", _python_minor(baseline.python_version), _python_minor(current.python_version)),
        ("Python implementation", baseline.python_implementation, current.python_implementation),
        ("operating system", baseline.os_name, current.os_name),
        ("operating system release", baseline.os_release, current.os_release),
        ("architecture", baseline.architecture, current.architecture),
        (
            "runtime dependencies",
            baseline.runtime_dependencies,
            current.runtime_dependencies,
        ),
        *(
            (
                (
                    "replay snapshot hash",
                    baseline.artifacts.snapshot_sha256,
                    current.artifacts.snapshot_sha256,
                ),
                (
                    "replay snapshot identifier",
                    baseline.artifacts.snapshot_id,
                    current.artifacts.snapshot_id,
                ),
                (
                    "replay snapshot size",
                    baseline.artifacts.snapshot_size_bytes,
                    current.artifacts.snapshot_size_bytes,
                ),
                (
                    "replay source manifest",
                    baseline.source_manifest_sha256,
                    current.source_manifest_sha256,
                ),
            )
            if baseline.mode is BenchmarkMode.SNAPSHOT_REPLAY
            else ()
        ),
    )
    incomparable = tuple(
        f"{name} differs: {left!r} != {right!r}"
        for name, left, right in comparable
        if left != right
    )
    if incomparable:
        return BenchmarkComparison(
            status=ComparisonStatus.INCOMPARABLE,
            issues=incomparable,
            duration_change_percent=(
                round(duration_change, 6) if duration_change is not None else None
            ),
            baseline_duration_ms=base_duration,
            current_duration_ms=current_duration,
            absolute_change_ms=delta,
            baseline_samples_ms=baseline_samples,
            current_samples_ms=current_samples,
        )
    issues: list[str] = []
    warnings: list[str] = []
    correctness_dimensions: tuple[tuple[str, object, object], ...] = (
        ("project count", baseline.project_count, current.project_count),
        ("success count", baseline.success_count, current.success_count),
        ("failure count", baseline.failure_count, current.failure_count),
        ("repository report hash", baseline.artifacts.repository_report_sha256, current.artifacts.repository_report_sha256),
        ("analysis report hash", baseline.artifacts.analysis_report_sha256, current.artifacts.analysis_report_sha256),
        ("explain hash", baseline.artifacts.explain_sha256, current.artifacts.explain_sha256),
        ("workspace project order hash", baseline.artifacts.workspace_project_order_sha256, current.artifacts.workspace_project_order_sha256),
        ("analysis order hash", baseline.artifacts.analysis_order_sha256, current.artifacts.analysis_order_sha256),
    )
    if baseline.schema_version == 1:
        correctness_dimensions += ((
            "semantic payload hash",
            baseline.artifacts.semantic_payload_sha256,
            current.artifacts.semantic_payload_sha256,
        ),)
        stable_semantics = (
            baseline.artifacts.semantic_payload_sha256
            == current.artifacts.semantic_payload_sha256
        )
    else:
        correctness_dimensions += (
            ("portable semantic hash", baseline.artifacts.portable_semantic_sha256, current.artifacts.portable_semantic_sha256),
            ("risk hash", baseline.artifacts.risk_sha256, current.artifacts.risk_sha256),
            ("knowledge graph hash", baseline.artifacts.knowledge_graph_sha256, current.artifacts.knowledge_graph_sha256),
            ("deterministic ordering hash", baseline.artifacts.deterministic_ordering_sha256, current.artifacts.deterministic_ordering_sha256),
        )
        stable_semantics = (
            baseline.artifacts.portable_semantic_sha256
            == current.artifacts.portable_semantic_sha256
        )
        if (
            baseline.artifacts.semantic_payload_sha256
            != current.artifacts.semantic_payload_sha256
            and stable_semantics
        ):
            warnings.append(
                "path-scoped semantic payload hash changed while portable semantics "
                "stayed stable"
            )
    for name, left, right in correctness_dimensions:
        if left != right:
            issues.append(f"{name} changed: {left!r} -> {right!r}")
    if (
        baseline.artifacts.snapshot_sha256 != current.artifacts.snapshot_sha256
        and stable_semantics
    ):
        warnings.append(
            "raw snapshot hash changed while the semantic payload stayed stable; "
            "inspect operational history metadata"
        )
    if baseline.artifacts.snapshot_size_bytes != current.artifacts.snapshot_size_bytes:
        warnings.append(
            "snapshot size changed: "
            f"{baseline.artifacts.snapshot_size_bytes} -> "
            f"{current.artifacts.snapshot_size_bytes} bytes"
        )
    performance_candidate = False
    if duration_change is not None:
        if duration_change > candidate_percent and delta >= candidate_absolute_ms:
            performance_candidate = True
            warnings.append(
                "performance regression candidate exceeds the documented advisory "
                "threshold; confirm it in an independent batch"
            )
        elif duration_change > warning_percent and delta >= warning_absolute_ms:
            warnings.append("performance warning threshold exceeded")
    status = (
        ComparisonStatus.REGRESSION
        if issues
        else ComparisonStatus.PERFORMANCE_CANDIDATE
        if performance_candidate
        else ComparisonStatus.WARNING
        if warnings
        else ComparisonStatus.MATCH
    )
    return BenchmarkComparison(
        status=status,
        issues=tuple(issues),
        warnings=tuple(warnings),
        duration_change_percent=(
            round(duration_change, 6) if duration_change is not None else None
        ),
        baseline_duration_ms=base_duration,
        current_duration_ms=current_duration,
        absolute_change_ms=delta,
        baseline_samples_ms=baseline_samples,
        current_samples_ms=current_samples,
    )


def _workspace_projects(context: Mapping[str, object]) -> tuple[str, ...]:
    workspace = context.get("workspace")
    if not isinstance(workspace, Mapping):
        raise ValueError("snapshot workspace must be an object")
    projects = workspace.get("projects")
    if not isinstance(projects, Sequence) or isinstance(projects, (str, bytes)):
        raise ValueError("snapshot workspace projects must be an array")
    result = []
    for item in projects:
        if not isinstance(item, Mapping):
            raise ValueError("snapshot project entry must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("snapshot project name must be a non-empty string")
        result.append(name.strip())
    if len(set(result)) != len(result):
        raise ValueError("snapshot project names must be unique")
    return tuple(result)


def _project_count(
    context: Mapping[str, object], projects: tuple[str, ...]
) -> int:
    summary = context.get("repository_summary")
    value = summary.get("project_count") if isinstance(summary, Mapping) else None
    if isinstance(summary, Mapping) and "project_count" in summary:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("snapshot repository project count must be a non-negative integer")
        if value != len(projects):
            raise ValueError("snapshot project counts are inconsistent")
        return value
    return len(projects)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"benchmark {name} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    name: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(repr(item) for item in actual - expected)
        raise ValueError(
            f"benchmark {name} fields are invalid; missing={missing}, unknown={unknown}"
        )


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"benchmark {name} must be a boolean")
    return value


def _exact_boolean(value: object, name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"benchmark {name} must be a boolean")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"benchmark {name} must be a non-empty string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _optional_boolean(value: object, name: str) -> bool | None:
    return None if value is None else _boolean(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"benchmark {name} must be an integer")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _integer_tuple(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"benchmark {name} must be an array")
    return tuple(_integer(item, name) for item in value)


def _non_empty(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"benchmark {name} must not be empty")


def _positive_integer(value: object, name: str) -> None:
    _non_negative_integer(value, name)
    if value == 0:
        raise ValueError(f"{name} must be positive")


def _non_negative_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _durations(value: tuple[int, ...], name: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"benchmark {name} must use an immutable tuple")
    for item in value:
        _positive_integer(item, name)


def _hash(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"benchmark {name} must be a lowercase SHA-256 digest")


def _git_object(value: str, name: str) -> None:
    if not isinstance(value, str) or _GIT_OBJECT_ID.fullmatch(value) is None:
        raise ValueError(f"benchmark {name} must be a full lowercase Git object ID")


def _repository_url(value: str) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"https://[^/@\s]+/[^\s]+", value) is None
        or "@" in value.split("/", 3)[2]
    ):
        raise ValueError("benchmark repository URL must be a credential-free HTTPS URL")


def _reference_name(value: str, name: str) -> None:
    _non_empty(value, name)
    if (
        value != value.strip()
        or value.startswith("-")
        or value.endswith((".", "/"))
        or ".." in value
        or "@{" in value
        or re.search(r"[\x00-\x20~^:?*\\\[]", value)
    ):
        raise ValueError(f"benchmark {name} is not a safe Git reference name")


def _named_git_objects(value: object, name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"benchmark {name} must be an immutable sequence")
    result: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes, bytearray))
            or len(item) != 2
        ):
            raise ValueError(f"benchmark {name} entries must be path/commit pairs")
        path, commit = item
        _non_empty(path, "submodule path")
        if contains_absolute_path(path) or "\\" in path or ".." in Path(path).parts:
            raise ValueError("benchmark submodule path must be repository-relative")
        _git_object(commit, "submodule commit")
        result.append((path, commit))
    if len({path for path, _ in result}) != len(result):
        raise ValueError("benchmark submodule paths must be unique")
    return tuple(sorted(result))


def _named_versions(value: object, name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"benchmark {name} must be an immutable sequence")
    result: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes, bytearray))
            or len(item) != 2
        ):
            raise ValueError(f"benchmark {name} entries must be name/version pairs")
        dependency, version = item
        _non_empty(dependency, "runtime dependency name")
        _non_empty(version, "runtime dependency version")
        result.append((dependency.casefold(), version))
    if len({dependency for dependency, _ in result}) != len(result):
        raise ValueError("benchmark runtime dependency names must be unique")
    return tuple(sorted(result))


def _submodule_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("benchmark repository submodules must be an array")
    result: list[tuple[str, str]] = []
    for item in value:
        mapping = _mapping(item, "repository submodule")
        _exact_keys(mapping, {"path", "commit"}, "repository submodule")
        result.append(
            (
                _string(mapping.get("path"), "submodule path"),
                _string(mapping.get("commit"), "submodule commit"),
            )
        )
    return tuple(result)


def _version_tuple(value: object) -> tuple[tuple[str, str], ...]:
    mapping = _mapping(value, "runtime dependencies")
    if any(not isinstance(name, str) for name in mapping):
        raise ValueError("benchmark runtime dependency names must be strings")
    return tuple(
        (_string(name, "runtime dependency name"), _string(version, "runtime dependency version"))
        for name, version in sorted(mapping.items())
    )


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("benchmark limitations must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("benchmark limitations must contain non-empty strings")
    return tuple(sorted(set(item.strip() for item in value)))


def _ordered_strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise ValueError(f"benchmark {name} must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"benchmark {name} must contain non-empty strings")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise ValueError(f"benchmark {name} must not contain duplicates")
    return result


def _python_minor(value: str) -> tuple[int, int] | str:
    match = re.match(r"(\d+)\.(\d+)", value)
    return (int(match.group(1)), int(match.group(2))) if match else value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid non-finite JSON number: {value}")


__all__ = [
    "BenchmarkComparison",
    "BenchmarkManifest",
    "BenchmarkMode",
    "ComparisonStatus",
    "MANIFEST_FORMAT",
    "MANIFEST_SCHEMA_VERSION",
    "PORTABLE_SNAPSHOT_FORMAT",
    "PORTABLE_SNAPSHOT_VERSION",
    "ResultsSource",
    "SnapshotArtifacts",
    "canonical_digest",
    "canonical_text_digest",
    "collect_snapshot_artifacts",
    "compare_manifests",
    "contains_machine_path",
    "normalize_observed_at",
    "portable_snapshot_payload",
    "portable_value",
    "sha256_bytes",
    "sha256_file",
    "utc_observation_time",
]
