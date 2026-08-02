# IntelliJ fixture source-root isolation investigation

## Status

The two original IntelliJ fixture collisions are resolved by a generic,
evidence-ordered Java source selector. The complete benchmark still stops on a
different and legitimate duplicate type compiled in two separately registered JPS
modules. Atlas continues to raise `DuplicateTypeError` for that conflict.

IntelliJ therefore remains **DIAGNOSTIC ONLY**. A failed workspace does not publish
a semantic snapshot, so snapshot, graph, portable-projection, replay, and Explain
Anything evidence is unavailable for this corpus. No earlier snapshot is substituted.

This work does not change the roadmap, implement PR135 or later work, execute a
repository build, introduce a cache or parallel analysis, modify IntelliJ source,
or add repository-specific behavior.

## Provenance

| Repository | Verified input |
| --- | --- |
| Atlas | Starting commit `df2a3db2694b80ac9d2f6ecc881acc8f3f253bd2`; `HEAD` matched `origin/main`, the worktree was clean, and the imported package resolved below the checked-out `moughorai` tree. |
| IntelliJ Community | Official origin `https://github.com/JetBrains/intellij-community.git`; pinned detached commit `6affce35cb2aad82747b36e886836c44e0188e46`; `core.longpaths=true`; only generated `.atlas/` output was untracked. |

Operational paths and generated logs remain outside the Atlas repository and are
not semantic identities or committed evidence.

## Baseline failure matrix

The initial full run discovered 119 projects: 117 succeeded and two failed.
Repository-owned PyDev `SyntaxWarning` messages were external input warnings, not the
Atlas failures.

| Project | Error | Conflicting inputs | Classification |
| --- | --- | --- | --- |
| `plugins-java-decompiler-engine` | Duplicate Java type `records.Anno` | Two `testData/manual/src/records/TestHideConstructorRecordAnno*.java` specimens | Independent decompiler inputs consumed as data; neither Gradle, IML, nor Bazel compiles the directory as part of the parent source set. |
| `idea` | Duplicate Java type `Main` | Two `java/idea-ui/testData/testProject*/src/Main.java` files | Independent synthetic IDE projects copied and loaded one fixture at a time; the parent module compiles `src`, `gen`, and `testSrc`, not these fixture trees. |

Each conflicting physical file was enumerated once. The inclusion trace was:

```text
complete project inventory
  -> AnalyzerRegistry groups every Java-looking file
  -> no generic compiled/resource/fixture separation
  -> one project-level Java symbol index
  -> DuplicateTypeError on an incorrect semantic input set
```

The duplicate detector was correct; its input classification was not.

## Repository evidence and counterexamples

The decompiler module's Gradle, IML, and Bazel metadata compile its `src` and `test`
trees and classify `resources` separately. Its tests consume the `testData/manual`
corpus as input. The IDEA UI IML and Bazel metadata likewise omit the synthetic
`testProject*` trees from compilation.

A path name alone is not enough to exclude code. IntelliJ's root module registry
explicitly registers the API Dump module under `tools/apiDump/testData`; its IML and
Bazel metadata compile that module's `src` tree. All 27 Java inputs in that source
root remain selected. Other real projects discovered below fixture-like names,
including Maven, Gradle, native, and Mermaid test-data projects, retain their own
project ownership.

The correction therefore does not blanket-filter `fixtures`, `testFixtures`,
`testProject`, `mockJDK`, `src`, or test code.

## Generic source-selection policy

Atlas retains the complete repository inventory and derives the Java semantic input
set in the following evidence order:

1. Resolve and contain candidates within their owning project; canonicalize repeated
   internal aliases to one physical source.
2. Read only direct, bounded structured metadata: literal Gradle
   `java/resources.srcDir(s)` calls, direct root IML files, and IML files registered
   by the root `.idea/modules.xml`.
3. Prefer the most-specific declared source or resource root. Equal-depth compiled
   evidence wins because it proves that Java compilation consumes the path.
4. Treat registered module content as authoritative only when that content has an
   attached source or resource root. Unregistered local fixture IMLs do not override
   root ownership.
5. Preserve complete conventional Java roots and generated roots before a fixture
   boundary. A directory merely named `src` is insufficient.
6. Exclude owner-relative `testData` and `test-data` boundaries only when no stronger
   compiled-root evidence exists. Files remain in inventory.
7. Preserve nested projects discovered from their own build descriptors; parent
   subtree exclusion and child-relative source selection remain authoritative.
8. Apply the same selector in normal Java analysis and semantic-context fallback.

Conventional `src/<sourceSet>/resources` roots are excluded, including below a
parent-owned nested directory. A resource-looking package below an already
established `src/<sourceSet>/java` root remains code. Standard test,
`testFixtures`, JMH, generated, and version-specific Java roots remain eligible.

No Gradle or JPS code is executed. Comments, ordinary quoted strings, Groovy slashy
and dollar-slashy strings, and triple-quoted strings cannot masquerade as source-root
declarations. Paths with unresolved variables, foreign URIs, or out-of-project
targets are rejected. Descriptor reads are capped at 16 MiB; XML is capped at
100,000 elements and rejects `DOCTYPE` and `ENTITY` declarations.

Assignments, block-style `java { srcDir(...) }`, multiline calls,
`setSrcDirs(...)`, variables, interpolation, and executable build logic are not
evaluated. A custom root expressed only through unsupported syntax remains unknown
rather than being guessed.

## Implementation and compatibility

The implementation adds one shared selector under `java_workspace` and reuses it in
the production analyzer and context fallback. Existing Gradle comment and literal
argument parsing was extracted into a shared helper rather than duplicated.

Repository inventory counts, project identity, snapshot schemas, canonical graph,
confidence/evidence contracts, public APIs, and `DuplicateTypeError` are unchanged.
The PR70/PR74 analysis-result producer fingerprint advances from v3 to v4 so
persistence and recovery invalidate pre-correction semantic results without a schema
rewrite. Excluded fixture content is not added to symbols, architecture,
dependencies, or source-free semantic context.

## Focused evidence

The regression fixtures cover both original collision shapes plus:

- complete inventory with fixture data absent from Java symbols and architecture;
- `testData` and `test-data` boundaries;
- registered versus unregistered IML roots and structured resources;
- explicit compiled/resource precedence and bounded Gradle evidence;
- comments and ordinary, slashy, dollar-slashy, and triple-quoted strings;
- nested conventional resources versus resource-like Java packages;
- standard test, `testFixtures`, JMH, generated, and version-root preservation;
- independently discovered nested projects;
- out-of-root rejection and internal symlink canonicalization;
- genuine same-source-set duplicates that still raise;
- semantic-context fallback parity, deterministic output, and source-free rendering.

The final affected-area run completed with `111 passed, 1 skipped in 1.90s`. The
skip is explicit: the Windows test account lacks file-symlink creation privilege
(`WinError 1314`). The same canonicalization path was also exercised read-only with
relative, absolute, and repeated aliases against the pinned corpus.

The persistence/recovery compatibility selection completed with `68 passed in
1.15s`. `python -m compileall -q moughorai` exited 0, and `git diff --check`
reported no whitespace error (only informational Windows LF/CRLF notices).

The first full-suite attempt used a sandbox-owned external base temp. Seven checkout
provenance tests could not execute their assertions because the sandbox denied the
local `git-upload-pack`; its exact result was `7 failed, 3820 passed, 3 skipped in
17.21s`. No test was weakened or changed. The clean rerun used a fresh local base
temp outside that process restriction and completed:

```text
3827 passed, 3 skipped in 21.89s
```

The exact skips are the existing directory-symlink recursive-membership guard, the
existing production file-symlink guard, and the new internal file-symlink selector
guard. All report `WinError 1314` because this Windows account cannot create the
required symlink. There were no test warnings or failures in the accepted run.

## Selection measurements

| Project | Inventory | Java candidates | Selected | Excluded | Inventory | Selection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `idea` | 256,515 | 88,217 | 41,481 | 46,736 | 14.003859 s | 8.519099 s |
| `plugins-java-decompiler-engine` | 1,088 | 501 | 227 | 274 | 0.046081 s | 0.046359 s |

Both partitions are exact and disjoint. Replacing a measured linear scan across
every declared root with set membership bounded by path depth reduced the root
selector from 39.654453 seconds to 8.519099 seconds (about 78.5 percent) without
changing any classification or count.

The decompiler project now completes direct production analysis in 1.749898 seconds:
1,088 inventoried files, 192 Java syntax units, 3,231 symbols, 243 architecture
nodes, 934 architecture edges, and 35 isolated parser diagnostics.

No peak-memory measurement was captured. These are selector and project
measurements, not a claim of whole-workspace speedup.

## Remaining legitimate IntelliJ conflict

After the fixture correction, `idea` raises on
`com.intellij.testFramework.TestDataFile` from two tracked sources:

- `platform/testFramework/src/.../TestDataFile.java`, registered as the
  `intellij.platform.testFramework` module and compiled by its Bazel target;
- `plugins/kotlin/tests-common/test/.../TestDataFile.java`, registered as the
  `intellij.kotlin.common.tests` module and compiled by its separate test target.

The definitions are not accidental copies and even carry different annotation
retention. Atlas currently collapses those JPS modules into the single project
`idea`, so a project-scoped Java index cannot represent both definitions. Filtering
either source or weakening duplicate detection would be incorrect. Module-scoped
JPS identity or an explicit partial/unavailable relational capability is separate,
evidence-required future work and is not implemented here.

The final isolated `idea` run reported the exact conflict after 279.328 seconds
(282.691902 seconds command wall time). It discovered one requested project and
reported `succeeded: no`; the non-gating `analyze` command returned its documented
native exit code 0.

## Final repeated full analysis

Both final commands used the same pinned checkout, active uncommitted Atlas
implementation, `--force`, and `--no-recover`.

| Result | Run 1 | Run 2 |
| --- | ---: | ---: |
| Projects | 119 | 119 |
| Succeeded | 118 | 118 |
| Failed | 1 | 1 |
| Command wall time | 290.424426 s | 245.946183 s |
| Sum of recorded project durations | 287.140 s | 242.578 s |
| `idea` duration | 275.015 s | 230.453 s |
| Decompiler duration | 1.890 s | 1.906 s |
| Native `analyze` exit | 0 | 0 |

Each run surfaced only the same deliberate `DuplicateTypeError` described above;
no other project failed. The project order, project statuses, and exact error pair
are identical. Deterministic hashes are:

| Preimage | SHA-256 |
| --- | --- |
| Human text output (10,488 bytes) | `06c4481c07f409de5822b3985e7e07b836879148d30daf21ec9894458e20d921` |
| Analysis/project order | `572e84e65d0edd96bbfabbe7caf8d9c3d22d57c0d823e3528d9f784747ac0520` |
| Ordered project/status pairs | `dd5a83338f526ba5a09847bcd395d592a85f40072220ce8a46a55f703a103b5c` |
| Ordered failure/error pairs | `f0873a382d564ab0b1ff2fbbb97b9c17e618c520a9e9d37ccc92ee9a4995792e` |
| Portable workspace project definitions | `6ff609870257e3b01392eb20b47ecf8ce29385f09093c89ce584cb129e97735a` |
| Filesystem module hierarchy | `2ba6e6d1a8c3979b0133f4ae5d236e6248e896fe6e79cda3691fdb9ffa4b1b56` |
| Ordered project dependencies | `ec3639e4e4577bba977b9e28d70cde0e87764881089fdfbdafc34a3f8d01d4ee` |

Debug-log files intentionally differ because correlation/event IDs and durations
are operational data. The semantic payload, graph, risk, report, Explain, and
portable-projection hashes remain unavailable rather than being derived from a
failed or older snapshot.

## Snapshot and Explain availability

Because a valid project still fails, the complete workspace correctly does not
publish `.atlas/ass/latest.ass`. Consequently the following are unavailable and are
not fabricated:

- snapshot size and semantic payload hash;
- graph node/edge counts and graph hash;
- hierarchy, workspace, dependency, risk, and repository-report hashes;
- portable projection and replay evidence;
- source-free snapshot validation and Explain Anything quality review.

The actually executed `atlas ai explain .` command reported that the semantic
snapshot was not found and instructed the operator to run snapshot creation first.

## Canonical non-regression

Fresh `--force --no-recover` analyses used the same source-selection implementation.
No benchmark source or accepted golden was modified.

| Corpus | Pinned commit | Result | Wall time | Snapshot bytes | Portable / graph evidence |
| --- | --- | ---: | ---: | ---: | --- |
| Apache Maven | `3e01a12e9eacd2b336f4db786d54e35647ce268c` | 92/92 | 27.121276 s | 33,715,785 | `a591962406d5f5f784d491e025652aa73043478bbacebe52638052181ec8e1f5` / `2df64026aed0e7b76ea471dfb9690374f45937b04a0b5655f3f820badaeaae16` |
| Quarkus | `bbc0853aef94c567bac2cc4a98d51c90fb423648` | 1,442/1,442 | 376.3 s tool wall | 358,304,086 | `9297de564e0a091ffc5e497a40ab238ba33ef904e74973fb0af9f51a117d3943` / `0a0834f8dae5509d9a0b019b2038d982df52e7ed3f609e48937fff7a60aa792f` |
| Spring Framework | `eceebb3077dda9e1b19d73c0398ef022cd91f99c` | 29/29 | 87.070122 s | 146,029,292 | `e73ad3126be2565f7efe99800d6e51f09fbfea530ba174ff21464c2e665762fb` / `9fd1a08e67790d2c7c8d99e407766814928d4eb90778b24463aa6b0e89c748c8` |
| Elasticsearch | `273e03a8a7149170fac16761af3fbf522b52f9fe` | 545/545 | 483.630572 s | 544,047,044 | `f01cddf387c693325511a096dfd43b0a4476036e146292dcfd6d12951c47f416` / `0f06c041c3933c4a6bd0d7cbbd7eb5bb2bc8ababe70e2fb58c881004ba5d07f6` |

Maven and Quarkus match the reviewed corrected-producer portable and graph hashes.
Spring's semantic, portable, repository-report, provider-free Explain, risk, graph,
and project-order hashes match all seven documented diagnostic references exactly.
Elasticsearch matches its documented semantic, portable, report, Explain, risk,
graph, project-order, and deterministic-order gates exactly. This correction does
not silently update the older accepted M1.1 producer goldens.

## Maintainer decision

| Area | Decision | Rationale |
| --- | --- | --- |
| Fixture classification | Keep | Narrow owner-relative boundary plus structured overrides resolves the proven false inputs. |
| Source-root changes | Keep | Bounded Gradle/IML evidence and conventional fallback are deterministic and generic. |
| Ownership changes | Defer | JPS module scoping is real but exceeds this fixture-classification correction. |
| Duplicate detection | Unchanged | The next legitimate conflict remains visible. |
| Tests | Keep | Small fixtures cover exclusion, preservation, safety, fallback parity, and true duplicates. |
| Documentation | Keep | Records both the material improvement and the remaining failure honestly. |
| Benchmark promotion | Defer | No successful full snapshot, portable projection, or replay exists. |

## Eligibility

| Gate | Result | Evidence |
| --- | --- | --- |
| Official pinned Git provenance | Pass | Official origin and immutable commit verified. |
| Stable project count and order | Pass, diagnostic | 119 projects and identical ordering in repeated diagnostic runs. |
| Complete supported project discovery | Unknown | JPS module identity is flattened into the root project. |
| All valid projects analyzed | Fail | `idea` retains one legitimate cross-module duplicate. |
| Original fixture semantics proven | Pass | Both original pairs excluded; registered API Dump sources preserved. |
| Deterministic repeated semantic payload | Unavailable | No successful snapshot. |
| Portable projection | Unavailable | No successful snapshot. |
| Source-free benchmark output | Unavailable | No successful snapshot. |
| Replay eligible | Fail | No retained successful semantic artifact. |
| Performance metadata | Partial | Selector and wall/project durations recorded; peak memory unavailable. |

Final classification: **DIAGNOSTIC ONLY**.

External `.atlas` logs and histories remain operational evidence in the pinned
checkout. They are not committed to Atlas, and no accepted benchmark golden is
changed automatically.
