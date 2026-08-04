# PR142 Verification Report

Status: **implemented and validated on 2026-08-04**.

## Roadmap compliance

The authoritative roadmap wording is:

> PR142 — Technical Debt Engine — Rank technical debt by engineering impact and
> reuse PR132 complexity and risk evidence.

The completed first slice is deliberately partial and cycle-only. A candidate must
be a PR137 dependency-cycle seam whose complete PR128 cycle was revalidated against
authoritative PR129 relationships. PR136 represented impact supplies ordinal rank;
compatible exact-subject PR132 risk is context and a tie-break only, and structured
complexity is shown only when PR132 actually has that signal. No composite score or
new analyzer was added. PR143 Architectural Drift remains excluded.

## Executed validation

All commands used Python 3.12.13 from the bundled workspace runtime.

| Validation | Exact result |
| --- | --- |
| Four focused PR142 test files | **43 passed in 2.68s** |
| Relevant PR141 suite | **51 passed in 1.35s** |
| PR127–PR141 historical compatibility matrix, 40 files | **664 passed in 54.06s** |
| Frozen public API fixture | **8 passed in 0.33s** |
| PR136 and PR137 focused compatibility | **105 passed in 7.83s** |
| Complete main-worktree suite | **4453 passed, 3 skipped in 84.08s** |
| `python -m compileall -q moughorai tests` | passed |
| Tracked `git diff --check` | passed |
| Alternate-index complete 16-file diff check | passed |

The three skips are the pre-existing Windows symlink-capability tests. No test was
weakened, deleted, or reclassified.

## Clean replay

An alternate index produced a 16-file candidate patch without staging the main
index. `git apply --check` and `git apply --index` succeeded in a detached worktree
at exact baseline:

`1923bebc8ddaa24867643715319cb2ab5031863c`

The first focused attempt produced 39 passes and four setup errors because pytest
could not access the ambient Windows pytest temp root. No product assertion failed.
The unchanged patch was rerun with an isolated writable `--basetemp`:

| Replay validation | Exact result |
| --- | --- |
| Focused PR142 | **43 passed in 2.74s** |
| Complete suite | **4453 passed, 3 skipped in 82.96s** |
| Compileall | passed |
| Replay staged diff check | passed |
| Replay nonignored untracked files | 0 |

The replay worktree, caches, basetemps, and alternate index were removed. The main
index remained unstaged. The external validation patch and report are not repository
deliverables and are outside the intended manifest.

## Determinism and source-free evidence

Focused and adversarial tests prove:

- canonical item IDs do not depend on impact, evidence order, request order, time,
  process, or temporary path;
- equivalent cycle observations collapse by directed seam before impact work;
- all evaluated advice IDs and exact equivalent, unevaluated, and output-omitted
  counts remain explicit;
- rank uses represented affected count, direct count, compatible exact-subject
  PR132 risk tie-break, then canonical item ID;
- unranked items ignore risk for ordering;
- confidence remains the conservative existing PR137 confidence;
- evidence closure, producer lineage, advice-set digest, impact fingerprint, risk
  subject, and complexity subject are revalidated by strict `from_dict()`;
- reordered equivalent inputs, JSON round trips, and human rendering are exact;
- snapshots and responses remain source-free and provider-free;
- PR142 neither writes snapshots nor creates persistence or cache state.

On the retained Maven snapshot, two independent canonical JSON invocations and two
human invocations were byte-identical. Ten same-service queries produced the same
canonical SHA-256:
`e4d8326a858d8088d59a2e68b88f810892b2e67140cff0340af1d626f262b147`.

## Official repository benchmarks

All successful runs used `--force --no-recover --workers 1 --format json`. Wall
times were affected by concurrent validation and are correctness-only observations.

| Repository | Pinned commit | Result | Observed wall time | Determinism and publication |
| --- | --- | ---: | ---: | --- |
| Apache Maven | `3e01a12e9eacd2b336f4db786d54e35647ce268c` | **92/92** | 32.0642s | Fresh snapshot raw bytes and all canonical hashes equal PR141; 0-byte growth |
| Quarkus | `bbc0853aef94c567bac2cc4a98d51c90fb423648` | **1442/1442** | 567.5052s | All canonical hashes and 359,125,800-byte size equal PR141 |
| Spring Framework | `eceebb3077dda9e1b19d73c0398ef022cd91f99c` | **29/29** | 124.2113s | Fresh snapshot raw bytes and all canonical hashes equal PR141; 0-byte growth |
| Elasticsearch | `273e03a8a7149170fac16761af3fbf522b52f9fe` | **545/545** | 808.7s | Fresh snapshot raw bytes and all canonical content equal PR141; 0-byte growth |
| IntelliJ Community | `6affce35cb2aad82747b36e886836c44e0188e46` | **118/119**, twice | 381.7569s / 381.8753s | Byte-identical run output; only documented root `idea` duplicate; no `latest.ass` published |

IntelliJ's only failure remained `DuplicateTypeError` for
`com.intellij.testFramework.TestDataFile` in the aggregated root `idea` project.
It was not hidden or reclassified. Both failed runs published history only, never a
semantic snapshot. Existing target `.atlas` state for every benchmark was preserved
or restored exactly; generated states were moved outside the Atlas repository.
Elasticsearch emitted one non-fatal Python `SyntaxWarning` for an invalid escape in
its own `tdvt_run.py` source; Atlas still reported zero internal exceptions.

## Compatibility and unsupported claims

PR142 preserves the frozen public API version 1.0 and changes no existing snapshot
schema or ordinary semantic-context key. PR127–PR141 services, PR138 security,
PR139 chat/ask, PR140 change review, and PR141 evolution remain compatible.

The implementation intentionally does not claim:

- complete repository technical-debt coverage;
- complexity when PR132 lacks structured complexity evidence;
- runtime reachability, external consumers, API breakage, exploitability, ownership,
  effort, urgency, business priority, remediation safety, or developer intent;
- debt growth, introduction time, author, causality, or architecture drift;
- that zero returned observations means no technical debt.

PR131 reachability debt, clone analysis, production complexity, test-density debt,
security-debt classification, evolution timelines, persistence, policy gates, and
automatic remediation remain intentionally deferred. The next roadmap item is
**PR143 — Architectural Drift — Detect divergence from intended architecture**.
