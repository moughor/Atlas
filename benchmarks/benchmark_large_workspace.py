"""Reproducible large-workspace benchmark using Atlas production paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

from moughorai.project_index import ProjectFileIndexer
from moughorai.workspace import Project, Workspace, WorkspaceCache


DEFAULT_FILES = 23_000
DEFAULT_PROJECTS = 23


def create_workspace(root: Path, *, files: int, projects: int) -> Workspace:
    """Create a deterministic Java workspace without retaining generated data."""
    if files < 1 or projects < 1:
        raise ValueError("files and projects must be positive")
    if projects > files:
        raise ValueError("projects must not exceed files")

    counts = [files // projects] * projects
    for index in range(files % projects):
        counts[index] += 1

    definitions: list[Project] = []
    for project_index, count in enumerate(counts):
        project_root = root / f"project-{project_index:03d}"
        source_root = project_root / "src" / "main" / "java"
        source_root.mkdir(parents=True)
        for file_index in range(count):
            package = source_root / f"package-{file_index // 250:03d}"
            package.mkdir(exist_ok=True)
            name = f"Type{file_index:05d}"
            (package / f"{name}.java").write_text(
                f"package benchmark.p{project_index};\n"
                f"final class {name} {{ int value = {file_index}; }}\n",
                encoding="utf-8",
                newline="\n",
            )
        definitions.append(
            Project(
                name=f"project-{project_index:03d}",
                path=project_root,
                include=("src/**/*.java",),
            )
        )
    return Workspace(root=root, projects=tuple(definitions))


def benchmark(root: Path, *, files: int = DEFAULT_FILES, projects: int = DEFAULT_PROJECTS) -> dict[str, object]:
    """Generate and measure indexing and hashing of a large workspace."""
    setup_started = perf_counter()
    workspace = create_workspace(root, files=files, projects=projects)
    setup_seconds = perf_counter() - setup_started

    tracemalloc.start()
    measured_started = perf_counter()
    indexer = ProjectFileIndexer()
    snapshots = tuple(indexer.build(project.path) for project in workspace.projects)
    indexing_seconds = perf_counter() - measured_started
    cache_started = perf_counter()
    workspace_snapshot = WorkspaceCache().snapshot(workspace)
    fingerprint_seconds = perf_counter() - cache_started
    measured_seconds = perf_counter() - measured_started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    indexed_files = sum(len(snapshot.files) for snapshot in snapshots)
    if indexed_files != files:
        raise RuntimeError(f"expected {files} indexed files, got {indexed_files}")

    digest = hashlib.sha256()
    for snapshot in snapshots:
        for item in snapshot.files:
            digest.update(item.relative_path.as_posix().encode())
            digest.update(item.sha256.encode())
    for name, fingerprint in workspace_snapshot.fingerprints:
        digest.update(name.encode())
        digest.update(fingerprint.encode())

    return {
        "schema_version": 1,
        "files": files,
        "projects": projects,
        "indexed_files": indexed_files,
        "setup_seconds": round(setup_seconds, 6),
        "indexing_seconds": round(indexing_seconds, 6),
        "fingerprint_seconds": round(fingerprint_seconds, 6),
        "measured_seconds": round(measured_seconds, 6),
        "files_per_second": round(files / measured_seconds, 2),
        "peak_memory_mib": round(peak_bytes / (1024 * 1024), 2),
        "content_checksum": digest.hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=DEFAULT_FILES)
    parser.add_argument("--projects", type=int, default=DEFAULT_PROJECTS)
    parser.add_argument("--workspace", type=Path)
    arguments = parser.parse_args()
    if arguments.workspace is not None:
        arguments.workspace.mkdir(parents=True, exist_ok=True)
        report = benchmark(arguments.workspace, files=arguments.files, projects=arguments.projects)
    else:
        with tempfile.TemporaryDirectory(prefix="atlas-large-workspace-") as directory:
            report = benchmark(Path(directory), files=arguments.files, projects=arguments.projects)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
