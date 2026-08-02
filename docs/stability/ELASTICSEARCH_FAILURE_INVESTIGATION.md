# Elasticsearch failure investigation

## Status

The pinned Elasticsearch checkout is now fully analyzable by Atlas: two fresh,
independent `--force --no-recover` runs discovered 545 projects and completed all
545 without an internal exception. The benchmark remains **DIAGNOSTIC ONLY**. It
has not been captured through the canonical prepare/manifest/replay workflow, has
only two fresh timing samples, and its 544 MB snapshot has a material replay and
memory cost.

This work is benchmark-driven hardening. It does not change the Atlas roadmap,
implement a later roadmap PR, execute Gradle, or add repository-specific behavior.

## Provenance and initial state

| Repository | Evidence |
| --- | --- |
| Atlas | Starting commit `75a8e1d168edea091a37d61fac6d5130b7639edc`; `HEAD` matched `origin/main`; worktree clean; the imported `moughorai` package resolved below the checked-out Atlas source tree. |
| Elasticsearch | Official origin `https://github.com/elastic/elasticsearch.git`; pinned commit `273e03a8a7149170fac16761af3fbf522b52f9fe`; detached checkout; only policy-allowed `.atlas/` output was untracked. |
| Windows path policy | Checkout-local `core.longpaths=true` remained enabled. |

The baseline command was a fresh static Atlas analysis. It discovered 436 projects,
completed 427, failed nine, reported `succeeded: no`, returned native process exit
code 0, and took 317.985 seconds. No successful semantic snapshot was published.

Exit code 0 is the documented CLI contract, not a shell-pipeline defect. `analyze`
emits and records a report but is deliberately non-gating. `check` is the quality
gate and raises its configured nonzero analysis exit code when a project fails. A
direct native-process invocation reproduced exit code 0 without a PowerShell
pipeline, so no exit semantics were changed.

## Failure matrix

Every failure raised `DuplicateTypeError` from the Java symbol index. All triggering
files were tracked, regular repository files. None was a symlink, generated copy,
resource-only Java file, or deliberately invalid fixture.

| Project | Conflicting qualified type | Evidence | Group |
| --- | --- | --- | --- |
| `libs-cli-terminal` | `org.elasticsearch.cli.terminal.ConsoleUtil` | `src/main/java` and exact `src/main22/java` counterpart | A: version overlay |
| `libs-entitlement` | `org.elasticsearch.entitlement.config.MainInstrumentationProvider` | `src/main/java` and exact `src/main25/java` counterpart | A: version overlay |
| `libs-entitlement-qa-entitlement-test-plugin` | `org.elasticsearch.entitlement.qa.test.StructuredTaskScopeActions` | `src/main/java` and exact `src/main25/java` counterpart | A: version overlay |
| `libs-foreign-adapter` | `org.elasticsearch.foreign.adapter.ArenaAdapter` | `src/main/java` and exact `src/main22/java` counterpart | A: version overlay |
| `qa-remote-clusters` | `org.elasticsearch.cluster.remote.test.AbstractMultiClusterRemoteTestCase` | Distinct conventional `test` and `javaRestTest` source sets in one Gradle project | C: source-scope ambiguity |
| `x-pack-plugin-eql-qa` | `org.elasticsearch.xpack.eql.EqlDateNanosIT` | Two real deep Gradle child projects were owned by their QA ancestor | B: collapsed project ownership |
| `x-pack-plugin-logsdb-qa` | `org.elasticsearch.xpack.logsdb.LogsdbWithBasicRestIT` | Two real deep Gradle child projects were owned by their QA ancestor | B: collapsed project ownership |
| `x-pack-plugin-ml-qa` | `org.elasticsearch.xpack.ml.integration.InferenceIT` | Two real deep Gradle child projects were owned by their QA ancestor | B: collapsed project ownership |
| `x-pack-plugin-sql-qa` | `org.elasticsearch.xpack.sql.qa.jdbc.JdbcIntegrationTestCase` | Two real deep Gradle child projects were owned by their QA ancestor | B: collapsed project ownership |

### Representative tracebacks

All nine tracebacks followed the same production path:

```text
AnalyzerRegistry.__call__
  -> JavaLanguageAnalyzer.analyze
  -> JavaSymbolIndexBuilder.build
  -> JavaSymbolIndex.__init__
  -> DuplicateTypeError
```

Representative evidence was:

```text
Duplicate Java type 'org.elasticsearch.cli.terminal.ConsoleUtil'
in project 'libs-cli-terminal':
libs/cli-terminal/src/main/java/.../ConsoleUtil.java
and libs/cli-terminal/src/main22/java/.../ConsoleUtil.java

Duplicate Java type
'org.elasticsearch.cluster.remote.test.AbstractMultiClusterRemoteTestCase'
in project 'qa-remote-clusters':
qa/remote-clusters/src/javaRestTest/java/.../AbstractMultiClusterRemoteTestCase.java
and qa/remote-clusters/src/test/java/.../AbstractMultiClusterRemoteTestCase.java

Duplicate Java type 'org.elasticsearch.xpack.eql.EqlDateNanosIT'
in project 'x-pack-plugin-eql-qa':
x-pack/plugin/eql/qa/multi-cluster-with-security/src/javaRestTest/java/.../EqlDateNanosIT.java
and x-pack/plugin/eql/qa/rest/src/javaRestTest/java/.../EqlDateNanosIT.java
```

Temporary traceback capture stayed outside the Atlas worktree and was not retained
in source, tests, or committed artifacts.

## Root causes

### Group A: exact Java-version overlays

Four libraries apply Elasticsearch's `elasticsearch.mrjar` Gradle convention and
store alternatives in `src/mainNN/java`. Atlas already handled Spring-style
`src/main/javaNN`, but not this equally structured layout. Merging the baseline and
its exact alternative created a false same-project duplicate.

The fix recognizes both layouts, keeps the ordinary `src/main/java` or
`src/test/java` baseline, and omits only an eligible versioned file with the exact
same relative tail. It emits `ATLAS-JAVA-SOURCE-VARIANT`. An additive versioned file
without a baseline counterpart remains analyzed. Atlas still does not select a Java
toolchain version or claim complete multi-release-JAR modeling.

### Group B: statically declared recursive Gradle membership

Four QA ancestors exceeded the generic marker scan's depth. Elasticsearch's root
settings define a strict recursive helper that includes each `build.gradle`-gated
directory and stops at nested Groovy `settings.gradle` boundaries or already-known
projects. The
deep children were real Gradle projects, but Atlas previously assigned their files
to the nearest discovered ancestor.

Atlas now recognizes only the complete, statically verified helper structure and
literal top-level invocations. Traversal is iterative, deterministic, contained to
literal roots, build-gated at every level, and does not follow symlinks. It reuses
existing alias, flattened-name collision, dependency, and ancestor ownership rules.
Prior dynamic `include`, `includeFlat`, or external `projectDir` mutations make
`findProject` semantics unknown and cause the recursive evidence to fail closed.
No arbitrary `build.gradle` scan or Gradle execution was added.

### Group C: distinct conventional source sets

`qa-remote-clusters` intentionally contains the same qualified type in two distinct
conventional source roots. A project-only ID cannot represent both definitions, and
their cross-source-set compilation relationship is not statically proven.

On a proven cross-source-set `DuplicateTypeError`, and only when every parsed Java
input can be assigned safely to a conventional non-versioned
`src/<sourceSet>/java` root, Atlas indexes each source set independently. Symbols
receive a deterministic optional `scope_id`, owner IDs remain in the same scope,
and persistence, immutable snapshots, the global database, semantic context, and
canonical graph retain that scope. Existing unscoped and project-only IDs remain
byte-for-byte unchanged.

Atlas deliberately omits the entire Java architecture artifact for the recovered
project, marks all Java architecture relations unavailable, and emits the source-free
`ATLAS-JAVA-SOURCE-SETS-PARTIAL` diagnostic. Non-relational visibility, annotations,
and Java-main evidence remain available. A
duplicate inside one source set, an unclassifiable path, or a version-root ambiguity
still raises `DuplicateTypeError`.

### Cache and recovery compatibility

The workspace analysis-result producer fingerprint advanced from v2 to v3. Existing
PR70 persistence and PR74 recovery machinery therefore invalidate stale results
created before source scopes and the revised source ownership rules. The storage
schema remains backward compatible because `scope_id` is emitted only when present.

## Regression coverage

The new fixtures are small and repository-independent. They cover:

- both versioned overlay layouts, exact counterparts, additive version files, and
  genuine duplicates that must still fail;
- distinct source sets, scoped member ownership, visibility, annotations, Java main
  evidence, omitted ambiguous relations, serialization round trips, and legacy
  unscoped payloads;
- verified recursive membership, nested Groovy `settings.gradle` boundaries, skips,
  literal invocation roots,
  source-free evidence, deterministic ordering, ownership, collisions, path escape,
  symlinks, changed helper behavior, dynamic invocation, prior membership mutation,
  and exact logical-path round trips.

Regression-first executions observed the expected failures before implementation:
four failures in the version/source-scope fixture, three failures in scope contract
checks, and five failures in recursive membership discovery. Final focused evidence
included:

| Scope | Result |
| --- | --- |
| Version/source-scope dedicated tests | 12 passed in 0.27 s |
| Combined Java/source-scope compatibility | 171 passed in 3.30 s |
| Integrated affected-area selection | 274 passed, 1 skipped in 3.38 s |
| Final recursive and legacy Gradle discovery | 50 passed, 1 skipped in 0.95 s |
| Maintainer's final guard review | 19 passed, 1 skipped in 0.45 s |

`python -m compileall -q moughorai` completed successfully. `git diff --check`
reported no whitespace error; Windows emitted only informational LF-to-CRLF notices.

The full Atlas suite was executed exactly once after targeted tests passed:

```text
3803 passed, 2 skipped in 23.28s
```

The exact skips were the new directory-symlink test and the existing file-symlink
production-remediation test. Both were skipped because the Windows test account
lacked symlink creation privileges (`WinError 1314`); there were no test warnings or
failures.

## Former failures after the fix

The normal discovery and production analyzer path was rerun without snapshot
publication for all nine projects:

| Project | Result | Classification or remaining limitation |
| --- | --- | --- |
| `libs-cli-terminal` | Succeeded | Exact main22 overlay omitted; variant warning retained. |
| `libs-entitlement` | Succeeded | Exact main25 overlay omitted; variant warning retained. |
| `libs-entitlement-qa-entitlement-test-plugin` | Succeeded | Exact main25 overlay omitted; variant warning retained. |
| `libs-foreign-adapter` | Succeeded | Exact main22 overlay omitted; variant warning retained. |
| `qa-remote-clusters` | Succeeded, semantic capability partial | 66 symbols persisted across `gradle-source-set:javaRestTest` and `gradle-source-set:test`; Java architecture relations are unavailable for the recovered project. |
| `x-pack-plugin-eql-qa` | Succeeded | Parent retains its own file; deep children are independent projects. |
| `x-pack-plugin-logsdb-qa` | Succeeded | Parent retains its own file; deep children are independent projects. |
| `x-pack-plugin-ml-qa` | Succeeded | Parent retains its own file; deep children are independent projects. |
| `x-pack-plugin-sql-qa` | Succeeded | Parent retains its own file; deep children are independent projects. |

The four overlay projects still emit pre-existing per-file Java parse diagnostics
where syntax is unsupported. These are structured input diagnostics, not internal
exceptions, and were not suppressed. None of the nine failures proved an
intentionally invalid fixture, so no fixture was silently discarded or reclassified
as successful.

## Full Elasticsearch validation

Both full runs used the same pinned checkout, `--force`, and `--no-recover`.

| Result | Run 1 | Run 2 |
| --- | ---: | ---: |
| Projects | 545 | 545 |
| Succeeded | 545 | 545 |
| Failed | 0 | 0 |
| Internal exceptions | 0 | 0 |
| Native exit code | 0 | 0 |
| Elapsed | 671.152 s | 652.958 s |
| Snapshot size | 544,047,044 bytes | 544,047,044 bytes |
| Graph nodes | 355,782 | 355,782 |
| Graph edges | 388,613 | 388,613 |

Both commands exposed the same repository-owned Python `SyntaxWarning` at
`x-pack/plugin/sql/connectors/tableau/tdvt/tdvt_run.py:150` for an invalid escape
sequence. It did not fail an Atlas project. Warning suppression was not needed to
establish the successful Atlas result.

Raw snapshot identity is intentionally volatile:

| Artifact | Run 1 | Run 2 |
| --- | --- | --- |
| Snapshot ID | `4178ecce07e387035f2915dd1853791b916cf90c87414642f6fcac431f3c68aa` | `71ada79b4311c105d4901ba5f018b05181642b3ea24eeb7cdf7e26be8342d867` |
| Raw ASS SHA-256 | `ad4012903e49f9bf7be5e58b525594a24a71099dff9904618d0f5ca1d868a3ad` | `f7864400c03eb9a30959e5e6f41687402184d69e5624800df9be4aa18600c032` |

All deterministic semantic gates matched exactly:

| Gate | SHA-256 |
| --- | --- |
| Workspace project order | `4395ec3a5341ff79b7ffacd97d85932480391b2469b6883339fe9daae53b4c07` |
| Portable workspace payload | `cc781bb41356dfe0f4915f39a762cc692792c5c230c30d4fef74e22252fa4388` |
| Module hierarchy | `1b6acffafcdb24e218e01ca370af579877a5e50cc5f733dae527e504fcb77e9b` |
| Semantic payload | `bb0fa2eb03f326b2ffb1c36fc3bd0e9f889ee7d0e2f87e152dc21e1894ddb467` |
| Ordered dependency records | `095babeb0aea792fcab1c8c5bd23368ebe9ec66cc3aef732171bf89d4b79fffb` |
| Risk analysis | `e0c96448da34e51162cf1522ce61c0481ed0e80988f8cb095abd3f1bb354fb15` |
| Repository report | `16db65d6477446b76e71d2675a411ee6a38c68bd58fe24b4de26becd35971e0d` |
| Default Explain Anything output | `434b3c850746cf82288a2131f1cbfc893c14dc9f7fb6f3f3c814f2a9159ad254` |
| Portable semantic projection | `f01cddf387c693325511a096dfd43b0a4476036e146292dcfd6d12951c47f416` |
| Portable canonical graph | `0f06c041c3933c4a6bd0d7cbbd7eb5bb2bc8ababe70e2fb58c881004ba5d07f6` |
| Deterministic portable ordering | `f25180692ec9a4efe8f8436971bfc8a5b5d3e304e388553a8c761a91f5d26d6c` |

The snapshot contains 353,403 symbols, 355,782 graph nodes, 388,613 graph edges,
1,237 ordered declared-dependency records, 545 hierarchy records, and 66 graph
nodes carrying the two explicit Java source scopes. Compact canonical section sizes
are 169,756,710 bytes for symbols, 136,656,164 bytes for the graph, 56,826,273
bytes for design-pattern findings, and 11,258,663 bytes for reachability.

## Explain review

The default deterministic explanation:

- identifies the repository as `es` and reports 545 discovered projects;
- reports exact file, byte, production, test, generated, graph-node, and graph-edge
  units;
- keeps architecture candidates and risk indicators evidence-scoped, confidence
  bounded, and explicitly non-defect/non-vulnerability claims;
- states that call evidence, closed-world reachability, dependency direction, cycle
  checks, runtime tests, and coverage are unavailable where appropriate;
- contains no absolute machine path or raw source code;
- contains no Spring Boot or React claim;
- is identical across both snapshots at 10,847 characters and the hash above.

Structured repository metadata identifies Gradle as the only detected build system,
with 543 project-local observations. Classified language counts are 99.368575 percent
Java and total 100 percent within six-decimal rounding. Framework evidence is limited
to JUnit 4, JUnit 5, Log4j2, Mockito, SLF4J, and Testcontainers. The default
7,000-token report budget omits some lower-ranked technology and hierarchy detail;
that explicit omission is a context-selection limitation, not a fabricated answer.

## Canonical non-regression

No accepted golden was modified.

| Repository | Pinned commit | Result | Elapsed | Deterministic comparison |
| --- | --- | ---: | ---: | --- |
| Apache Maven | `3e01a12e9eacd2b336f4db786d54e35647ce268c` | 92/92 | 35.589 s | Portable `a591962406d5f5f784d491e025652aa73043478bbacebe52638052181ec8e1f5` and graph `2df64026aed0e7b76ea471dfb9690374f45937b04a0b5655f3f820badaeaae16` match the reviewed corrected producer. |
| Quarkus | `bbc0853aef94c567bac2cc4a98d51c90fb423648` | 1442/1442 | 572.844 s | Portable `9297de564e0a091ffc5e497a40ab238ba33ef904e74973fb0af9f51a117d3943` and graph `0a0834f8dae5509d9a0b019b2038d982df52e7ed3f609e48937fff7a60aa792f` match the reviewed corrected producer. |
| Spring Framework | `eceebb3077dda9e1b19d73c0398ef022cd91f99c` | 29/29 | 113.393 s | Semantic, portable, report, explanation, risk, graph, and project-order hashes all match the recorded diagnostic reference. |

The accepted M1.1 Maven and Quarkus goldens predate a separately reviewed Java
producer correction. Their portable and graph hashes therefore intentionally differ
from current output, exactly as recorded in
`SPRING_PORTABLE_PATH_HARDENING.md`. This investigation neither conceals that drift
nor updates those goldens.

## Performance observations

Three read-only discovery and enumeration repeats returned identical workspace and
project-order hashes:

| Repeat | Discovery | File enumeration | Project-file records |
| --- | ---: | ---: | ---: |
| 1 | 6.159221 s | 3.730463 s | 46,215 |
| 2 | 7.663141 s | 3.606589 s | 46,215 |
| 3 | 7.774670 s | 3.681978 s | 46,215 |

The recursive helper support did not introduce an arbitrary repository traversal;
discovery remains bounded by literal roots and build-gated chains. No persistent
cache or new parallel execution was introduced.

A representative instrumented rerun of the nine former failures took 0.913792
seconds. It measured 154 Java parses at 0.757253 seconds total, seven symbol-index
builds at 0.008385 seconds, and four Java architecture builds at 0.011764 seconds.
This is a defect-cohort micro-profile, not a repository-wide phase total.

History records show 413.593 seconds of summed project analysis in run 1 and 400.563
seconds in run 2. The differences from wall time, 257.559 and 252.395 seconds,
respectively, include discovery, context collection, graph/report/pattern/reachability
construction, snapshot serialization, history, and output. Existing instrumentation
does not separate those contributors without another invasive full run, so the
residual is not mislabeled as snapshot construction alone.

The 544 MB ASS is the principal measured scalability concern. Loading, validating,
portable-projecting, explaining, and hashing each retained snapshot took 241.4 and
240.8 seconds. This investigation makes no speculative serialization or caching
change; a future optimization must first add bounded phase/memory instrumentation
and preserve source-free deterministic identity.

## Eligibility decision

| Gate | Result | Evidence |
| --- | --- | --- |
| Official pinned Git provenance | Pass | Official origin and full commit verified. |
| Tracked worktree and provenance integrity | Pass | Only policy-allowed `.atlas/` output was untracked; checkout-local long paths enabled. |
| Canonical clean initial state | Fail | The operational checkout already contained generated `.atlas/` evidence and was not prepared through the canonical workflow. |
| Complete supported project discovery | Pass | 545 projects and identical discovery hashes across three repeats. |
| All valid projects analyzed | Pass | 545/545 twice; zero internal exceptions. |
| Intentional invalid fixtures classified | Pass | None of the nine was an intentional invalid fixture; each root cause was proven. |
| Deterministic repeated output | Pass | All semantic gates above match exactly. |
| Portable projection | Pass | Full projection succeeds and contains no machine path. |
| Source-free output | Pass | Snapshot projection and explanation contain no raw source or absolute path. |
| Replay eligible | Fail | No canonical fresh manifest, retained source-free bundle, or linked replay capture. |
| Performance metadata | Fail | Two fresh samples, not the canonical three; phase and peak-memory data remain incomplete. |

Elasticsearch therefore remains **DIAGNOSTIC ONLY**, not a candidate or canonical
golden. Promotion requires a clean canonical prepare, at least three final-code
samples, a reviewed source-free manifest bundle, linked replay, peak-memory and
phase-level evidence, and an explicit decision about the practical 544 MB snapshot.

## Maintainer review

| Area | Decision | Reason |
| --- | --- | --- |
| Failure group A | Keep | Extends an existing exact-counterpart rule to a second structurally equivalent Gradle layout without selecting a Java version. |
| Failure group B | Keep | Proves one complete helper contract and literal invocation instead of scanning or executing Gradle. |
| Failure group C | Keep | Preserves both legitimate definitions, explicit uncertainty, and genuine duplicate errors. |
| Source-root changes | Keep | Additive files remain; only exact overlays are omitted. |
| Java model changes | Keep | Optional scope identity is backward compatible and propagates through existing stores and graph integration. |
| Diagnostics | Keep | Variant and partial states are source-free and honest; parse diagnostics remain visible. |
| Tests | Keep | Small fixtures cover the proven semantics, adversarial cases, determinism, and legacy compatibility. |
| Benchmark artifacts | External only | Logs and 544 MB snapshots remain outside Git; accepted goldens are unchanged. |
| Elasticsearch baseline | Defer | Replay, three-sample performance, memory, and canonical lineage gates are incomplete. |

The final review found no temporary traceback printing, Elasticsearch-specific
branch, broad error suppression, weakened duplicate detection, generated `.atlas`
content, benchmark log, local replay manifest, or debug instrumentation in the
proposed Git diff. A pre-existing ignored `.atlas/` directory remains operational
data and is not part of the commit.

## Remaining limitations and recommendation

- General Gradle execution, arbitrary loops/closures, Kotlin helper parsing,
  `includeBuild`, dynamic project paths, external `projectDir` mappings, custom build
  filenames, and unsupported pre-invocation membership mutations remain unmodeled.
- Exact overlays remain a conservative baseline preference, not target-toolchain or
  complete multi-release-JAR semantics.
- Source scopes are introduced only to recover a proven conventional cross-source-set
  conflict. They do not establish Gradle compilation membership, and cross-scope
  ambiguity causes Java architecture relations to be unavailable for the entire
  recovered project.
- Unsupported Java syntax still creates structured per-file diagnostics.
- The semantic snapshot duplicates large symbol and graph projections and needs
  measured size/memory work before Elasticsearch can be promoted.

The next benchmark action should be a canonical Elasticsearch capture only after
adding non-invasive phase and peak-memory measurement. The next Gradle extension
should be driven by a new pinned corpus that proves a specific unsupported settings
shape; Atlas should not generalize the helper parser speculatively.
