# PR137 Verification

## Scope and baseline

The official roadmap defines PR137 as **Refactoring Advisor**:

> Suggest extractions, simplifications, dependency cleanup, package moves, and
> modularization with rationale and estimated impact.

The roadmap does not contain M2.0 or M2.1 entries. Those names belong to completed
stability work in Git and `docs/stability`. With local PR136 commit
`cef8d52b2a39ec019e3a6cd34e34450d36c85a55` as the implementation baseline, PR137
is the next numbered roadmap item. At validation time `origin/main` remained at
PR135 commit `cddfefc09ee7ae2ceeb908f167568797c02041d0`; that integration discrepancy
must be resolved before a later push.

The complete roadmap item is larger than the authoritative evidence currently
published by Atlas. This implementation is therefore the smallest independently
useful first slice: deterministic review advice for PR128 dependency-cycle seams
whose complete directed cycle is revalidated against authoritative PR129 project
dependency or cross-project import evidence. It does not claim that the complete
PR137 roadmap item is finished.

The pre-change suite result was:

```text
4071 passed, 3 skipped, 1 warning in 36.86s
```

The warning concerned an unwritable optional `.pytest_cache`; accepted validation
runs disabled that cache provider.

## Implementation verification

The implementation reuses:

- PR128 dependency-cycle observations as candidate input only;
- the PR129 canonical `KnowledgeGraph` and relationship evidence;
- PR130 evidence, confidence, deterministic ID, and lineage contracts;
- PR134 canonical subject resolution and ambiguity handling;
- PR136 impact prediction as lazy, optional context after a candidate exists;
- M2 measurement scopes and existing snapshot/CLI/public-facade conventions.

It does not add a graph, cycle detector, resolver, confidence model, evidence model,
impact engine, semantic pass, cache, persistence payload, concurrent executor, LLM
path, or patch generator. Unsupported families produce deterministic
`unavailable` or `insufficient` capabilities.

The only intentional change to an earlier implementation is the extraction of the
PR136 canonical-edge authority predicate into
`knowledge_graph.evidence.has_authoritative_edge_evidence()`. The shared predicate
validates each evidence token before authority matching. This prevents an unsafe
token from borrowing safety from a different token; the prior scoring and traversal
policies are unchanged.

## Tests

Final focused command:

```text
python -m pytest -q -p no:cacheprovider \
  --basetemp=.pytest_pr137_targeted_final \
  tests/test_pr137_refactoring_advisor.py \
  tests/test_pr137_refactoring_adversarial.py \
  tests/test_pr137_cli.py \
  tests/test_pr136_impact_prediction_adversarial.py \
  tests/test_pr105_public_api.py
```

Result:

```text
67 passed in 1.73s
```

Final complete-suite command:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr137_final
```

Result:

```text
4111 passed, 3 skipped in 31.51s
```

The three skips are the existing Windows symlink-capability checks. Pytest reported
no failure or warning in the final run.

Focused coverage includes normal PR128 producer data, direct and transitive cycle
evidence, directed seam identity, reordered input, exact serialization round trips,
source-free contracts, malformed and stale snapshots, ambiguous and out-of-scope
subjects, missing coverage, non-authoritative evidence, bounded work, CLI human/JSON
output, M2 opt-in profiling, public-facade compatibility, and the PR136 mixed-token
authority regression.

## Clean replay

The complete change was exported through a temporary Git index and applied with
`git apply --check` to a detached checkout of PR136. The replay succeeded. A single
blank line at the end of the new package `__init__.py` was found by the clean
checkout's staged whitespace validation and removed before final validation.

The clean benchmark candidate was committed only in the detached validation
worktree as `065d641df81371a89ecbf21e1a95ce134dd071f4`. The user's main branch was not
committed or pushed.

## Fresh repository validation

All successful repositories were analyzed from clean, detached temporary worktrees
with one worker, forced analysis, recovery disabled, and three repeats. Exact
artifact determinism was required across repeats.

| Repository | Result | Durations (ms) | Median (ms) | Snapshot bytes | Determinism |
| --- | ---: | --- | ---: | ---: | --- |
| Apache Maven `3e01a12e` | 92/92 | 37,766; 26,669; 26,499 | 26,669 | 33,712,720 | exact; golden verified |
| Quarkus `bbc0853a` | 1442/1442 | 385,689; 510,797; 522,564 | 510,797 | 358,297,696 | exact; golden verified |
| Spring Framework `eceebb30` | 29/29 | 99,124; 88,503; 86,975 | 88,503 | 146,017,372 | exact |
| Elasticsearch `273e03a8` | 545/545 | 596,555; 606,604; 476,107 | 596,555 | 544,065,280 | exact |

Maven and Quarkus satisfy the registered canonical baseline protocol and external
golden verification. The Spring and Elasticsearch diagnostic manifests are not
promotion-eligible because the invocations intentionally omitted an unverified
branch/tag field; their commits, origins, counts, clean worktrees, analysis success,
and exact three-run determinism were verified.

The larger captures overlapped in wall-clock time. Their durations are observations
of this machine, not an isolated performance comparison or a PR137 speed claim.

### IntelliJ Community

IntelliJ was analyzed twice from identical clean temporary state at commit
`6affce35cb2aad82747b36e886836c44e0188e46`:

| Run | Projects | Succeeded | Failed | Wall time |
| --- | ---: | ---: | ---: | ---: |
| 1 | 119 | 118 | 1 | 288.774 s |
| 2 | 119 | 118 | 1 | 337.988 s |

Both runs preserved the documented architectural limitation: only project `idea`
failed, with the same `DuplicateTypeError` for the two legitimate module-scoped
`com.intellij.testFramework.TestDataFile` definitions. The project order, statuses,
failure, stdout, and stderr were identical. The deterministic report projection
SHA-256 was
`a16e28842df3316bf6aa939c87f4c1680e16cf17dbedd358f57ff8da673bc522`;
the analysis-order SHA-256 remained
`572e84e65d0edd96bbfabbe7caf8d9c3d22d57c0d823e3528d9f784747ac0520`.
No successful snapshot was published, as required.

## Controlled pre-PR137 comparison

PR136 `cef8d52` and the clean PR137 candidate were each run three times against the
same Maven commit, at the same temporary checkout path, with the same worker and
state-reset protocol:

| Version | Durations (ms) | Median (ms) |
| --- | --- | ---: |
| PR136 baseline | 25,231; 24,984; 25,088 | 25,088 |
| PR137 candidate | 37,766; 26,669; 26,499 | 26,669 |

The observed median delta is +1,581 ms (+6.302%). The candidate mean is distorted by
its first-run outlier and the cohorts ran under different concurrent system load, so
this is not evidence that PR137 caused an analysis regression.

The semantic result is stronger and exact: both versions produced the same
33,712,720-byte snapshot, snapshot ID, raw snapshot SHA-256
`2f37c4fb3ef25eee7935ad48382b03c0b2c6d7d6403374bee674f796bb402706`,
analysis and workspace order, deterministic ordering, analysis report, semantic
payload, portable projection, repository report, provider-free explanation,
knowledge graph, and risk hashes. Snapshot growth is therefore **0 bytes (0%)**.

## PR137 request-path measurements

The four available accepted snapshots were replayed three times with:

```text
python -m moughorai.atlas_cli refactor <root> --no-impact --json
```

| Snapshot | Median wall time | Median peak working set | Maximum peak working set |
| --- | ---: | ---: | ---: |
| Maven | 1.581276 s | 205.875 MiB | 206.051 MiB |
| Quarkus | 14.039826 s | 1260.176 MiB | 1260.723 MiB |
| Spring | 7.295175 s | 709.531 MiB | 709.605 MiB |
| Elasticsearch | 28.377880 s | 2369.062 MiB | 2369.164 MiB |

All 12 processes exited 0 with empty stderr. Each repository produced identical
stdout bytes across its three runs, and every input snapshot retained its exact
pre-run SHA-256. Each accepted snapshot reports that PR128 dependency analysis did
not execute and contains no dependency-cycle observation, so the honest result is
zero advice with an `insufficient` cycle-breaking capability. Positive production-
path behavior is covered by focused tests using the normal PR128 producer and
authoritative PR129 cross-project edges.

No feature-identical pre-PR137 request-path or memory baseline exists because
`atlas refactor` did not exist. The figures above are absolute observations, not an
A/B improvement. Process working set includes Python, snapshot loading, graph and
resolver reconstruction, and operating-system cache effects; it is not exclusive
PR137 allocation.

## Remaining limitations

- General simplification advice remains unsupported.
- Duplicate consolidation requires authoritative structural clone groups.
- Extraction requires complete method/class complexity, cohesion, size, ownership,
  and dependency evidence.
- Package restructuring and modularization require resolved dependency clusters and
  persisted intended boundaries.
- Dependency removal requires complete build and usage evidence.
- Layer-violation repair requires persisted intended direction rules.
- Gain and effort stay `unknown` when current evidence cannot quantify them.
- Ambiguous project identities suppress advice; the documented IntelliJ module-
  identity limitation remains.
- Accepted real snapshots validate deterministic degradation but not positive-cycle
  performance because none contains executed PR128 cycle evidence.

No PR138 Security Intelligence functionality was added.
