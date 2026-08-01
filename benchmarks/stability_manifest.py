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
from typing import Any

from moughorai.ai_explain import ExplainEngine
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.semantic_snapshot.models import canonical_json
from moughorai.workspace import Workspace


MANIFEST_FORMAT = "atlas-benchmark-manifest"
MANIFEST_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_BENCHMARK_ID = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")


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


def collect_snapshot_artifacts(path: Path) -> SnapshotArtifacts:
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
    )


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

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("unsupported benchmark manifest schema")
        if not isinstance(self.mode, BenchmarkMode):
            raise ValueError("benchmark mode must use BenchmarkMode")
        if not isinstance(self.results_source, ResultsSource):
            raise ValueError("benchmark results source must use ResultsSource")
        if self.format != MANIFEST_FORMAT:
            raise ValueError("unsupported benchmark manifest format")
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
        if self.source_manifest_sha256 is not None:
            _hash(self.source_manifest_sha256, "source manifest hash")
        for name in ("project_count", "success_count", "failure_count"):
            _non_negative_integer(getattr(self, name), name)
        if self.success_count + self.failure_count != self.project_count:
            raise ValueError("benchmark project result counts are inconsistent")
        if self.artifacts.project_count != self.project_count:
            raise ValueError("manifest and snapshot project counts disagree")
        normalized = _strings(self.limitations)
        object.__setattr__(self, "limitations", normalized)

    @property
    def baseline_eligible(self) -> bool:
        return (
            self.repository_revision_verified
            and self.repository_commit is not None
            and self.checkout_identity is not None
            and len(self.analysis_duration_ms or self.replay_duration_ms) >= 3
            and self.analysis_success_verified
            and self.project_count > 0
            and self.success_count == self.project_count
            and self.artifacts.repository_report_sha256 is not None
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
        return {
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

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True,
            allow_nan=False,
        ) + "\n"

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BenchmarkManifest:
        _exact_keys(
            value,
            {
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
            },
            "manifest",
        )
        repository = _mapping(value.get("repository"), "repository")
        atlas = _mapping(value.get("atlas"), "atlas")
        environment = _mapping(value.get("environment"), "environment")
        execution = _mapping(value.get("execution"), "execution")
        results = _mapping(value.get("results"), "results")
        artifacts = _mapping(value.get("artifacts"), "artifacts")
        _exact_keys(
            repository,
            {"name", "commit", "revision_verified", "checkout_identity"},
            "repository",
        )
        _exact_keys(atlas, {"commit", "version"}, "Atlas identity")
        _exact_keys(
            environment,
            {
                "python_version",
                "python_implementation",
                "os",
                "os_release",
                "architecture",
            },
            "environment",
        )
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
        _exact_keys(
            artifacts,
            {
                "snapshot_size_bytes",
                "snapshot_sha256",
                "snapshot_id",
                "semantic_payload_sha256",
                "repository_report_sha256",
                "analysis_report_sha256",
                "explain_sha256",
                "workspace_project_order_sha256",
                "analysis_order_sha256",
            },
            "artifacts",
        )
        repository_commit = repository.get("commit")
        checkout_identity = repository.get("checkout_identity")
        report_hash = artifacts.get("repository_report_sha256")
        analysis_hash = artifacts.get("analysis_report_sha256")
        analysis_order_hash = artifacts.get("analysis_order_sha256")
        source_manifest_hash = results.get("source_manifest_sha256")
        result = cls(
            _string(value.get("benchmark_id"), "benchmark identifier"),
            BenchmarkMode(_string(value.get("mode"), "benchmark mode")),
            _string(repository.get("name"), "repository name"),
            _optional_string(repository_commit, "repository commit"),
            _boolean(repository.get("revision_verified"), "revision verified"),
            _optional_string(checkout_identity, "checkout identity"),
            _string(atlas.get("commit"), "Atlas commit"),
            _string(atlas.get("version"), "Atlas version"),
            _string(environment.get("python_version"), "Python version"),
            _string(environment.get("python_implementation"), "Python implementation"),
            _string(environment.get("os"), "operating system"),
            _string(environment.get("os_release"), "operating system release"),
            _string(environment.get("architecture"), "architecture"),
            _string(execution.get("observed_at_utc"), "observation timestamp"),
            _integer(execution.get("workers"), "workers"),
            _string(execution.get("cache_mode"), "cache mode"),
            _string(execution.get("measurement_scope"), "measurement scope"),
            _integer_tuple(
                execution.get("analysis_duration_ms"), "analysis durations"
            ),
            _integer_tuple(
                execution.get("replay_duration_ms"), "replay durations"
            ),
            _integer(results.get("project_count"), "project count"),
            _integer(results.get("success_count"), "success count"),
            _integer(results.get("failure_count"), "failure count"),
            ResultsSource(_string(results.get("source"), "results source")),
            _boolean(
                results.get("analysis_success_verified"),
                "analysis success verified",
            ),
            _optional_string(source_manifest_hash, "source manifest hash"),
            SnapshotArtifacts(
                _integer(artifacts.get("snapshot_size_bytes"), "snapshot size"),
                _string(artifacts.get("snapshot_sha256"), "snapshot hash"),
                _string(artifacts.get("snapshot_id"), "snapshot identifier"),
                _string(artifacts.get("semantic_payload_sha256"), "semantic payload hash"),
                _optional_string(report_hash, "repository report hash"),
                _optional_string(analysis_hash, "analysis report hash"),
                _string(artifacts.get("explain_sha256"), "explain hash"),
                _integer(results.get("project_count"), "project count"),
                _string(
                    artifacts.get("workspace_project_order_sha256"),
                    "workspace project order hash",
                ),
                _optional_string(analysis_order_hash, "analysis order hash"),
            ),
            _strings(value.get("limitations")),
            _integer(value.get("schema_version"), "schema version"),
            _string(value.get("format"), "manifest format"),
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
        ("benchmark", baseline.benchmark_id, current.benchmark_id),
        ("mode", baseline.mode.value, current.mode.value),
        ("repository", baseline.repository_name, current.repository_name),
        ("repository commit", baseline.repository_commit, current.repository_commit),
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
    for name, left, right in (
        ("project count", baseline.project_count, current.project_count),
        ("success count", baseline.success_count, current.success_count),
        ("failure count", baseline.failure_count, current.failure_count),
        ("semantic payload hash", baseline.artifacts.semantic_payload_sha256, current.artifacts.semantic_payload_sha256),
        ("repository report hash", baseline.artifacts.repository_report_sha256, current.artifacts.repository_report_sha256),
        ("analysis report hash", baseline.artifacts.analysis_report_sha256, current.artifacts.analysis_report_sha256),
        ("explain hash", baseline.artifacts.explain_sha256, current.artifacts.explain_sha256),
        ("workspace project order hash", baseline.artifacts.workspace_project_order_sha256, current.artifacts.workspace_project_order_sha256),
        ("analysis order hash", baseline.artifacts.analysis_order_sha256, current.artifacts.analysis_order_sha256),
    ):
        if left != right:
            issues.append(f"{name} changed: {left!r} -> {right!r}")
    if (
        baseline.artifacts.snapshot_sha256 != current.artifacts.snapshot_sha256
        and baseline.artifacts.semantic_payload_sha256
        == current.artifacts.semantic_payload_sha256
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


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"benchmark {name} must be an integer")
    return value


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


def _strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("benchmark limitations must be an array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("benchmark limitations must contain non-empty strings")
    return tuple(sorted(set(item.strip() for item in value)))


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
    "ResultsSource",
    "SnapshotArtifacts",
    "canonical_digest",
    "canonical_text_digest",
    "collect_snapshot_artifacts",
    "compare_manifests",
    "normalize_observed_at",
    "sha256_bytes",
    "sha256_file",
    "utc_observation_time",
]
