# PR131 Test Report

## Focused development validation

- Initial PR131 model, pipeline, and explanation tests: **22 passed** in 0.51s.
- Expanded state, call, CFG, cache, serialization, and bound tests:
  **27 passed** in 0.48s.
- Reachability/CFG/call/framework compatibility: **214 passed** in 0.77s.
- PR124 and PR127–PR130 compatibility: **55 passed** in 0.93s.
- Post-refactor PR114/PR130/PR131 validation: **38 passed** in 0.55s.
- Metadata/persistence pipeline validation: **39 passed** in 0.66s.
- Final focused and adjacent compatibility set: **269 passed** in 1.39s.

One attempted compatibility command referenced nonexistent
`tests/test_pr121_ai_context_integration.py`. Pytest executed zero tests for that
command, so it is not counted as a passing result. The corrected set used
`tests/test_ai_context_pipeline_integration.py`.

## Complete suite

The complete Atlas suite was executed exactly once after the final production and
test changes:

**3484 passed, 1 skipped in 10.74s.**

```text
python -m pytest -q --basetemp=<external-pr131-temp> -p no:cacheprovider
```

The command exited with code 0 and emitted no warnings. Disabling pytest's cache
provider avoided the repository `.pytest_cache` access issue without altering test
selection.

## Clean-checkout patch replay

`PR131.patch` was applied to a detached clean checkout of baseline commit
`b42138b`. The replay compatibility set completed successfully:

**62 passed in 1.20s.**

```text
python -m pytest -q -p no:cacheprovider --basetemp=<external-replay-temp> \
  tests/test_pr131_reachability.py \
  tests/test_pr114_explain_engine.py \
  tests/test_pr129_knowledge_graph.py \
  tests/test_pr130_design_patterns.py \
  tests/test_ai_context_pipeline_integration.py \
  tests/test_pr111_semantic_snapshot.py
```

An earlier replay attempt executed zero tests because the repository `.venv`
launcher referenced a removed Python 3.12 interpreter. The successful command used
the available standalone workspace Python runtime and is the result reported above.

## JUnit acceptance

The final normal-pipeline command completed in 16.7 seconds:

```text
python -m moughorai.atlas_cli analyze \
  C:\Users\MoughorOC\Documents\AITest\JUnit\junit-team --no-recover
```

**JUnit workspace validated successfully: 41 discovered projects, including the root
`junit-team` aggregator.** All projects succeeded.

Final reachability results:

- 13,036 symbol findings;
- 4 reachable and 13,032 unknown;
- 0 likely-dead or unreachable candidates;
- 2 structured roots;
- 45 deduplicated evidence records;
- call evidence unavailable for all 41 projects;
- overall coverage `partial` (5 partial projects and 36 unavailable projects);
- 89 deterministic finding groups;
- exact grouped serialization round trip passed.

The reachability section is 471,357 compact JSON bytes. The final semantic snapshot is
17,277,988 bytes, an increase of 1,539,388 bytes (**9.78%**) over the documented PR130
snapshot baseline of 15,738,600 bytes. Cumulative growth over the PR129 baseline is
12.06%.

This acceptance result is deliberately conservative. The lack of production call
evidence produced no dead-code claims.
