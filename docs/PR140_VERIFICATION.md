# PR140 Verification

## Baseline and roadmap compliance

PR140 was implemented from the exact pushed PR139 baseline
`2e8e27097dbcb43625639ea4234172409a8ed36c`. Before implementation, `HEAD`,
`origin/main`, and `origin/HEAD` identified that commit and the worktree contained no
PR140 production changes.

The official roadmap assigns **Change Review** to PR140: analyze Git diffs and
produce impact analysis, architectural concerns, test recommendations, risk
assessment, and migration advice. The implementation provides each area through an
explicit deterministic section while preserving unavailable, insufficient,
unsupported, stale, and partial states.

PR140 does not implement PR141 Repository Evolution. In particular, it does not
claim a semantic before/after comparison, architecture drift, deleted-symbol
identity, API/ABI compatibility, or diff-introduced security findings.

## Architectural verification

The implementation reuses:

- PR92 `GitDiffService` for working-tree, staged, base-to-working-tree, and
  base-to-head collection;
- PR129 `KnowledgeGraph` as the only canonical graph;
- PR130 `EvidenceIndex` and `ConfidenceCalculator`;
- PR134 `CanonicalSubjectResolver`, extended with one shared exact-path query and
  resolver-owned provenance;
- PR136 `ImpactPredictionService` for impact, affected tests, and compatible risk;
- PR137 `RefactoringAdvisorService` for fully revalidated dependency-cycle seams;
- M2 `MeasurementSession` for opt-in request phases.

`ChangeReviewService` performs no Git subprocess itself. The CLI collects Git facts,
loads a verified snapshot, invokes the service, and renders the result. The service
does not invoke a provider, network service, workspace analyzer, new graph, new
resolver, or new cache.

PR138 security projection is intentionally deferred. No security section or second
security scanner was added. `atlas ai review` remains the independent provider-
backed PR115 command, and PR139 Ask/Chat is unchanged.

## Focused coverage

The PR140 tests are divided by ownership:

- `tests/test_pr140_git_diff.py`: strict DTOs, refs, resolved commit provenance,
  sub-workspace translation, path safety, deterministic fingerprints, and source
  exclusion;
- `tests/test_pr140_path_subject_resolution.py`: exact path sources, conflicting
  symbol metadata, structural project fallback, deterministic bounds, provenance,
  and strict round trips;
- `tests/test_pr140_change_review.py`: alignment, exact mapping, PR136 impact,
  evidence-backed tests and risk, PR137 cycle seams, global bounds, section states,
  rendering, and serialization;
- `tests/test_pr140_change_review_adversarial.py`: tampering, projection mismatch,
  source/private-path rejection, stale/unknown short-circuiting, provider/network
  prohibition, and large boundaries;
- `tests/test_pr140_change_review_measurement.py`: measurement phases, response
  growth, reordered equivalence, and snapshot byte stability;
- `tests/test_pr140_change_review_cli.py`: separate provider-free CLI, Git argument
  validation, deterministic JSON/human output, explicit alignment assumption, no
  rescan, legacy command separation, and opt-in profiles.

Focused PR140 validation executed during implementation:

```text
python -m pytest -q -p no:cacheprovider --basetemp=<isolated> tests/test_pr140_*.py
```

Result: **82 passed in 23.50s**.

Additional final-candidate validation already executed:

| Validation | Result |
| --- | --- |
| Historical compatibility matrix, including legacy AI and PR139 | **586 passed in 17.85s** |
| Frozen public API fixture | **8 passed in 0.33s** |
| Complete main-worktree suite | **4359 passed, 3 skipped in 57.48s** |

These results replace the earlier interim 61-test and 12-test observations. The
three complete-suite skips remain reported as skips; this document does not convert
them into passes.

## Determinism and integrity assertions

Focused tests verify:

- reordered Git files, graph nodes, edges, symbols, and path candidates produce
  identical canonical JSON and human output;
- global file, subject, impact, and architecture bounds report exact omitted counts;
- the architecture advice limit applies globally across changed scopes;
- `from_dict()` rejects unknown fields, count mismatches, malformed IDs, foreign,
  dangling, unused, or wrong-lineage evidence, and stale semantic conclusions;
- exact feature projection reconstructs Git, mapping, and candidate-association
  evidence from serialized facts;
- resolver provenance exactly covers every returned file candidate;
- semantic confidence is recalculated from shared evidence roles, coverage, and
  ambiguity and cannot be modified independently;
- section states, item IDs, and evidence IDs are recomputed from nested results;
- absolute/private paths, source-shaped text, retained-source flags, unsafe control
  content, and malformed Git paths are rejected or escaped;
- review execution leaves the input snapshot byte-identical and publishes no
  `change_review` snapshot key;
- stale and unknown alignment never invoke PR136 or PR137;
- the service invokes no provider, socket, URL, subprocess, or workspace rescan.

## Compatibility assertions

- Existing Git-diff constructors and the PR92 filter remain valid through additive
  defaulted metadata fields.
- Existing subject resolution remains unchanged; the exact-path query is additive.
- Snapshots without a PR129 graph remain readable and report unavailable identity.
- The frozen public API facade is not expanded or renamed.
- Existing PR136 and PR137 request/response contracts are consumed unchanged.
- Existing semantic snapshots are read-only and receive no PR140 payload.
- `atlas ai review`, `atlas ai ask`, and `atlas ai chat` retain their established
  meanings.

## Final delivery validation

Completed final-candidate checks:

- focused PR140 tests: **82 passed in 23.50s**;
- historical compatibility: **586 passed in 17.85s**;
- public API compatibility: **8 passed in 0.33s**;
- complete main-worktree suite: **4359 passed, 3 skipped in 57.48s**;
- controlled latency, memory, response-size, determinism, and snapshot checks: see
  `PR140_PERFORMANCE.md`;
- official repository benchmark validation: completed as recorded below.

## Official repository validation

| Repository and pin | Executed result | Determinism |
| --- | --- | --- |
| Apache Maven `3e01a12e9eacd2b336f4db786d54e35647ce268c` | 92/92 twice; timed repeat 30.419s | Portable, report, risk, graph, and project-order hashes exact |
| Quarkus `bbc0853aef94c567bac2cc4a98d51c90fb423648` | 1442/1442 at 405.544s and 404.313s | Same five hashes exact |
| Spring Framework `eceebb3077dda9e1b19d73c0398ef022cd91f99c` | 29/29 at 102.889s and 116.817s | Same five hashes exact |
| Elasticsearch `273e03a8a7149170fac16761af3fbf522b52f9fe` | 545/545 at 834.242s and 818.025s | Same five hashes exact |
| IntelliJ Community `6affce35cb2aad82747b36e886836c44e0188e46` | 119 discovered and 118 succeeded at 409.470s and 409.365s; only `idea` failed | Exact stdout/stderr; no `latest.ass` |

Both Elasticsearch runs emitted the upstream
`tdvt_run.py:150: SyntaxWarning: invalid escape sequence '\.'` warning on stderr.
It did not alter the 545/545 result or the five exact deterministic hashes.

The IntelliJ result is the accepted architectural limitation: project `idea`
reports `DuplicateTypeError` for
`com.intellij.testFramework.TestDataFile` because Atlas does not yet model the
required module-scoped semantic identity. Both executions reproduced the exact
stdout and stderr and correctly published no `latest.ass`.

Final syntax, patch, and replay checks:

- `python -m compileall -q moughorai tests`: **passed (exit code 0)**;
- complete candidate `git diff --check`: **passed (exit code 0)**;
- patch application onto detached PR139 baseline
  `2e8e27097dbcb43625639ea4234172409a8ed36c`: **passed**;
- replay-focused PR140 tests: **82 passed in 30.38s**;
- replay public API fixture: **8 passed in 0.49s**;
- replay complete suite: **4359 passed, 3 skipped in 73.17s**;
- replay `compileall` and `git diff --check`: **passed (exit code 0)**.

The replay checkout was detached, contained no staged files, and received only the
candidate patch. No benchmark state, pytest directory, Python cache, measurement
sidecar, or validation helper is part of the PR140 file manifest.

## Known limitations

- The CLI defaults to unknown alignment because it deliberately avoids a workspace
  rescan; semantic enrichment requires explicit assumption unless an API caller
  supplies a verified current fingerprint.
- Exact file identity is not hunk-to-declaration identity because snapshots have no
  declaration spans.
- Deleted symbols and semantic renames need commit-bound paired snapshots.
- Missing call, test, and external-consumer evidence prevents completeness claims.
- PR137 cycle seams are existing snapshot context, not issues introduced by the
  reviewed diff.
- General migration planning and diff-aware security review remain unsupported.
- Git output is materialized before response bounds apply.
