# PR104 Test Report

Date: 2026-07-29

Baseline PR103 (`b409037`): **3310 passed in 6.82s**.

Focused indexing, workspace, and benchmark tests:

```text
python -m pytest tests/test_pr20_persistent_project_index.py
tests/test_pr67_workspace_model.py
tests/test_pr104_large_workspace_benchmark.py -p no:cacheprovider
--basetemp=.pytest_pr104_focused -q
```

Result: **60 passed in 0.45s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr104_full -q
```

Result: **3316 passed in 7.46s**.

Default large-workspace benchmark:

```text
python -m benchmarks.benchmark_large_workspace
```

Result: **23,000 files indexed across 23 projects**. Measured production-path
time was **22.138827s** (**1038.9 files/s**) with **16.77 MiB** peak traced
memory. Corpus setup took **8.754968s**. Content checksum:
`37f7a59c467e4b0730361c7550bdd9e93d4ddd4e93cc569fad8b2384bdaaeba4`.

Clean replay from PR103 commit `b409037` passed `git apply --check` and
`git diff --check`.

Result: **3316 passed in 8.19s**.
