import json
from pathlib import Path

import pytest

from moughorai.project_index import PersistentProjectIndex, ProjectFileIndexer, ProjectIndexStore


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_hashes_files(tmp_path: Path):
    write(tmp_path / "A.java", "class A {}")
    snapshot = ProjectFileIndexer().build(tmp_path)
    assert len(snapshot.files[0].sha256) == 64


def test_build_is_sorted(tmp_path: Path):
    write(tmp_path / "z.java", "z")
    write(tmp_path / "A.java", "a")
    assert [x.relative_path.name for x in ProjectFileIndexer().build(tmp_path).files] == ["A.java", "z.java"]


def test_same_content_has_same_hash(tmp_path: Path):
    write(tmp_path / "A.java", "same")
    first = ProjectFileIndexer().build(tmp_path)
    second = ProjectFileIndexer().build(tmp_path)
    assert first.files[0].sha256 == second.files[0].sha256


def test_compare_detects_added(tmp_path: Path):
    indexer = ProjectFileIndexer()
    old = indexer.build(tmp_path)
    write(tmp_path / "A.java", "a")
    change = indexer.compare(old, indexer.build(tmp_path))
    assert change.added == (Path("A.java"),)


def test_compare_detects_removed(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    indexer = ProjectFileIndexer()
    old = indexer.build(tmp_path)
    (tmp_path / "A.java").unlink()
    assert indexer.compare(old, indexer.build(tmp_path)).removed == (Path("A.java"),)


def test_compare_detects_modified_content(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    indexer = ProjectFileIndexer()
    old = indexer.build(tmp_path)
    write(tmp_path / "A.java", "b")
    assert indexer.compare(old, indexer.build(tmp_path)).modified == (Path("A.java"),)


def test_compare_marks_unchanged(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    indexer = ProjectFileIndexer()
    old = indexer.build(tmp_path)
    assert indexer.compare(old, indexer.build(tmp_path)).unchanged == (Path("A.java"),)


def test_change_set_reports_changes(tmp_path: Path):
    old = ProjectFileIndexer().build(tmp_path)
    write(tmp_path / "A.java", "a")
    assert ProjectFileIndexer().compare(old, ProjectFileIndexer().build(tmp_path)).has_changes


def test_store_round_trip(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    snapshot = ProjectFileIndexer().build(tmp_path)
    cache = tmp_path / ".atlas-cache/index.json"
    ProjectIndexStore().save(snapshot, cache)
    assert ProjectIndexStore().load(cache) == snapshot


def test_store_creates_parent(tmp_path: Path):
    cache = tmp_path / "deep/index.json"
    ProjectIndexStore().save(ProjectFileIndexer().build(tmp_path), cache)
    assert cache.exists()


def test_store_uses_current_schema(tmp_path: Path):
    cache = tmp_path / "index.json"
    ProjectIndexStore().save(ProjectFileIndexer().build(tmp_path), cache)
    assert json.loads(cache.read_text())["schema_version"] == 1


def test_store_rejects_unknown_schema(tmp_path: Path):
    cache = tmp_path / "index.json"
    cache.write_text('{"schema_version": 99, "root": ".", "files": []}')
    with pytest.raises(ValueError, match="unsupported"):
        ProjectIndexStore().load(cache)


def test_refresh_initially_adds_every_file(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    snapshot, changes = PersistentProjectIndex().refresh(tmp_path, tmp_path / "cache/index.json")
    assert len(snapshot.files) == 1
    assert changes.added == (Path("A.java"),)


def test_refresh_reuses_cache(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    cache = tmp_path / "cache/index.json"
    service = PersistentProjectIndex()
    service.refresh(tmp_path, cache)
    _, changes = service.refresh(tmp_path, cache)
    assert changes.unchanged == (Path("A.java"),)
    assert not changes.has_changes


def test_refresh_detects_update(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    cache = tmp_path / "cache/index.json"
    service = PersistentProjectIndex()
    service.refresh(tmp_path, cache)
    write(tmp_path / "A.java", "changed")
    _, changes = service.refresh(tmp_path, cache)
    assert changes.modified == (Path("A.java"),)


def test_scanner_ignores_cache_directory(tmp_path: Path):
    write(tmp_path / "A.java", "a")
    cache = tmp_path / ".atlas-cache/index.json"
    service = PersistentProjectIndex()
    snapshot, _ = service.refresh(tmp_path, cache)
    assert [x.relative_path for x in snapshot.files] == [Path("A.java")]


def test_invalid_chunk_size_is_rejected():
    with pytest.raises(ValueError):
        ProjectFileIndexer(chunk_size=0)


def test_binary_content_is_supported(tmp_path: Path):
    (tmp_path / "x.jar").write_bytes(bytes(range(32)))
    assert ProjectFileIndexer().build(tmp_path).files[0].size == 32


def test_paths_are_relative(tmp_path: Path):
    write(tmp_path / "src/A.java", "a")
    assert ProjectFileIndexer().build(tmp_path).files[0].relative_path == Path("src/A.java")


def test_empty_project_round_trip(tmp_path: Path):
    snapshot = ProjectFileIndexer().build(tmp_path)
    cache = tmp_path / "cache/index.json"
    ProjectIndexStore().save(snapshot, cache)
    assert ProjectIndexStore().load(cache).files == ()
