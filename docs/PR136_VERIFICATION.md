# PR136 Verification

Status: complete on the PR136 delivery candidate.

## Baseline and roadmap compliance

- Starting commit: `cddfefc09ee7ae2ceeb908f167568797c02041d0`.
- `HEAD` and `origin/main` matched and the worktree was clean before PR136 work.
- The imported `moughorai` package resolved inside this checkout.
- PR136 implements only deterministic Impact Prediction.
- `IMPLEMENTATION_ROADMAP.md` and `ROADMAP_DEPENDENCY_MATRIX.md` were not modified.
- No PR137 refactoring recommendation, PR138 security analysis, second graph,
  second resolver, persistent cache, embedding model, or LLM dependency was added.

## Focused and full validation

The final focused command covered PR136 models, prediction, adversarial behavior,
CLI, PR135 search regressions, and the PR105 public facade:

```text
154 passed in 6.28s
```

The required full suite was executed exactly once on the final production code:

```text
4071 passed, 3 skipped in 30.79s
```

No warnings were reported. The three skips were the existing Windows symlink
capability checks:

- `test_recursive_membership_does_not_follow_symlinks_outside_workspace`:
  directory symlink creation unavailable;
- `test_internal_file_symlink_is_canonicalized_once`: file symlink creation
  unavailable;
- `test_project_indexer_does_not_follow_file_symlinks`: file symlink creation
  unavailable.

Additional verification:

- `python -m compileall -q moughorai`: passed;
- `git diff --check`: passed; Git reported only the checkout's existing CRLF
  conversion notices;
- public API manifest and frozen signature fixture: passed in the focused and full
  suites;
- PR26 legacy impact service compatibility: passed in the full suite.

## Determinism and safety

Focused tests verify:

- exact request and response `to_dict()` / `from_dict()` round trips;
- byte-identical JSON for repeated, reordered, warm, and concurrent requests;
- bounded depth, high-degree adjacency, result limits, PR131 paths, and evidence
  references;
- deterministic shortest-path selection with relation-strength tie-breaking;
- cycle safety and exclusion of changed roots from impacted findings;
- exact evidence closure, canonical evidence IDs, snapshot lineage, graph digest,
  request fingerprint, and confidence-formula binding;
- rejection of absolute paths, raw/source-shaped queries and prose, arbitrary
  evidence text, malformed enums, booleans, arrays, numbers, and duplicate evidence;
- conservative ambiguity when PR134 candidate projection is truncated;
- producer-bound call authority using `moughorai.call_graph.v1:calls`; generic
  `calls` and `semantic_graph:calls` labels do not create findings;
- PR131 `member_owner` mapping from canonical `member_of` evidence, tampered PR131
  identity rejection, bounded path truncation, and unavailable state without usable
  call/reference evidence;
- PR132 risk lineage validation and risk/search/Git non-authority;
- multi-source resolution, breaking-change attribution, and human rendering;
- missing calls, unknown dependency scope/version, external consumers, and partial
  module identity remain explicit rather than being treated as safe or empty.

Impact responses contain canonical semantic identities, structured facts, bounded
one-way evidence references, and fixed explanatory text only. They contain no source
bodies, comments, arbitrary literals, absolute paths, private remotes, host data, or
LLM output.

## Snapshot replay benchmarks

The final PR136 code replayed the accepted Maven, Quarkus, Spring Framework, and
Elasticsearch semantic snapshots. This was snapshot validation, not a fresh source
analysis. Therefore the project-success figures below identify the accepted baseline
represented by each snapshot; PR136 did not rewrite accepted goldens.

| Repository | Accepted baseline | Projects | Nodes | Edges | Snapshot bytes | Load s | Resolver s | Impact index s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Apache Maven | 92/92 | 92 | 24,282 | 27,290 | 33,715,785 | 0.254758 | 0.900035 | 0.072231 |
| Quarkus | 1,442/1,442 | 1,442 | 149,048 | 167,850 | 337,186,920 | 2.424391 | 7.045799 | 0.421437 |
| Spring Framework | 29/29 | 29 | 104,095 | 114,190 | 146,029,291 | 1.180471 | 4.315295 | 0.088610 |
| Elasticsearch | 545/545 | 545 | 355,782 | 388,613 | 544,047,043 | 5.296612 | 15.526919 | 0.226177 |

Every required representative query was executed twice. Exact PR134 resolution was
preserved: Maven `MavenSession` was ambiguous with two candidates; Spring
`ApplicationContext` and `scheduler` were ambiguous with 73 and 15 candidates;
the other broad phrases were `not_found`. PR136 did not invoke PR135 to guess a
subject or convert relevance into impact.

Each repository also ran a resolved canonical `overrides` edge probe twice:

| Repository | Findings | Visited nodes | Visited edges | First s | Warm s | JSON identical |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Apache Maven | 6 | 4 | 13 | 0.008870 | 0.008700 | yes |
| Quarkus | 4 | 2 | 7 | 0.006713 | 0.006538 | yes |
| Spring Framework | 4 | 2 | 7 | 0.006307 | 0.006165 | yes |
| Elasticsearch | 5 | 3 | 10 | 0.007453 | 0.007258 | yes |

All first/warm query pairs produced byte-identical JSON. SHA-256 before and after
each replay was identical:

- Maven: `63b06803be261a8c92dcd7b96f7c714dbebb3e3748a47dd76c14706e58d2bd40`;
- Quarkus: `4c3357ed62bdd3d91ed3654a0e6a826a8c34f8dbe29f6879a23ef9514c4a4da1`;
- Spring: `1e1c2969045b17d2f3d42ed173f4a7534c31d82cf86f7b5671d8d0a2dc87b117`;
- Elasticsearch: `ba829dceef927ccc4d835ac4b2957c7860c92e5a1f150b5f663b87399de6cbb3`.

The resolved warm probes remained below 9 ms. Resolver restoration dominated large
snapshot startup; PR136's feature-local capability index remained below 0.43 s even
for Elasticsearch. No persistent cache was justified or added.

## IntelliJ limitation

No complete IntelliJ semantic snapshot exists because the accepted benchmark has
119 discovered projects, 118 successes, and one legitimate `idea` project failure
caused by the documented module-identity conflict. PR136 did not hide, alter, or
reclassify that failure. Module-scoped duplicate-subject and truncated-ambiguity
behavior was instead validated with bounded synthetic fixtures in the full suite.

## Persistence and compatibility decision

Impact predictions are request-specific and reconstructible from compatible
snapshot facts. PR136 therefore publishes no default snapshot payload and adds no
persistent cache. Older snapshots remain readable; absent or incompatible PR131,
PR132, Git, search, call, composition, or module evidence degrades only the relevant
capability. Snapshot bytes and identifiers remain unchanged when PR136 is used.
