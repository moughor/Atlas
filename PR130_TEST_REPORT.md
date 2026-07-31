# PR130 Test Report

## Targeted development validation

- Initial PR130 focused suite: **8 passed** in 0.42s.
- PR128, PR129, semantic snapshot, and AI context pipeline compatibility:
  **31 passed** in 0.72s.
- Final expanded PR130 focused suite: **10 passed** in 0.36s.

One attempted compatibility command referenced the nonexistent file
`tests/test_ai_context_persistence.py`; pytest executed zero tests for that command,
so it is not counted as a passing result. The corrected command used
`tests/test_ai_context_pipeline_integration.py`.

The repository `.venv` launcher referenced an unavailable system Python. Tests were
therefore executed with the Codex workspace Python 3.12 runtime after installing the
project's declared dependencies and pytest into that isolated runtime.

## Complete suite

The complete suite was executed exactly once after focused validation:

**3461 passed, 1 skipped** in 9.07s.

Command:

```text
python -m pytest -q --basetemp=.pytest_pr130_full -p no:cacheprovider
```

Disabling pytest's cache provider avoided the known denied-write warning for the
repository `.pytest_cache`. The run emitted no warnings.

## Repository explanation acceptance fix

Inspection of the accepted JUnit snapshot confirmed the additive section at
`snapshot.semantic_context.design_patterns`, with schema version `1` and producer
version `atlas-pr130/1`. The normal production pipeline produced 68 findings: 58
Strategy and 10 Builder.

The repository explanation path had omitted this section while the targeted-symbol
path already consumed the complete semantic context. The repository path now includes
a compact, source-free projection. Validation after this production-code adjustment:

- PR114 explanation and PR130 pattern tests: **16 passed** in 0.48s;
- adjacent PR109, PR120, PR127, PR128, and PR129 tests: **26 passed** in 0.63s;
- captured complete suite: **3462 passed, 1 skipped** in 9.00s.

An earlier post-adjustment complete run finished, but its final output was truncated
by the execution transport. It is not claimed as a passing result. The captured run
above was performed to obtain an auditable exact result.

## JUnit production validation

The accepted JUnit workspace was analyzed with the PR130 normal production path:

**JUnit workspace validated successfully: 41 discovered projects, including the root
`junit-team` aggregator.**

The command completed with `succeeded: yes` in 12 seconds. The resulting snapshot
contained:

- 68 pattern findings: 58 Strategy and 10 Builder;
- 150 deduplicated evidence records;
- 11 pattern capability entries;
- 216,735 bytes in the compact `design_patterns` section;
- 15,738,600 total snapshot bytes.

Against the documented PR129 JUnit baseline of 15,418,187 bytes, total snapshot growth
is 320,413 bytes (**2.08%**), below the PR130 planning target of 8%. The pattern
section is 1.38% of the resulting snapshot.

## Replay

The candidate patch applied cleanly to detached baseline `f848850`. The PR114,
PR130, PR128, PR129, snapshot, and AI context pipeline replay suite completed with
**47 passed** in 1.18s.

The final patch was regenerated after removing four documentation-only blank lines at
EOF and replayed again as described in `PR130_VERIFICATION.md`.
