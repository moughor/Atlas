# PR56 — Deterministic Parallel Incremental Scheduler

PR56 adds dependency-aware parallel execution to the PR55 incremental analysis engine without changing the existing sequential API.

## Capabilities

- deterministic topological execution waves
- bounded `ThreadPoolExecutor` worker pools
- stable result, failure, reuse, and cancellation ordering
- cache reuse for unchanged files
- cache writes only for successful analyses
- dependency-cycle detection before execution
- failure isolation for independent branches
- automatic cancellation of dependents whose prerequisites failed
- optional fail-fast behavior
- full-rebuild compatibility
- explicit run reports containing waves, results, failures, and cancellations

## Public API

```python
from moughorai.incremental_analysis import ParallelIncrementalScheduler

scheduler = ParallelIncrementalScheduler(max_workers=4)
run = scheduler.run(
    fingerprints,
    analyzer,
    previous=previous_fingerprints,
    dependencies=dependency_map,
)
```

The dependency map follows the existing convention: each key is a dependent file and each value contains the files it requires.

## Determinism

Work inside a wave may finish in any order, but all externally visible collections are sorted by normalized path. Repeated executions therefore produce the same report ordering regardless of worker count or completion timing.

## Failure semantics

Analyzer exceptions are captured as `ExecutionFailure` values. Successful independent work is retained and cached. Files that depend on a failed or blocked file are reported as cancelled. With `fail_fast=True`, no later wave is started after a failure, while already submitted work in the current wave is allowed to finish safely.

## Compatibility

`IncrementalAnalysisEngine.run()` remains unchanged. PR56 is opt-in through `ParallelIncrementalScheduler` and uses the same fingerprints, cache, change comparison, and dependency invalidation behavior introduced by PR55.
