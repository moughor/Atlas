# PR134 Verification Report

## Roadmap compliance

PR134 implements the roadmap-defined Explain Anything capability by resolving a
canonical subject and composing a bounded structured explanation from existing Atlas
facts. It does not introduce another graph, repository report, semantic analyzer,
evidence model, confidence model, persistent cache, or source scan. PR129 remains the
canonical repository graph, and specialized analyzers remain authoritative.

PR133 is optional enrichment. Repository, project, module/package, type/class, method,
dependency, framework, build-system/target, generic symbol, and canonical relationship
requests operate from compatible snapshots and the PR129 graph. PR135 and later
roadmap capabilities are not included.

## Verification matrix

| Requirement | Verification intent |
| --- | --- |
| Canonical resolution | Exact ID, scoped qualified name, unique normalized name, and deterministic ambiguity candidates |
| Subject coverage | Every PR134 subject kind, including explicit relationship and honest unavailable build-target behavior |
| Evidence | Every available/partial fact cites an explanation-owned, traceable evidence record |
| Confidence | Compatible upstream confidence is preserved; no LLM or arbitrary score changes it |
| Partial data | Missing producer data remains unavailable, partial, insufficient, ambiguous, or not found |
| Bounds | High-degree/cyclic graphs, whole-fact token selection, exact omission counts, and mandatory-envelope failure |
| Determinism | Reordered inputs, repeated requests, canonical JSON hashes, and exact serialization round trips |
| Source-free safety | No raw source, absolute path, URL-encoded absolute path, or whole ASS enters structured output or prompts |
| Compatibility | Default PR133 output, public request/result prefixes, old snapshots, memory, and existing explain behavior |
| LLM separation | Provider sees only selected structured facts; deterministic unsupported states bypass provider inference |

## Tests executed

Focused development and compatibility tests were executed with isolated pytest state:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr134_final_focused tests\test_pr114_explain_engine.py tests\test_pr129_knowledge_graph.py tests\test_pr130_design_patterns.py tests\test_pr131_reachability.py tests\test_pr132_risk_hotspots.py tests\test_pr133_repository_report.py tests\test_pr134_subject_resolution.py tests\test_pr134_structured_explanation.py tests\test_pr134_explain_integration.py
```

Result: `176 passed in 3.78s`.

An initial complete-suite run after the first production freeze reported:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr134_full
```

Result: `3637 passed, 1 skipped in 14.75s`.
Maintainer review then identified additional evidence-binding and source-free safety
hardening. The focused result above includes those changes. A final complete-suite
run after that hardening used:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr134_full_final
```

Final result: `3643 passed, 1 skipped in 14.86s`. This final result is authoritative.
The single skip is the existing platform-dependent file-symlink test, which reports
that file symlinks are unavailable on this Windows environment.

## Performance validation

`benchmarks/benchmark_pr134_explain_anything.py` separates resolver index construction
from warm indexed lookup and bounded explanation/context selection. It supports
deterministic synthetic 10K, 100K, and 1M-node inputs and checksum-verified ASS replay.
It records median/p95 timing, graph size, token counts, result hashes, snapshot bytes,
and process peak working set. PR134 explanations and indexes are ephemeral, so the
expected persisted snapshot increase is zero bytes.

The performance targets are:

- interactive lookup p95 below 250 ms at 100K indexed nodes;
- interactive lookup p95 below 1 second at 1M indexed nodes;
- bounded AI context selection p95 below 500 ms;
- PR134 snapshot growth at or below 2% (expected 0% because nothing is stored).

The benchmark was exercised during development after the resolver and selector were
added. These are implementation-worktree measurements, not pass/fail thresholds:

| Input | Repeats | Graph | Resolver index p95 | Warm lookup p95/subject | Bounded incident p95 | Selection p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Synthetic 10K | 2 | 10,000 nodes / 19,997 edges | 0.080738 s | 0.000070014 s | 0.001731 s / 9,999 incident | 0.021303 s |
| Synthetic 100K | 2 | 100,000 nodes / 199,997 edges | 1.359846 s | 0.000071452 s | 0.018109 s / 99,999 incident | 0.022479 s |
| Synthetic 1M | 2 | 1,000,000 nodes / 1,999,997 edges | 16.386452 s | 0.000071601 s | 0.304590 s / 999,999 incident | 0.021622 s |
| Apache Maven snapshot replay | 2 | 22,427 nodes / 25,254 edges | 0.545226 s | 0.000097592 s | 0.000036 s / 93 incident | 0.016439 s |
| Quarkus snapshot replay | 2 | 149,048 nodes / 167,850 edges | 4.154978 s | 0.000102148 s | 0.000300 s / 1,443 incident | 0.016304 s |

Every repeated resolution and selected-context hash was stable, and every selected
context passed exact serialization round-trip verification. Selection retained 21 of
96 facts under 7,000 tokens for the synthetic cases and 20 of 32 for the snapshot
replays. The 1M run used 3,415,515,136
bytes peak RSS; its warm lookup and bounded selection remained within their targets,
while cold graph construction, digesting, and index construction are explicitly not
interactive-query timings. The Maven and Quarkus replays used 100 lookups per repeat
and a 32-fact fixture. Both input snapshot checksums and snapshot IDs were verified.

The exact commands were:

```text
python -B -m benchmarks.benchmark_pr134_explain_anything --nodes 10000 100000 --repeats 2 --lookups 1000 --facts 96 --token-budget 7000
python -B -m benchmarks.benchmark_pr134_explain_anything --nodes 1000000 --repeats 2 --lookups 1000 --facts 96 --token-budget 7000
python -B -m benchmarks.benchmark_pr134_explain_anything C:\AITest\maven-master\maven-master\.atlas\ass\latest.ass C:\AITest\quarkus-main\quarkus-main\.atlas\ass\latest.ass --repeats 2 --lookups 100 --facts 32 --token-budget 7000
```

The Maven and Quarkus results are checksum-verified snapshot replays, not fresh
repository analyses. PR134 does not change workspace analysis or snapshot publication.

## Compatibility validation

Delivery verification must establish that:

- default `atlas ai explain` repository Markdown stays on the accepted deterministic
  PR133 path and does not call a provider;
- targeted narrative input contains the bounded `structured_explanation` projection,
  not the complete semantic snapshot;
- `atlas ai explain --json` is provider-free and byte deterministic;
- old snapshots without PR130 through PR133 findings remain explainable with explicit
  capability limitations;
- malformed, future-schema, duplicate-ID, dangling-edge, and ambiguous inputs fail or
  degrade explicitly;
- no snapshot schema or persisted semantic-context field is added by PR134.

## Real-repository validation

The current successful Apache Maven artifact contains 92 discovered projects and a
31,153,709-byte snapshot. Its repeated repository explanation JSON was byte-identical
with SHA-256 `7053c41e880b691370b95bd4a84f98fb6c226ec7261b6c69b4328f90985cca45`;
the two executions took 1.518205 s and 1.507831 s and selected 12 facts / 12 evidence
records at 6,369 estimated tokens. The accepted default PR133 Markdown path was also
byte-identical across two executions with SHA-256
`93a06637a0822557449a21911e91138acc7b58cef0b1e4bcdb619c769a07c6b4`.
The same capture executed from an unmodified detached PR133 baseline produced exactly
the same bytes, hash, and 10,924-character output.

The Quarkus artifact contains 1,442 discovered projects and a 336,960,228-byte
snapshot. Its repeated repository explanation JSON was byte-identical with SHA-256
`57ec9737c1e4a2306ccd61dcd6733cf0090397dfa8fe5a3e831a36049bf4604d`;
the two final executions took 9.878308 s and 9.778435 s and selected 13 facts / 13
evidence records at 6,727 estimated tokens. Snapshot-backed AI loading no longer
rediscovers the workspace, and grouped optional findings remain compact until the
requested subject needs them.

An initial default-report attempt using the sandboxed Maven directory as the
conversation-memory root did not execute successfully and reported
`OperationalError: attempt to write a readonly database`. Repeating it with the
writable Atlas worktree as the memory root and the same explicit Maven snapshot
succeeded as recorded above. This is an inherited writable-memory requirement, not a
snapshot replay or PR134 determinism failure.

## Deliberate limitations and deferred work

- PR134 explains facts already established by Atlas; it does not answer arbitrary
  natural-language intent through semantic search.
- Absent canonical call or composition evidence remains unavailable and cannot prove a
  negative relationship.
- Real build-target explanations require a compatible authoritative producer; build
  system metadata is not promoted to a task or target.
- Optional provider prose is not part of deterministic validation and cannot modify
  evidence, confidence, availability, or citations.
- PR130 v1 has no standalone canonical graph digest. Its current-graph binding rests
  on checksum-verified snapshot co-publication and is disclosed as an inherited
  limitation.
- PR131 root and relation evidence is accepted only when the report's persisted path
  binds it to the requested subject and scope; unrelated valid records are rejected.
- Line-level source explanation, persistent indexes/caches, impact prediction,
  refactoring, security analysis, and interactive chat remain later-roadmap work.

No PR135 or later functionality is included.
