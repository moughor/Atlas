"""Prepare, verify, capture, and replay canonical M1.1 repository baselines.

This module is orchestration around :mod:`benchmarks.repository_benchmark`; it does
not implement another analyzer or benchmark engine. Repository definitions are
tracked, while checkouts and generated golden bundles stay external or ignored.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

from moughorai.ai_explain import ExplainEngine
from moughorai.repository_report.safety import contains_absolute_path
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import Workspace

from . import repository_benchmark
from .stability_manifest import (
    BenchmarkManifest,
    PORTABLE_SNAPSHOT_FORMAT,
    PORTABLE_SNAPSHOT_VERSION,
    canonical_digest,
    canonical_text_digest,
    collect_snapshot_artifacts,
    contains_machine_path,
    portable_snapshot_payload,
)


DEFINITIONS_FORMAT = "atlas-benchmark-repositories"
DEFINITIONS_SCHEMA_VERSION = 1
GOLDEN_BUNDLE_FORMAT = "atlas-benchmark-golden-bundle"
GOLDEN_BUNDLE_SCHEMA_VERSION = 1
DEFAULT_DEFINITIONS = Path(__file__).with_name("repositories.json")
_GIT_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_GOLDEN_PAYLOAD_FILES = frozenset(
    {
        "ai-explain.md",
        "benchmark-metadata.json",
        "deterministic-ordering.json",
        "knowledge-graph-summary.json",
        "repository-report.json",
        "risk-summary.json",
        "semantic-snapshot.json",
    }
)
_GOLDEN_FILES = _GOLDEN_PAYLOAD_FILES | {"checksums.json"}
_GOLDEN_JSON_FILES = _GOLDEN_FILES - {"ai-explain.md"}


@dataclass(frozen=True, slots=True)
class BenchmarkRepositoryDefinition:
    repository_id: str
    name: str
    url: str
    commit: str
    branch: str
    tag: str | None
    checkout_identity: str
    expected_project_count: int
    workers: int
    timeout_seconds: int
    tracked_size_bytes: int
    tracked_file_count: int
    submodules: tuple[tuple[str, str], ...]
    lfs_required: bool
    history_complete: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.repository_id, "repository identifier"),
            (self.checkout_identity, "checkout identity"),
        ):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"{label} must be a lowercase path-safe slug")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("repository name must not be empty")
        if contains_absolute_path(self.name):
            raise ValueError("repository name must not contain a machine path")
        if (
            not isinstance(self.url, str)
            or re.fullmatch(r"https://[^/@\s]+/[^\s]+", self.url) is None
            or "@" in self.url.split("/", 3)[2]
        ):
            raise ValueError("repository URL must be credential-free HTTPS")
        if not isinstance(self.commit, str) or _GIT_OBJECT_ID.fullmatch(self.commit) is None:
            raise ValueError("repository commit must be a full lowercase Git object ID")
        if not isinstance(self.branch, str) or not self.branch.strip():
            raise ValueError("repository branch must not be empty")
        if self.tag is not None and (not isinstance(self.tag, str) or not self.tag.strip()):
            raise ValueError("repository tag must be null or non-empty")
        for value, label, positive in (
            (self.expected_project_count, "expected project count", True),
            (self.workers, "worker count", True),
            (self.timeout_seconds, "timeout", True),
            (self.tracked_size_bytes, "tracked size", False),
            (self.tracked_file_count, "tracked file count", False),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (1 if positive else 0)
            ):
                qualifier = "positive" if positive else "non-negative"
                raise ValueError(f"{label} must be a {qualifier} integer")
        if not isinstance(self.lfs_required, bool):
            raise ValueError("LFS requirement must be a boolean")
        if not isinstance(self.history_complete, bool):
            raise ValueError("repository history completeness must be a boolean")
        if not self.history_complete:
            raise ValueError("canonical repositories require complete declared-branch history")
        if tuple(sorted(self.submodules)) != self.submodules:
            raise ValueError("submodule definitions must use deterministic path order")
        if len({path for path, _ in self.submodules}) != len(self.submodules):
            raise ValueError("submodule paths must be unique")
        for path, commit in self.submodules:
            if contains_absolute_path(path) or "\\" in path or ".." in Path(path).parts:
                raise ValueError("submodule path must be repository-relative")
            if _GIT_OBJECT_ID.fullmatch(commit) is None:
                raise ValueError("submodule commit must be a full Git object ID")

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_id": self.repository_id,
            "name": self.name,
            "url": self.url,
            "commit": self.commit,
            "branch": self.branch,
            "tag": self.tag,
            "checkout_identity": self.checkout_identity,
            "expected_project_count": self.expected_project_count,
            "workers": self.workers,
            "timeout_seconds": self.timeout_seconds,
            "tracked_size_bytes": self.tracked_size_bytes,
            "tracked_file_count": self.tracked_file_count,
            "submodules": [
                {"path": path, "commit": commit}
                for path, commit in self.submodules
            ],
            "lfs_required": self.lfs_required,
            "history_complete": self.history_complete,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> BenchmarkRepositoryDefinition:
        _exact_keys(
            value,
            {
                "repository_id",
                "name",
                "url",
                "commit",
                "branch",
                "tag",
                "checkout_identity",
                "expected_project_count",
                "workers",
                "timeout_seconds",
                "tracked_size_bytes",
                "tracked_file_count",
                "submodules",
                "lfs_required",
                "history_complete",
            },
            "repository definition",
        )
        raw_submodules = value.get("submodules")
        if not isinstance(raw_submodules, Sequence) or isinstance(
            raw_submodules, (str, bytes, bytearray)
        ):
            raise ValueError("repository submodules must be an array")
        submodules = []
        for item in raw_submodules:
            mapping = _mapping(item, "submodule")
            _exact_keys(mapping, {"path", "commit"}, "submodule")
            submodules.append(
                (
                    _string(mapping.get("path"), "submodule path"),
                    _string(mapping.get("commit"), "submodule commit"),
                )
            )
        return cls(
            repository_id=_string(value.get("repository_id"), "repository identifier"),
            name=_string(value.get("name"), "repository name"),
            url=_string(value.get("url"), "repository URL"),
            commit=_string(value.get("commit"), "repository commit"),
            branch=_string(value.get("branch"), "repository branch"),
            tag=_optional_string(value.get("tag"), "repository tag"),
            checkout_identity=_string(
                value.get("checkout_identity"), "checkout identity"
            ),
            expected_project_count=_integer(
                value.get("expected_project_count"), "expected project count"
            ),
            workers=_integer(value.get("workers"), "worker count"),
            timeout_seconds=_integer(value.get("timeout_seconds"), "timeout"),
            tracked_size_bytes=_integer(
                value.get("tracked_size_bytes"), "tracked size"
            ),
            tracked_file_count=_integer(
                value.get("tracked_file_count"), "tracked file count"
            ),
            submodules=tuple(submodules),
            lfs_required=_boolean(value.get("lfs_required"), "LFS requirement"),
            history_complete=_boolean(
                value.get("history_complete"),
                "repository history completeness",
            ),
        )


@dataclass(frozen=True, slots=True)
class RepositoryVerification:
    repository_id: str
    commit: str
    remote_url: str
    detached_head: bool
    clean_worktree: bool
    initial_atlas_state_absent: bool
    tracked_size_bytes: int
    tracked_file_count: int
    submodules: tuple[tuple[str, str], ...]
    lfs_required: bool
    history_complete: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "repository_id": self.repository_id,
            "commit": self.commit,
            "remote_url": self.remote_url,
            "detached_head": self.detached_head,
            "clean_worktree": self.clean_worktree,
            "initial_atlas_state_absent": self.initial_atlas_state_absent,
            "tracked_size_bytes": self.tracked_size_bytes,
            "tracked_file_count": self.tracked_file_count,
            "submodules": [
                {"path": path, "commit": commit}
                for path, commit in self.submodules
            ],
            "lfs_required": self.lfs_required,
            "history_complete": self.history_complete,
        }


def load_definitions(
    path: Path = DEFAULT_DEFINITIONS,
) -> tuple[str, tuple[BenchmarkRepositoryDefinition, ...]]:
    """Load one exact canonical repository-definition document."""

    raw = path.read_bytes()
    try:
        decoded = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("benchmark repository definitions must be UTF-8 JSON") from exc
    root = _mapping(decoded, "repository definitions")
    _exact_keys(
        root,
        {"format", "schema_version", "benchmark_version", "repositories"},
        "repository definitions",
    )
    if root.get("format") != DEFINITIONS_FORMAT:
        raise ValueError("unsupported repository-definition format")
    if root.get("schema_version") != DEFINITIONS_SCHEMA_VERSION:
        raise ValueError("unsupported repository-definition schema")
    version = _string(root.get("benchmark_version"), "benchmark version")
    raw_repositories = root.get("repositories")
    if not isinstance(raw_repositories, Sequence) or isinstance(
        raw_repositories, (str, bytes, bytearray)
    ):
        raise ValueError("benchmark repositories must be an array")
    repositories = tuple(
        BenchmarkRepositoryDefinition.from_dict(
            _mapping(item, "repository definition")
        )
        for item in raw_repositories
    )
    if not repositories:
        raise ValueError("at least one benchmark repository is required")
    if tuple(sorted(item.repository_id for item in repositories)) != tuple(
        item.repository_id for item in repositories
    ):
        raise ValueError("benchmark repositories must use deterministic identifier order")
    if len({item.repository_id for item in repositories}) != len(repositories):
        raise ValueError("benchmark repository identifiers must be unique")
    canonical = _json_text(
        {
            "format": DEFINITIONS_FORMAT,
            "schema_version": DEFINITIONS_SCHEMA_VERSION,
            "benchmark_version": version,
            "repositories": [item.to_dict() for item in repositories],
        }
    ).encode("utf-8")
    if raw != canonical:
        raise ValueError("benchmark repository definitions are not canonical JSON")
    return version, repositories


def select_definition(
    repository_id: str,
    *,
    definitions_path: Path = DEFAULT_DEFINITIONS,
) -> tuple[str, BenchmarkRepositoryDefinition]:
    version, definitions = load_definitions(definitions_path)
    for definition in definitions:
        if definition.repository_id == repository_id:
            return version, definition
    raise ValueError(f"unknown benchmark repository: {repository_id}")


def prepare_checkout(
    definition: BenchmarkRepositoryDefinition,
    target: Path,
) -> RepositoryVerification:
    """Create a new detached checkout at the exact immutable definition commit."""

    destination = Path(os.path.abspath(target.expanduser()))
    if os.path.lexists(destination):
        raise FileExistsError(
            f"benchmark checkout target already exists: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    try:
        _git(destination, "init")
        if platform.system() == "Windows":
            _git(destination, "config", "core.longpaths", "true")
        _git(destination, "remote", "add", "origin", definition.url)
        branch_ref = f"refs/heads/{definition.branch}"
        remote_branch_ref = f"refs/remotes/origin/{definition.branch}"
        _git(
            destination,
            "fetch",
            "--no-tags",
            "origin",
            f"+{branch_ref}:{remote_branch_ref}",
        )
        if definition.tag is not None:
            tag_ref = f"refs/tags/{definition.tag}"
            _git(destination, "fetch", "--no-tags", "origin", f"+{tag_ref}:{tag_ref}")
        _git(destination, "checkout", "--detach", definition.commit)
        if definition.submodules:
            _git(destination, "submodule", "update", "--init", "--recursive")
        if definition.lfs_required:
            _git(destination, "lfs", "pull")
    except Exception as exc:
        raise RuntimeError(
            "fresh benchmark checkout failed; the partial target was retained for "
            f"inspection: {destination}"
        ) from exc
    return verify_checkout(definition, destination, require_initial_state=True)


def verify_checkout(
    definition: BenchmarkRepositoryDefinition,
    root: Path,
    *,
    require_initial_state: bool,
) -> RepositoryVerification:
    """Verify commit, remote, tree shape, worktree state, submodules, and LFS."""

    repository = root.expanduser().resolve()
    commit, verified, git_backed, _ = repository_benchmark._repository_identity(
        repository,
        definition.commit,
        allow_unpinned=False,
    )
    if not verified or not git_backed or commit != definition.commit:
        raise ValueError("benchmark checkout revision is not verified")
    if repository_benchmark._repository_is_partial_clone(repository):
        raise ValueError(
            "canonical benchmark checkout must contain full Git objects, not a "
            "partial/promisor clone"
        )
    history_complete = repository_benchmark._repository_history_complete(repository)
    if not history_complete:
        raise ValueError("canonical benchmark checkout must contain complete Git history")
    remote_branch_ref = f"refs/remotes/origin/{definition.branch}"
    branch_commit = _git_result(
        repository,
        "rev-parse",
        "--verify",
        f"{remote_branch_ref}^{{commit}}",
    )
    if branch_commit.returncode != 0:
        raise ValueError("canonical benchmark checkout is missing the declared branch")
    reachable = _git_result(
        repository,
        "merge-base",
        "--is-ancestor",
        definition.commit,
        remote_branch_ref,
    )
    if reachable.returncode == 1:
        raise ValueError("benchmark commit is not reachable from the declared branch")
    if reachable.returncode != 0:
        diagnostic = reachable.stderr.strip() or reachable.stdout.strip()
        raise RuntimeError(f"benchmark branch reachability check failed: {diagnostic}")
    tracked_atlas = repository_benchmark._git_required(
        repository,
        "ls-files",
        "--",
        ".atlas",
    )
    if tracked_atlas:
        raise ValueError("canonical benchmark repository must not track .atlas state")
    provenance = repository_benchmark._repository_provenance(
        repository,
        git_backed=True,
        repository_url=definition.url,
        repository_branch=definition.branch,
        repository_tag=definition.tag,
    )
    expected = (
        ("tracked size", provenance[3], definition.tracked_size_bytes),
        ("tracked file count", provenance[4], definition.tracked_file_count),
        ("submodules", provenance[5], definition.submodules),
        ("LFS requirement", provenance[6], definition.lfs_required),
        ("history completeness", provenance[7], definition.history_complete),
    )
    mismatches = [
        f"{name}: {actual!r} != {declared!r}"
        for name, actual, declared in expected
        if actual != declared
    ]
    if mismatches:
        raise ValueError("benchmark repository definition drift: " + "; ".join(mismatches))
    symbolic = _git_result(repository, "symbolic-ref", "-q", "HEAD")
    detached = symbolic.returncode != 0
    if not detached:
        raise ValueError("canonical benchmark checkout must use detached HEAD")
    sparse = _git_result(repository, "config", "--bool", "core.sparseCheckout")
    if sparse.returncode == 0 and sparse.stdout.strip().casefold() == "true":
        raise ValueError("canonical benchmark checkout must not be sparse")
    atlas_absent = not os.path.lexists(repository / ".atlas")
    if require_initial_state and not atlas_absent:
        raise ValueError("fresh benchmark checkout must not contain .atlas state")
    return RepositoryVerification(
        repository_id=definition.repository_id,
        commit=commit,
        remote_url=provenance[0] or definition.url,
        detached_head=True,
        clean_worktree=True,
        initial_atlas_state_absent=atlas_absent,
        tracked_size_bytes=provenance[3] or 0,
        tracked_file_count=provenance[4] or 0,
        submodules=provenance[5],
        lfs_required=bool(provenance[6]),
        history_complete=bool(provenance[7]),
    )


def capture_definition(
    definition: BenchmarkRepositoryDefinition,
    root: Path,
    *,
    atlas_commit: str,
    repeats: int = 3,
    observed_at_utc: str | None = None,
    benchmark_version: str = "m1.1",
) -> BenchmarkManifest:
    """Capture a fresh canonical analysis through the existing M1 runner."""

    verify_checkout(definition, root, require_initial_state=True)
    result = repository_benchmark.capture_analysis(
        root,
        repository_name=definition.name,
        expected_repository_commit=definition.commit,
        checkout_identity=definition.checkout_identity,
        repeats=repeats,
        workers=definition.workers,
        timeout_seconds=definition.timeout_seconds,
        observed_at_utc=observed_at_utc,
        repository_url=definition.url,
        repository_branch=definition.branch,
        repository_tag=definition.tag,
        expected_project_count=definition.expected_project_count,
        expected_atlas_commit=atlas_commit,
        reset_atlas_state=True,
        benchmark_version=benchmark_version,
    )
    if not result.baseline_eligible:
        raise RuntimeError("canonical fresh-analysis manifest is not baseline eligible")
    return result


def replay_definition(
    definition: BenchmarkRepositoryDefinition,
    root: Path,
    snapshot: Path,
    *,
    atlas_commit: str,
    source_manifest: BenchmarkManifest,
    repeats: int = 3,
    observed_at_utc: str | None = None,
    benchmark_version: str = "m1.1",
) -> BenchmarkManifest:
    """Replay a captured ASS with verified fresh-manifest lineage."""

    verify_checkout(definition, root, require_initial_state=False)
    result = repository_benchmark.capture_replay(
        snapshot,
        repository_root=root,
        repository_name=definition.name,
        project_count=definition.expected_project_count,
        success_count=definition.expected_project_count,
        expected_repository_commit=definition.commit,
        checkout_identity=definition.checkout_identity,
        repeats=repeats,
        observed_at_utc=observed_at_utc,
        source_manifest=source_manifest,
        repository_url=definition.url,
        repository_branch=definition.branch,
        repository_tag=definition.tag,
        expected_atlas_commit=atlas_commit,
        benchmark_version=benchmark_version,
    )
    if not result.baseline_eligible:
        raise RuntimeError("canonical snapshot-replay manifest is not baseline eligible")
    return result


def write_golden_bundle(
    target: Path,
    *,
    repository_root: Path,
    snapshot_path: Path,
    manifest: BenchmarkManifest,
) -> tuple[Path, ...]:
    """Write a source-free portable golden bundle through a staged directory."""

    destination = Path(os.path.abspath(target.expanduser()))
    if os.path.lexists(destination):
        raise FileExistsError(f"golden bundle target already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    store = SemanticSnapshotStore(
        Workspace(snapshot_path.parent, ()),
        snapshot_path.parent,
    )
    snapshot = store.load(snapshot_path)
    if snapshot is None:
        raise ValueError("semantic snapshot is unavailable for golden publication")
    portable = portable_snapshot_payload(snapshot, repository_root)
    context = _mapping(portable.get("semantic_context"), "portable semantic context")
    raw_report = context.get("repository_report")
    report = raw_report
    if not isinstance(raw_report, Mapping):
        report = {
            "available": False,
            "reason": "repository report is unavailable in this semantic snapshot",
        }
    explanation = ExplainEngine().explain(snapshot).markdown
    if contains_machine_path(explanation):
        raise ValueError("provider-free explanation contains an absolute machine path")
    risk = context.get("risk_analysis")
    graph = context.get("semantic_graph")
    observed = collect_snapshot_artifacts(
        snapshot_path,
        repository_root=repository_root,
    )
    artifact_checks = (
        ("snapshot size", observed.snapshot_size_bytes, manifest.artifacts.snapshot_size_bytes),
        ("snapshot hash", observed.snapshot_sha256, manifest.artifacts.snapshot_sha256),
        ("snapshot identifier", observed.snapshot_id, manifest.artifacts.snapshot_id),
        (
            "portable semantic hash",
            canonical_digest(portable),
            manifest.artifacts.portable_semantic_sha256,
        ),
        (
            "repository report hash",
            canonical_digest(raw_report) if isinstance(raw_report, Mapping) else None,
            manifest.artifacts.repository_report_sha256,
        ),
        (
            "provider-free explanation hash",
            canonical_text_digest(explanation),
            manifest.artifacts.explain_sha256,
        ),
        (
            "risk hash",
            canonical_digest(risk) if isinstance(risk, Mapping) else None,
            manifest.artifacts.risk_sha256,
        ),
        (
            "knowledge graph hash",
            canonical_digest(graph) if isinstance(graph, Mapping) else None,
            manifest.artifacts.knowledge_graph_sha256,
        ),
        (
            "workspace project order hash",
            observed.workspace_project_order_sha256,
            manifest.artifacts.workspace_project_order_sha256,
        ),
    )
    mismatches = [
        f"{name}: {actual!r} != {expected!r}"
        for name, actual, expected in artifact_checks
        if actual != expected
    ]
    if mismatches:
        raise ValueError("golden bundle does not match its manifest: " + "; ".join(mismatches))
    risk_summary = _risk_summary(risk, manifest)
    graph_summary = _graph_summary(graph, manifest)
    ordering = _ordering_summary(context, manifest)
    metadata = {
        "format": GOLDEN_BUNDLE_FORMAT,
        "schema_version": GOLDEN_BUNDLE_SCHEMA_VERSION,
        "benchmark_id": manifest.benchmark_id,
        "benchmark_version": manifest.benchmark_version,
        "manifest": manifest.to_dict(),
    }
    if contains_machine_path(
        [portable, report, explanation, risk_summary, graph_summary, ordering, metadata]
    ):
        raise ValueError("golden bundle contains an absolute machine path")
    payloads: dict[str, bytes] = {
        "semantic-snapshot.json": _json_text(portable).encode("utf-8"),
        "repository-report.json": _json_text(report).encode("utf-8"),
        "ai-explain.md": _canonical_text(explanation).encode("utf-8"),
        "risk-summary.json": _json_text(risk_summary).encode("utf-8"),
        "knowledge-graph-summary.json": _json_text(graph_summary).encode("utf-8"),
        "deterministic-ordering.json": _json_text(ordering).encode("utf-8"),
        "benchmark-metadata.json": _json_text(metadata).encode("utf-8"),
    }
    checksums = {
        name: hashlib.sha256(value).hexdigest()
        for name, value in sorted(payloads.items())
    }
    payloads["checksums.json"] = _json_text(
        {
            "format": "atlas-benchmark-golden-checksums",
            "schema_version": 1,
            "files": checksums,
        }
    ).encode("utf-8")
    published_names = tuple(sorted(payloads))
    staging = Path(
        tempfile.mkdtemp(prefix=destination.name + ".", dir=destination.parent)
    )
    try:
        for name, value in sorted(payloads.items()):
            path = staging / name
            with path.open("xb") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        del payloads
        del (
            snapshot,
            portable,
            context,
            raw_report,
            report,
            explanation,
            risk,
            graph,
            observed,
            artifact_checks,
            risk_summary,
            graph_summary,
            ordering,
            metadata,
            checksums,
        )
        verify_golden_bundle(
            staging,
            snapshot_path=snapshot_path,
            require_external_snapshot=True,
        )
        _publish_golden_directory(staging, destination)
    except Exception:
        for path in sorted(staging.glob("*"), reverse=True):
            if path.is_file():
                path.unlink()
        staging.rmdir()
        raise
    return tuple(destination / name for name in published_names)


def verify_golden_bundle(
    target: Path,
    *,
    snapshot_path: Path | None = None,
    require_external_snapshot: bool = False,
) -> BenchmarkManifest:
    """Strictly verify a portable golden bundle and optional raw ASS lineage.

    The portable bundle deliberately excludes the raw ASS because the latter can be
    large and contains checkout-scoped operational metadata. When supplied, the raw
    artifact is linked through its exact byte size, SHA-256, and semantic snapshot
    identifier. Release validation can require that external artifact explicitly.
    """

    bundle = target.expanduser()
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError(f"golden bundle must be a real directory: {bundle}")
    bundle = bundle.resolve()
    entries = tuple(bundle.iterdir())
    actual_names = {entry.name for entry in entries}
    if actual_names != _GOLDEN_FILES:
        raise ValueError(
            "golden bundle file set is invalid; "
            f"missing={sorted(_GOLDEN_FILES - actual_names)}, "
            f"unknown={sorted(actual_names - _GOLDEN_FILES)}"
        )
    invalid_entries = sorted(
        entry.name for entry in entries if entry.is_symlink() or not entry.is_file()
    )
    if invalid_entries:
        raise ValueError(
            "golden bundle entries must be regular files: "
            + ", ".join(invalid_entries)
        )

    documents = {
        name: _load_canonical_json(bundle / name)
        for name in sorted(_GOLDEN_JSON_FILES)
    }
    explanation = _load_canonical_text(bundle / "ai-explain.md")
    if contains_machine_path([*documents.values(), explanation]):
        raise ValueError("golden bundle contains an absolute machine path")

    raw_checksums = _mapping(documents["checksums.json"], "golden checksums")
    _exact_keys(
        raw_checksums,
        {"format", "schema_version", "files"},
        "golden checksums",
    )
    if raw_checksums.get("format") != "atlas-benchmark-golden-checksums":
        raise ValueError("unsupported golden checksum format")
    if raw_checksums.get("schema_version") != 1:
        raise ValueError("unsupported golden checksum schema")
    checksum_values = _mapping(raw_checksums.get("files"), "golden checksum files")
    if set(checksum_values) != _GOLDEN_PAYLOAD_FILES:
        raise ValueError(
            "golden checksum file set is invalid; "
            f"missing={sorted(_GOLDEN_PAYLOAD_FILES - set(checksum_values))}, "
            f"unknown={sorted(set(checksum_values) - _GOLDEN_PAYLOAD_FILES)}"
        )
    for name in sorted(_GOLDEN_PAYLOAD_FILES):
        expected = _string(checksum_values.get(name), f"checksum for {name}")
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ValueError(f"checksum for {name} must be a lowercase SHA-256")
        actual, _ = _file_sha256_and_size(bundle / name)
        if actual != expected:
            raise ValueError(
                f"golden bundle checksum mismatch for {name}: "
                f"{actual!r} != {expected!r}"
            )

    metadata = _mapping(documents["benchmark-metadata.json"], "golden metadata")
    _exact_keys(
        metadata,
        {"format", "schema_version", "benchmark_id", "benchmark_version", "manifest"},
        "golden metadata",
    )
    if metadata.get("format") != GOLDEN_BUNDLE_FORMAT:
        raise ValueError("unsupported golden bundle format")
    if metadata.get("schema_version") != GOLDEN_BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported golden bundle schema")
    manifest_mapping = _mapping(metadata.get("manifest"), "embedded benchmark manifest")
    manifest = BenchmarkManifest.from_dict(manifest_mapping)
    if manifest.to_dict() != manifest_mapping:
        raise ValueError("embedded benchmark manifest is not exactly round-trippable")
    if not manifest.baseline_eligible:
        raise ValueError("embedded benchmark manifest is not baseline eligible")
    if metadata.get("benchmark_id") != manifest.benchmark_id:
        raise ValueError("golden metadata benchmark identifier does not match manifest")
    if metadata.get("benchmark_version") != manifest.benchmark_version:
        raise ValueError("golden metadata benchmark version does not match manifest")

    portable = _mapping(documents["semantic-snapshot.json"], "portable semantic snapshot")
    _exact_keys(
        portable,
        {
            "format",
            "projection_version",
            "snapshot_schema_version",
            "workspace_fingerprint",
            "analyzer_version",
            "semantic_context",
        },
        "portable semantic snapshot",
    )
    if portable.get("format") != PORTABLE_SNAPSHOT_FORMAT:
        raise ValueError("unsupported portable semantic snapshot format")
    if portable.get("projection_version") != PORTABLE_SNAPSHOT_VERSION:
        raise ValueError("unsupported portable semantic snapshot projection version")
    snapshot_schema = portable.get("snapshot_schema_version")
    if (
        isinstance(snapshot_schema, bool)
        or not isinstance(snapshot_schema, int)
        or snapshot_schema < 1
    ):
        raise ValueError("portable semantic snapshot schema must be a positive integer")
    if portable.get("workspace_fingerprint") != "PATH_SCOPED_WORKSPACE_FINGERPRINT":
        raise ValueError("portable semantic snapshot fingerprint is invalid")
    _string(portable.get("analyzer_version"), "portable analyzer version")
    context = _mapping(portable.get("semantic_context"), "portable semantic context")
    workspace_projects = _workspace_project_names(context)
    ordering_checks = (
        ("project count", len(workspace_projects), manifest.project_count),
        (
            "workspace project inventory",
            workspace_projects,
            manifest.artifacts.workspace_projects,
        ),
        (
            "workspace project order hash",
            canonical_digest(workspace_projects),
            manifest.artifacts.workspace_project_order_sha256,
        ),
        (
            "analysis order hash",
            canonical_digest(manifest.artifacts.analysis_order),
            manifest.artifacts.analysis_order_sha256,
        ),
        (
            "deterministic ordering hash",
            canonical_digest(
                {
                    "analysis_order": manifest.artifacts.analysis_order,
                    "workspace_project_order_sha256": (
                        manifest.artifacts.workspace_project_order_sha256
                    ),
                }
            ),
            manifest.artifacts.deterministic_ordering_sha256,
        ),
    )
    ordering_mismatches = [
        f"{name}: {actual!r} != {expected!r}"
        for name, actual, expected in ordering_checks
        if actual != expected
    ]
    if set(workspace_projects) != set(manifest.artifacts.analysis_order):
        ordering_mismatches.append(
            "analysis order does not contain exactly the portable workspace projects"
        )
    if ordering_mismatches:
        raise ValueError(
            "golden bundle ordering does not match portable semantics: "
            + "; ".join(ordering_mismatches)
        )
    raw_report = context.get("repository_report")
    report = raw_report
    if not isinstance(raw_report, Mapping):
        report = {
            "available": False,
            "reason": "repository report is unavailable in this semantic snapshot",
        }
    semantic_checks = (
        (
            "portable semantic hash",
            canonical_digest(portable),
            manifest.artifacts.portable_semantic_sha256,
        ),
        (
            "repository report hash",
            canonical_digest(raw_report) if isinstance(raw_report, Mapping) else None,
            manifest.artifacts.repository_report_sha256,
        ),
        (
            "provider-free explanation hash",
            canonical_text_digest(explanation),
            manifest.artifacts.explain_sha256,
        ),
        (
            "risk hash",
            canonical_digest(context["risk_analysis"])
            if isinstance(context.get("risk_analysis"), Mapping)
            else None,
            manifest.artifacts.risk_sha256,
        ),
        (
            "knowledge graph hash",
            canonical_digest(context["semantic_graph"])
            if isinstance(context.get("semantic_graph"), Mapping)
            else None,
            manifest.artifacts.knowledge_graph_sha256,
        ),
    )
    mismatches = [
        f"{name}: {actual!r} != {expected!r}"
        for name, actual, expected in semantic_checks
        if actual != expected
    ]
    if mismatches:
        raise ValueError(
            "golden bundle content does not match its manifest: " + "; ".join(mismatches)
        )
    if documents["repository-report.json"] != report:
        raise ValueError("golden repository report does not match portable semantics")
    if documents["risk-summary.json"] != _risk_summary(
        context.get("risk_analysis"), manifest
    ):
        raise ValueError("golden risk summary does not match portable semantics")
    if documents["knowledge-graph-summary.json"] != _graph_summary(
        context.get("semantic_graph"), manifest
    ):
        raise ValueError("golden knowledge graph summary does not match portable semantics")
    if documents["deterministic-ordering.json"] != _ordering_summary(context, manifest):
        raise ValueError("golden deterministic ordering does not match portable semantics")

    if require_external_snapshot and snapshot_path is None:
        raise ValueError("external raw ASS is required for golden bundle verification")
    if snapshot_path is not None:
        _verify_external_snapshot(snapshot_path, manifest)
    return manifest


def _preflight_capture_outputs(
    manifest_output: Path,
    golden_output: Path,
) -> tuple[Path, Path]:
    manifest_target = Path(os.path.abspath(manifest_output.expanduser()))
    golden_target = Path(os.path.abspath(golden_output.expanduser()))
    if (
        manifest_target == golden_target
        or manifest_target.is_relative_to(golden_target)
        or golden_target.is_relative_to(manifest_target)
    ):
        raise ValueError("manifest and golden output targets must not overlap")
    for target, label in (
        (manifest_target, "manifest"),
        (golden_target, "golden bundle"),
    ):
        if os.path.lexists(target):
            raise FileExistsError(f"{label} output already exists: {target}")
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    golden_target.parent.mkdir(parents=True, exist_ok=True)
    for target, label in (
        (manifest_target, "manifest"),
        (golden_target, "golden bundle"),
    ):
        if os.path.lexists(target):
            raise FileExistsError(f"{label} output appeared during preflight: {target}")
    return manifest_target, golden_target


def _publish_capture_outputs(
    manifest_output: Path,
    golden_output: Path,
    *,
    repository_root: Path,
    snapshot_path: Path,
    manifest: BenchmarkManifest,
) -> None:
    """Stage, validate, and no-clobber publish both canonical capture outputs."""

    manifest_target, golden_target = _preflight_capture_outputs(
        manifest_output,
        golden_output,
    )
    descriptor, temporary_manifest = tempfile.mkstemp(
        prefix=manifest_target.name + ".",
        suffix=".tmp",
        dir=manifest_target.parent,
    )
    manifest_staging = Path(temporary_manifest)
    golden_transaction = Path(
        tempfile.mkdtemp(
            prefix=golden_target.name + ".transaction.",
            dir=golden_target.parent,
        )
    )
    golden_staging = golden_transaction / "bundle"
    manifest_published = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(manifest.to_json().encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        BenchmarkManifest.from_file(manifest_staging)
        write_golden_bundle(
            golden_staging,
            repository_root=repository_root,
            snapshot_path=snapshot_path,
            manifest=manifest,
        )
        verify_golden_bundle(
            golden_staging,
            snapshot_path=snapshot_path,
            require_external_snapshot=True,
        )
        if os.path.lexists(manifest_target) or os.path.lexists(golden_target):
            raise FileExistsError("capture output appeared before publication")
        try:
            os.link(manifest_staging, manifest_target)
        except FileExistsError as exc:
            raise FileExistsError(
                f"manifest output appeared during publication: {manifest_target}"
            ) from exc
        manifest_published = True
        _publish_golden_directory(golden_staging, golden_target)
    except Exception:
        if manifest_published:
            try:
                if manifest_target.exists() and os.path.samefile(
                    manifest_staging, manifest_target
                ):
                    manifest_target.unlink()
            except OSError as rollback_error:
                raise RuntimeError(
                    "capture publication failed and its manifest output could not be "
                    f"rolled back: {manifest_target}"
                ) from rollback_error
        raise
    finally:
        manifest_staging.unlink(missing_ok=True)
        if golden_staging.exists():
            _remove_staged_golden_bundle(golden_staging)
        golden_transaction.rmdir()


def _remove_staged_golden_bundle(path: Path) -> None:
    for name in sorted(_GOLDEN_FILES):
        (path / name).unlink(missing_ok=True)
    path.rmdir()


def _publish_golden_directory(staging: Path, destination: Path) -> None:
    """Publish exact staged files without ever replacing an existing path."""

    try:
        destination.mkdir()
    except FileExistsError as exc:
        raise FileExistsError(
            f"golden bundle output appeared during publication: {destination}"
        ) from exc
    created: dict[str, tuple[int, int]] = {}
    try:
        for name in sorted(_GOLDEN_FILES):
            source = staging / name
            target = destination / name
            try:
                os.link(source, target)
            except FileExistsError:
                raise
            except OSError:
                with source.open("rb") as reader, target.open("xb") as writer:
                    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                        writer.write(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
            identity = target.stat(follow_symlinks=False)
            created[name] = (identity.st_dev, identity.st_ino)
        actual_names = {entry.name for entry in destination.iterdir()}
        if actual_names != _GOLDEN_FILES:
            raise RuntimeError(
                "golden bundle target changed during exclusive publication"
            )
    except Exception:
        for name, identity in reversed(tuple(created.items())):
            target = destination / name
            try:
                observed = target.stat(follow_symlinks=False)
                if (observed.st_dev, observed.st_ino) == identity:
                    target.unlink()
            except FileNotFoundError:
                pass
        try:
            destination.rmdir()
        except OSError as rollback_error:
            raise RuntimeError(
                "golden publication failed and the target contains paths not "
                f"created by this invocation: {destination}"
            ) from rollback_error
        raise
    _remove_staged_golden_bundle(staging)


def _risk_summary(value: object, manifest: BenchmarkManifest) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {
            "available": False,
            "risk_sha256": None,
            "limitations": ["risk analysis is unavailable in this semantic snapshot"],
        }
    hotspots = value.get("hotspots")
    heatmaps = value.get("heatmaps")
    return {
        "available": True,
        "producer_version": value.get("producer_version"),
        "hotspot_count": len(hotspots) if isinstance(hotspots, Sequence) else 0,
        "heatmap_count": len(heatmaps) if isinstance(heatmaps, Sequence) else 0,
        "capabilities": value.get("capabilities", {}),
        "limitations": value.get("limitations", []),
        "risk_sha256": manifest.artifacts.risk_sha256,
    }


def _graph_summary(value: object, manifest: BenchmarkManifest) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {
            "available": False,
            "knowledge_graph_sha256": None,
            "node_count": 0,
            "edge_count": 0,
        }
    nodes = value.get("nodes")
    edges = value.get("edges")
    node_values = nodes if isinstance(nodes, Sequence) else ()
    edge_values = edges if isinstance(edges, Sequence) else ()
    node_kinds = Counter(
        str(item.get("kind"))
        for item in node_values
        if isinstance(item, Mapping) and item.get("kind") is not None
    )
    edge_kinds = Counter(
        str(item.get("kind"))
        for item in edge_values
        if isinstance(item, Mapping) and item.get("kind") is not None
    )
    return {
        "available": True,
        "schema_version": value.get("schema_version"),
        "node_count": len(node_values),
        "edge_count": len(edge_values),
        "node_kinds": dict(sorted(node_kinds.items())),
        "relation_kinds": dict(sorted(edge_kinds.items())),
        "knowledge_graph_sha256": manifest.artifacts.knowledge_graph_sha256,
    }


def _ordering_summary(
    context: Mapping[str, object],
    manifest: BenchmarkManifest,
) -> dict[str, object]:
    projects = _workspace_project_names(context)
    return {
        "workspace_projects": list(projects),
        "analysis_order": list(manifest.artifacts.analysis_order),
        "workspace_project_order_sha256": (
            manifest.artifacts.workspace_project_order_sha256
        ),
        "analysis_order_sha256": manifest.artifacts.analysis_order_sha256,
        "deterministic_ordering_sha256": (
            manifest.artifacts.deterministic_ordering_sha256
        ),
    }


def _workspace_project_names(
    context: Mapping[str, object],
) -> tuple[str, ...]:
    workspace = _mapping(context.get("workspace"), "portable workspace")
    raw_projects = workspace.get("projects")
    if not isinstance(raw_projects, Sequence) or isinstance(
        raw_projects, (str, bytes, bytearray)
    ):
        raise ValueError("portable workspace projects must be an array")
    projects: list[str] = []
    for item in raw_projects:
        project = _mapping(item, "portable workspace project")
        projects.append(_string(project.get("name"), "portable project name"))
    if len(set(projects)) != len(projects):
        raise ValueError("portable workspace project names must be unique")
    return tuple(projects)


def _git(root: Path, *arguments: str) -> str:
    result = _git_result(root, *arguments)
    if result.returncode != 0:
        diagnostic = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"benchmark Git command failed: {diagnostic}")
    return result.stdout.strip()


def _git_result(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=3_600,
    )


def _json_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _canonical_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def _load_canonical_json(path: Path) -> object:
    before = path.stat()
    raw_hash, raw_size = _file_sha256_and_size(path)
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            value = json.load(stream, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"golden JSON must be valid UTF-8: {path.name}") from exc
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    canonical_hash = hashlib.sha256()
    canonical_size = 0
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8")
        canonical_hash.update(encoded)
        canonical_size += len(encoded)
    canonical_hash.update(b"\n")
    canonical_size += 1
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"golden file changed while it was verified: {path.name}")
    if canonical_size != raw_size or canonical_hash.hexdigest() != raw_hash:
        raise ValueError(f"golden JSON is not canonical: {path.name}")
    return value


def _load_canonical_text(path: Path) -> str:
    before = path.stat()
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError(f"golden text must not contain a UTF-8 BOM: {path.name}")
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"golden text must be valid UTF-8: {path.name}") from exc
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"golden file changed while it was verified: {path.name}")
    if _canonical_text(value).encode("utf-8") != raw:
        raise ValueError(f"golden text is not canonical: {path.name}")
    return value


def _file_sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _verify_external_snapshot(path: Path, manifest: BenchmarkManifest) -> None:
    source = path.expanduser()
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"external raw ASS must be a regular file: {source}")
    source = source.resolve()
    before = source.stat()
    raw_hash, raw_size = _file_sha256_and_size(source)
    store = SemanticSnapshotStore(Workspace(source.parent, ()), source.parent)
    snapshot = store.load(source)
    if snapshot is None:
        raise ValueError("external raw ASS is unavailable")
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("external raw ASS changed while it was verified")
    checks = (
        ("size", raw_size, manifest.artifacts.snapshot_size_bytes),
        ("SHA-256", raw_hash, manifest.artifacts.snapshot_sha256),
        ("snapshot identifier", snapshot.snapshot_id, manifest.artifacts.snapshot_id),
    )
    mismatches = [
        f"{name}: {actual!r} != {expected!r}"
        for name, actual, expected in checks
        if actual != expected
    ]
    if mismatches:
        raise ValueError(
            "external raw ASS does not match golden manifest: " + "; ".join(mismatches)
        )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{name} fields are invalid; missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid non-finite JSON number: {value}")


def _emit_json(value: object) -> None:
    print(_json_text(value), end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definitions", type=Path, default=DEFAULT_DEFINITIONS)
    commands = parser.add_subparsers(dest="command", required=True)
    list_command = commands.add_parser("list", help="List canonical definitions.")
    list_command.set_defaults(command="list")
    prepare = commands.add_parser("prepare", help="Create one fresh pinned checkout.")
    prepare.add_argument("repository_id")
    prepare.add_argument("target", type=Path)
    verify = commands.add_parser("verify", help="Verify one pinned checkout.")
    verify.add_argument("repository_id")
    verify.add_argument("root", type=Path)
    verify.add_argument("--require-initial-state", action="store_true")
    verify_golden = commands.add_parser(
        "verify-golden",
        help="Strictly verify one portable golden bundle.",
    )
    verify_golden.add_argument("bundle", type=Path)
    verify_golden.add_argument("--snapshot", type=Path)
    verify_golden.add_argument("--require-snapshot", action="store_true")
    capture = commands.add_parser("capture", help="Capture one fresh canonical baseline.")
    capture.add_argument("repository_id")
    capture.add_argument("root", type=Path)
    capture.add_argument("--atlas-commit", required=True)
    capture.add_argument("--repeats", type=int, default=3)
    capture.add_argument("--observed-at")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--golden-output", type=Path, required=True)
    replay = commands.add_parser("replay", help="Replay a linked canonical snapshot.")
    replay.add_argument("repository_id")
    replay.add_argument("root", type=Path)
    replay.add_argument("snapshot", type=Path)
    replay.add_argument("--atlas-commit", required=True)
    replay.add_argument("--source-manifest", type=Path, required=True)
    replay.add_argument("--repeats", type=int, default=3)
    replay.add_argument("--observed-at")
    replay.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    version, definitions = load_definitions(arguments.definitions)
    if arguments.command == "list":
        _emit_json(
            {
                "benchmark_version": version,
                "repositories": [item.to_dict() for item in definitions],
            }
        )
        return 0
    if arguments.command == "verify-golden":
        verified = verify_golden_bundle(
            arguments.bundle,
            snapshot_path=arguments.snapshot,
            require_external_snapshot=arguments.require_snapshot,
        )
        _emit_json(
            {
                "format": GOLDEN_BUNDLE_FORMAT,
                "schema_version": GOLDEN_BUNDLE_SCHEMA_VERSION,
                "benchmark_id": verified.benchmark_id,
                "benchmark_version": verified.benchmark_version,
                "external_snapshot_verified": arguments.snapshot is not None,
            }
        )
        return 0
    definition = next(
        (
            item
            for item in definitions
            if item.repository_id == arguments.repository_id
        ),
        None,
    )
    if definition is None:
        parser.error(f"unknown benchmark repository: {arguments.repository_id}")
    if arguments.command == "prepare":
        _emit_json(prepare_checkout(definition, arguments.target).to_dict())
        return 0
    if arguments.command == "verify":
        _emit_json(
            verify_checkout(
                definition,
                arguments.root,
                require_initial_state=arguments.require_initial_state,
            ).to_dict()
        )
        return 0
    if arguments.command == "capture":
        manifest_output, golden_output = _preflight_capture_outputs(
            arguments.output,
            arguments.golden_output,
        )
        manifest = capture_definition(
            definition,
            arguments.root,
            atlas_commit=arguments.atlas_commit,
            repeats=arguments.repeats,
            observed_at_utc=arguments.observed_at,
            benchmark_version=version,
        )
        snapshot = arguments.root / ".atlas" / "ass" / "latest.ass"
        _publish_capture_outputs(
            manifest_output,
            golden_output,
            repository_root=arguments.root,
            snapshot_path=snapshot,
            manifest=manifest,
        )
        return 0
    source = BenchmarkManifest.from_file(arguments.source_manifest)
    manifest = replay_definition(
        definition,
        arguments.root,
        arguments.snapshot,
        atlas_commit=arguments.atlas_commit,
        source_manifest=source,
        repeats=arguments.repeats,
        observed_at_utc=arguments.observed_at,
        benchmark_version=version,
    )
    repository_benchmark._write(arguments.output, manifest.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BenchmarkRepositoryDefinition",
    "DEFINITIONS_FORMAT",
    "DEFINITIONS_SCHEMA_VERSION",
    "DEFAULT_DEFINITIONS",
    "RepositoryVerification",
    "capture_definition",
    "load_definitions",
    "prepare_checkout",
    "replay_definition",
    "select_definition",
    "verify_checkout",
    "verify_golden_bundle",
    "write_golden_bundle",
]
