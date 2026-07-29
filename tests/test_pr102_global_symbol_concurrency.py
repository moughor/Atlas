from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from moughorai.global_symbols import (
    DuplicateSymbolError,
    GlobalSymbol,
    GlobalSymbolDatabase,
    GlobalSymbolKind,
    GlobalSymbolSnapshot,
)


def symbol(index: int, *, source: Path | None = None, name: str | None = None) -> GlobalSymbol:
    simple = name or f"Type{index}"
    return GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        simple,
        f"example.package{index}.{simple}",
        source=source,
    )


def test_atomic_batch_rejects_duplicate_without_partial_write() -> None:
    database = GlobalSymbolDatabase((symbol(0),))
    with pytest.raises(DuplicateSymbolError):
        database.add_many((symbol(1), symbol(0), symbol(2)))
    assert [item.qualified_name for item in database.symbols] == [symbol(0).qualified_name]
    assert database.version == 1


def test_concurrent_unique_writers_preserve_every_index() -> None:
    database = GlobalSymbolDatabase()
    workers = 8
    per_worker = 125
    barrier = Barrier(workers)

    def populate(worker: int) -> None:
        barrier.wait()
        start = worker * per_worker
        database.add_many(
            symbol(index, source=Path(f"source{worker}.java"))
            for index in range(start, start + per_worker)
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        tuple(executor.map(populate, range(workers)))

    assert len(database) == workers * per_worker
    assert database.version == workers
    database.validate()
    for worker in range(workers):
        assert len(database.by_source(Path(f"source{worker}.java"))) == per_worker


def test_duplicate_race_has_one_winner_and_no_corruption() -> None:
    database = GlobalSymbolDatabase()
    barrier = Barrier(12)

    def compete(_: int) -> str:
        barrier.wait()
        try:
            database.add(symbol(1))
            return "added"
        except DuplicateSymbolError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=12) as executor:
        outcomes = tuple(executor.map(compete, range(12)))

    assert outcomes.count("added") == 1
    assert outcomes.count("duplicate") == 11
    assert len(database) == 1
    database.validate()


def test_readers_observe_consistent_snapshots_during_writes() -> None:
    database = GlobalSymbolDatabase()
    barrier = Barrier(5)

    def writer(worker: int) -> None:
        barrier.wait()
        for offset in range(100):
            database.add(symbol(worker * 100 + offset, name="Shared"))

    def reader() -> tuple[int, ...]:
        barrier.wait()
        observed = []
        for _ in range(300):
            snapshot = database.snapshot()
            assert tuple(sorted(snapshot.symbols, key=lambda item: (item.qualified_name, item.kind.value))) == snapshot.symbols
            assert len(snapshot.find_simple("Shared")) == len(snapshot)
            observed.append(snapshot.version)
        return tuple(observed)

    with ThreadPoolExecutor(max_workers=5) as executor:
        writes = [executor.submit(writer, worker) for worker in range(4)]
        reads = executor.submit(reader)
        for future in writes:
            future.result()
        observed = reads.result()

    assert observed == tuple(sorted(observed))
    assert len(database) == 400
    database.validate()


def test_snapshot_is_detached_from_later_mutations() -> None:
    first = symbol(1, source=Path("One.java"))
    database = GlobalSymbolDatabase((first,))
    snapshot = database.snapshot()
    assert isinstance(snapshot, GlobalSymbolSnapshot)
    database.add(symbol(2))
    database.remove_source(Path("One.java"))
    assert snapshot.version == 1
    assert snapshot.symbols == (first,)
    assert snapshot.get(first.id) is first
    assert len(database) == 1


def test_concurrent_source_removal_and_reads_are_safe() -> None:
    source = Path("Generated.java")
    database = GlobalSymbolDatabase(symbol(index, source=source) for index in range(300))
    barrier = Barrier(2)

    def remove() -> int:
        barrier.wait()
        return database.remove_source(source)

    def read() -> None:
        barrier.wait()
        for _ in range(500):
            current = database.by_source(source)
            assert len(current) in {0, 300}
            database.symbols

    with ThreadPoolExecutor(max_workers=2) as executor:
        removed = executor.submit(remove)
        reader = executor.submit(read)
        assert removed.result() == 300
        reader.result()

    assert database.symbols == ()
    database.validate()


def test_empty_batch_does_not_advance_version() -> None:
    database = GlobalSymbolDatabase()
    assert database.add_many(()) == 0
    assert database.version == 0
