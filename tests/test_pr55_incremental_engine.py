from __future__ import annotations

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from moughorai.incremental_analysis import (
    CacheEntry,
    CacheFormatError,
    FileFingerprint,
    FingerprintService,
    IncrementalAnalysisEngine,
    IncrementalCache,
)


def fp(path: str, char: str = "a", size: int = 1) -> FileFingerprint:
    return FileFingerprint(Path(path), size, char * 64)


def test_digest_bytes_is_sha256():
    assert FingerprintService.digest_bytes(b"atlas") == "7c82602500857aa6ed0cf38c4c3e4ec645bdcaa82c00b9155eb08be100c778a9"


def test_fingerprint_file(tmp_path: Path):
    path = tmp_path / "A.java"
    path.write_text("class A {}", encoding="utf-8")
    value = FingerprintService().fingerprint(Path("A.java"), root=tmp_path)
    assert value.path == Path("A.java")
    assert value.size == 10


def test_scan_is_deterministic(tmp_path: Path):
    (tmp_path / "b").write_text("b")
    (tmp_path / "A").write_text("a")
    values = FingerprintService().scan(tmp_path, [Path("b"), Path("A")])
    assert [x.path.as_posix() for x in values] == ["A", "b"]


@pytest.mark.parametrize("size", [-1, -5])
def test_fingerprint_rejects_negative_size(size: int):
    with pytest.raises(ValueError):
        FileFingerprint(Path("x"), size, "a" * 64)


@pytest.mark.parametrize("digest", ["", "a" * 63, "A" * 64, "z" * 64])
def test_fingerprint_rejects_bad_digest(digest: str):
    with pytest.raises(ValueError):
        FileFingerprint(Path("x"), 0, digest)


def test_cache_put_and_get():
    cache = IncrementalCache()
    cache.put("A.java", "a" * 64, {"ok": True})
    assert cache.get("A.java", "a" * 64) == {"ok": True}
    assert cache.statistics.hits == 1
    assert cache.statistics.writes == 1


def test_cache_miss_for_unknown_key():
    cache = IncrementalCache()
    assert cache.get("missing", "a" * 64) is None
    assert cache.statistics.misses == 1


def test_cache_miss_for_changed_fingerprint():
    cache = IncrementalCache([CacheEntry("x", "a" * 64, 1)])
    assert cache.get("x", "b" * 64) is None


def test_cache_dependencies_are_deduplicated_and_sorted():
    entry = CacheEntry("x", "a" * 64, 1, ("z", "a", "z"))
    assert entry.dependencies == ("a", "z")


def test_cache_remove():
    cache = IncrementalCache([CacheEntry("x", "a" * 64, 1)])
    assert cache.remove("x") is True
    assert cache.remove("x") is False
    assert cache.statistics.removals == 1


def test_cache_clear():
    cache = IncrementalCache([CacheEntry("a", "a" * 64, 1), CacheEntry("b", "b" * 64, 2)])
    assert cache.clear() == 2
    assert cache.entries == ()


def test_cache_direct_invalidation():
    cache = IncrementalCache([CacheEntry("a", "a" * 64, 1), CacheEntry("b", "b" * 64, 2)])
    assert cache.invalidate(["a"], transitive=False) == ("a",)
    assert [x.key for x in cache.entries] == ["b"]


def test_cache_transitive_invalidation():
    cache = IncrementalCache([
        CacheEntry("a", "a" * 64, 1),
        CacheEntry("b", "b" * 64, 2, ("a",)),
        CacheEntry("c", "c" * 64, 3, ("b",)),
    ])
    assert cache.invalidate(["a"]) == ("a", "b", "c")
    assert cache.statistics.invalidations == 3


def test_cache_unrelated_entries_survive_invalidation():
    cache = IncrementalCache([
        CacheEntry("a", "a" * 64, 1),
        CacheEntry("b", "b" * 64, 2, ("a",)),
        CacheEntry("x", "c" * 64, 3),
    ])
    cache.invalidate(["a"])
    assert [x.key for x in cache.entries] == ["x"]


def test_cache_json_is_deterministic():
    left = IncrementalCache([CacheEntry("b", "b" * 64, 2), CacheEntry("a", "a" * 64, 1)])
    right = IncrementalCache([CacheEntry("a", "a" * 64, 1), CacheEntry("b", "b" * 64, 2)])
    assert left.to_json() == right.to_json()


def test_cache_save_and_load(tmp_path: Path):
    path = tmp_path / "cache.json"
    cache = IncrementalCache([CacheEntry("a", "a" * 64, {"n": 1}, ("dep",))])
    cache.save(path)
    loaded = IncrementalCache.load(path)
    assert loaded.entries == cache.entries


def test_cache_load_missing_returns_empty(tmp_path: Path):
    assert IncrementalCache.load(tmp_path / "missing.json").entries == ()


def test_cache_rejects_corrupt_json(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text("{")
    with pytest.raises(CacheFormatError):
        IncrementalCache.load(path)


def test_cache_recovers_from_corrupt_json(tmp_path: Path):
    path = tmp_path / "cache.json"
    path.write_text("{")
    assert IncrementalCache.load(path, recover=True).entries == ()


def test_cache_rejects_version_mismatch():
    with pytest.raises(CacheFormatError):
        IncrementalCache.from_dict({"schema_version": 99, "entries": []})


def test_cache_rejects_non_list_entries():
    with pytest.raises(CacheFormatError):
        IncrementalCache.from_dict({"schema_version": 1, "entries": {}})


def test_cache_rejects_duplicate_keys():
    raw = {
        "schema_version": 1,
        "entries": [
            {"key": "x", "fingerprint": "a" * 64, "result": 1},
            {"key": "x", "fingerprint": "b" * 64, "result": 2},
        ],
    }
    with pytest.raises(CacheFormatError):
        IncrementalCache.from_dict(raw)


def test_cache_atomic_save_leaves_no_temp_file(tmp_path: Path):
    path = tmp_path / "cache.json"
    IncrementalCache().save(path)
    assert path.exists()
    assert not (tmp_path / "cache.json.tmp").exists()


def test_cache_hit_rate():
    cache = IncrementalCache([CacheEntry("x", "a" * 64, 1)])
    cache.get("x", "a" * 64)
    cache.get("y", "a" * 64)
    assert cache.statistics.requests == 2
    assert cache.statistics.hit_rate == 0.5


def test_cache_is_safe_for_parallel_reads():
    cache = IncrementalCache([CacheEntry("x", "a" * 64, 42)])
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: cache.get("x", "a" * 64), range(100)))
    assert values == [42] * 100
    assert cache.statistics.hits == 100


def test_compare_detects_added_modified_removed_unchanged():
    engine = IncrementalAnalysisEngine()
    result = engine.compare(
        [fp("old", "a"), fp("mod", "a"), fp("same", "c")],
        [fp("new", "b"), fp("mod", "b"), fp("same", "c")],
    )
    assert result.added == (Path("new"),)
    assert result.modified == (Path("mod"),)
    assert result.removed == (Path("old"),)
    assert result.unchanged == (Path("same"),)


def test_compare_propagates_dependencies():
    result = IncrementalAnalysisEngine().compare(
        [fp("a"), fp("b"), fp("c")],
        [fp("a", "b"), fp("b"), fp("c")],
        {Path("b"): [Path("a")], Path("c"): [Path("b")]},
    )
    assert result.invalidated == (Path("b"), Path("c"))
    assert result.dirty == (Path("a"), Path("b"), Path("c"))


def test_compare_noop():
    result = IncrementalAnalysisEngine().compare([fp("a")], [fp("a")])
    assert result.is_noop


def test_run_analyzes_new_files():
    calls = []
    run = IncrementalAnalysisEngine().run([fp("a")], lambda p: calls.append(p) or p.name)
    assert run.analyzed == (Path("a"),)
    assert run.reused == ()
    assert run.result_map()[Path("a")] == "a"


def test_run_reuses_cached_unchanged_file():
    cache = IncrementalCache([CacheEntry("a", "a" * 64, "cached")])
    run = IncrementalAnalysisEngine(cache).run([fp("a")], lambda _: "new", previous=[fp("a")])
    assert run.analyzed == ()
    assert run.reused == (Path("a"),)
    assert run.result_map()[Path("a")] == "cached"


def test_run_reanalyzes_changed_file():
    cache = IncrementalCache([CacheEntry("a", "a" * 64, "old")])
    run = IncrementalAnalysisEngine(cache).run([fp("a", "b")], lambda _: "new", previous=[fp("a")])
    assert run.analyzed == (Path("a"),)
    assert run.result_map()[Path("a")] == "new"


def test_run_reanalyzes_transitive_dependents():
    cache = IncrementalCache([
        CacheEntry("a", "a" * 64, "old-a"),
        CacheEntry("b", "a" * 64, "old-b", ("a",)),
    ])
    run = IncrementalAnalysisEngine(cache).run(
        [fp("a", "b"), fp("b")], lambda p: "new-" + p.name,
        previous=[fp("a"), fp("b")], dependencies={Path("b"): [Path("a")]},
    )
    assert run.analyzed == (Path("a"), Path("b"))


def test_run_removes_deleted_file_from_cache():
    cache = IncrementalCache([CacheEntry("gone", "a" * 64, 1), CacheEntry("stay", "a" * 64, 2)])
    IncrementalAnalysisEngine(cache).run([fp("stay")], lambda _: 2, previous=[fp("gone"), fp("stay")])
    assert [x.key for x in cache.entries] == ["stay"]


def test_run_full_rebuild_ignores_cache():
    cache = IncrementalCache([CacheEntry("a", "a" * 64, "old")])
    run = IncrementalAnalysisEngine(cache).run([fp("a")], lambda _: "new", previous=[fp("a")], full_rebuild=True)
    assert run.analyzed == (Path("a"),)
    assert run.result_map()[Path("a")] == "new"


def test_run_results_are_path_sorted():
    run = IncrementalAnalysisEngine().run([fp("z"), fp("A")], lambda p: p.name)
    assert [p for p, _ in run.results] == [Path("A"), Path("z")]


def test_run_records_cache_dependencies():
    cache = IncrementalCache()
    IncrementalAnalysisEngine(cache).run(
        [fp("a"), fp("b")], lambda p: p.name,
        dependencies={Path("b"): [Path("a")]},
    )
    assert next(x for x in cache.entries if x.key == "b").dependencies == ("a",)


@pytest.mark.parametrize("count", [0, 1, 2, 5, 10, 25])
def test_cache_round_trip_for_various_sizes(tmp_path: Path, count: int):
    cache = IncrementalCache(CacheEntry(f"k{i}", f"{i % 10}" * 64, i) for i in range(count))
    path = tmp_path / f"cache-{count}.json"
    cache.save(path)
    assert IncrementalCache.load(path).entries == cache.entries


@pytest.mark.parametrize("operator", ["added", "modified", "removed", "unchanged", "invalidated"])
def test_change_summary_collections_are_tuples(operator: str):
    result = IncrementalAnalysisEngine().compare([], [])
    assert isinstance(getattr(result, operator), tuple)


def test_saved_json_has_expected_schema(tmp_path: Path):
    path = tmp_path / "cache.json"
    IncrementalCache([CacheEntry("x", "a" * 64, 1)]).save(path)
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 1
    assert raw["entries"][0]["key"] == "x"
