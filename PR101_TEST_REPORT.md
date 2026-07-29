# PR101 Test Report

Date: 2026-07-29

## Baseline

PR100 commit `a072bf9`: **3286 passed in 6.85s**.

## Focused suite

```text
python -m pytest tests/test_atlas_type_table.py tests/test_atlas_variable_type_inference.py tests/test_atlas_semantic_document.py tests/test_atlas_type_serialization.py tests/test_atlas_pass_manager.py tests/test_pr101_semantic_table_builders.py -p no:cacheprovider --basetemp=.pytest_pr101_focused -q
```

Result: **86 passed in 0.26s**.

## Benchmark

The direct file invocation failed before measurement because its import root
was `benchmarks/`. The supported module invocation completed:

```text
python -m benchmarks.benchmark_semantic_tables --entries 5000 --repeats 3
```

Result: legacy 1.707386s, builder 0.004469s, **382.01× speedup**.

## Full suite

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr101_full -q
```

Result: **3294 passed in 6.63s**.

## Clean replay

The candidate patch applied cleanly to PR100 commit `a072bf9`;
`git apply --check` and `git diff --check` succeeded.

Full result: **3294 passed in 8.04s**.

Replay benchmark: legacy 1.689877s, builder 0.004344s,
**389.03× speedup**.
