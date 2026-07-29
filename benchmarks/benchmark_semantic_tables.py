"""Compare repeated immutable updates with PR101 bulk builders."""

from __future__ import annotations

import argparse
import json
from time import perf_counter

from moughorai.semantic import PrimitiveType, SymbolTable, TypeTable, VariableSymbol


def benchmark(entries: int, repeats: int = 3) -> dict[str, float | int]:
    if entries < 1 or repeats < 1:
        raise ValueError("entries and repeats must be positive")
    semantic_type = PrimitiveType("int")
    legacy_samples: list[float] = []
    builder_samples: list[float] = []
    for _ in range(repeats):
        started = perf_counter()
        types = TypeTable()
        symbols = SymbolTable()
        for index in range(entries):
            types = types.with_type(index, semantic_type)
            symbols = symbols.with_symbol(VariableSymbol(index, f"value{index}", semantic_type))
        legacy_samples.append(perf_counter() - started)

        started = perf_counter()
        type_builder = TypeTable().to_builder()
        symbol_builder = SymbolTable().to_builder()
        for index in range(entries):
            type_builder.set(index, semantic_type)
            symbol_builder.add(VariableSymbol(index, f"value{index}", semantic_type))
        built_types = type_builder.build()
        built_symbols = symbol_builder.build()
        builder_samples.append(perf_counter() - started)
        assert len(types) == len(built_types) == entries
        assert len(symbols) == len(built_symbols) == entries

    legacy = min(legacy_samples)
    builder = min(builder_samples)
    return {
        "entries": entries,
        "repeats": repeats,
        "legacy_seconds": round(legacy, 6),
        "builder_seconds": round(builder, 6),
        "speedup": round(legacy / builder, 2) if builder else float("inf"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=3)
    arguments = parser.parse_args()
    print(json.dumps(benchmark(arguments.entries, arguments.repeats), sort_keys=True))


if __name__ == "__main__":
    main()
