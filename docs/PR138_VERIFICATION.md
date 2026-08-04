# PR138 Verification

## Authoritative scope and baseline

The official Atlas 2.x roadmap assigns **Security Intelligence** to PR138:

> Consolidate existing security analyzers and detect secrets, SQL injection, weak
> cryptography, path traversal, SSRF, XSS, unsafe deserialization, and unsafe
> reflection. Every finding includes semantic evidence.

PR138 therefore begins the roadmap item after PR137; it does not extend the
Refactoring Advisor. The dependency matrix requires the PR129 canonical graph and
the existing security platform, while PR136 impact data is optional enrichment.

The exact baseline was clean `main == origin/main` at
`a7104cdd8b71a103f843fac01a00a1fa57f3a718`. Its documented complete-suite result
was:

```text
4111 passed, 3 skipped in 31.51s
```

The complete Security Intelligence roadmap item requires producer evidence that is
not yet available across every category and language. This implementation is the
smallest independently useful first slice: it runs the existing bounded Java
security adapter while each already-selected source is in memory, normalizes its
structured results, and publishes source-free evidence through the normal semantic
snapshot pipeline. It does not claim that the complete PR138 item is finished.

## Pre-implementation audit and rejected scope

Atlas already owned the Java security rules, specialized taint and policy engines,
the PR129 graph, PR130 evidence and confidence, PR134 subject resolution, PR70/PR74
persistence and recovery, semantic snapshots, AI projections, and M2 measurement.
The missing capability was a normal-pipeline adapter and a canonical, persisted,
queryable security-intelligence projection.

The implementation deliberately rejected:

- a second scanner, taint graph, evidence model, confidence model, resolver, cache,
  or filesystem traversal;
- name-, package-, framework-, graph-, or LLM-based security inference;
- treating missing findings or missing call edges as evidence of safety;
- a name-only XSS rule without an authoritative producer;
- retaining raw source, arbitrary literals, secrets, full taint expressions, or
  producer prose in snapshots or AI context;
- mandatory PR136 impact enrichment, speculative exploitability, automatic fixes,
  runtime testing, or vulnerability feeds;
- unbounded interprocedural or cross-module source retention.

`docs/PR138_EXISTING_CAPABILITIES.md` records the baseline audit and
`docs/PR138_SECURITY_INTELLIGENCE.md` records the implemented contracts and deferred
work.

## Implemented slice

The normal Java analysis path now invokes the existing `JavaSecurityAnalyzer` on
the same in-memory source text that the selected-source loop already read. A
versioned, bounded per-project producer report survives result persistence and
recovery. `SemanticContextCollector` consolidates compatible reports against the
exact PR129 graph lineage and publishes:

```text
semantic_context.security_intelligence
```

The feature-local schema contains explicit capability states, normalized findings,
aggregate coverage, producer lineage, limitations, and a closed PR130 evidence
index. `atlas security` reads only the verified snapshot and supports deterministic
scope, project, language, category, severity, subject, limit, human/JSON, and
profiling behavior. The public facade exposes only the request, report, and service
contracts. The default provider-free repository explanation receives a compact
aggregate section; targeted PR134 symbol explanation remains unchanged.

The producer fingerprint advances from v5 to v6. This makes PR70/PR74 reject
otherwise valid recovered Java results that predate the security producer rather
than silently interpreting them as a successful empty analysis. The top-level
semantic snapshot schema remains version 1, and older snapshots without the new
feature key remain readable.

## Evidence, confidence, and determinism

Every retained finding references a closed set of PR130 `EvidenceRecord` IDs.
Capability evidence also records execution when a compatible producer ran but found
nothing. Evidence identities bind producer and schema versions, snapshot lineage,
project and language scope, normalized semantic location, category and rule,
severity, trace digest/count, limitations, coverage, and the canonical graph digest.
Raw evidence wire types are validated strictly before reconstruction.

A retained canonical subject is re-resolved through PR134 against the exact PR129
graph. Missing or ambiguous identity remains explicit; stale, absent, or
metadata-inconsistent canonical subjects make the feature incompatible rather than
being trusted. The default repository explanation invokes this same
`SecurityIntelligenceService.from_snapshot()` validation before projecting any
present security data; stale graph lineage or stale subject metadata cannot bypass
the service through the AI path. No finding is created from a graph relationship
alone.

The persisted report's graph lineage is compared with the exact serialized PR129
payload via the streaming `KnowledgeGraph.stable_payload_digest()` helper. This is
separate from the PR134 resolver's established normalized query-view digest, so the
fix does not change PR134-PR137 response identity or introduce another graph. A
regression uses deliberately non-lexical edge-evidence order to reproduce the
real-repository mismatch that exposed this boundary.

PR130 `ConfidenceCalculator` derives confidence from compatible producer evidence,
coverage, agreement, and optional exact canonical identity. Severity and review
priority remain separate. Unknown runtime exposure and optional PR136 blast radius
contribute neither favorable evidence nor invented certainty.

Canonical ordering is severity descending, priority descending, category, project,
semantic location, rule ID, and deterministic finding ID. All request filters and
limits are applied over canonical order. Producer reports, findings, evidence,
capabilities, limitations, and serialized object keys are deterministic. Exact
`to_dict()` / `from_dict()` round trips and reversed-input equivalence are tested.

## Test results

In the commands below, `python` was the bundled Python 3.12 runtime at
`C:\Users\MoughorOC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.
The repository `.venv` launcher was not used because its recorded base interpreter
was unavailable in this execution environment.

Final focused command:

```text
python -m pytest -q -p no:cacheprovider \
  --basetemp=.pytest_pr138_final_lineage_focused \
  tests/test_pr129_knowledge_graph.py \
  tests/test_pr134_subject_resolution.py \
  tests/test_pr136_impact_prediction_adversarial.py \
  tests/test_pr137_refactoring_advisor.py \
  tests/test_pr138_cli.py \
  tests/test_pr138_security_ai.py \
  tests/test_pr138_security_intelligence_core.py \
  tests/test_pr138_security_pipeline.py
```

Result:

```text
127 passed in 3.77s
```

The focused suite covers positive normal-pipeline publication, isolated producer
failure, source-read reuse, recovery round trips, category mapping, source-free
redaction, explicit unavailable/partial/incompatible states, zero-finding behavior,
strict evidence replay, graph-lineage and canonical-subject validation, exact
serialization, deterministic reordered input and tie-breaking, bounded work and
traces, scoping and filters, CLI human/JSON output, public facade, compact AI
projection, legacy-snapshot compatibility, and rejection of stale graph or subject
lineage on the default explanation path. It also covers exact streaming PR129 wire
digests with non-lexical evidence order, PR134 resolver compatibility, PR136
adversarial evidence, and preservation of PR137 advice behavior.

Final complete-suite command:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr138_final_lineage_full
```

Result:

```text
4185 passed, 3 skipped in 34.68s
```

The three skips are the existing Windows symlink-capability tests:

- Gradle recursive membership with a source-root symlink;
- internal file-symlink traversal;
- project-indexer file-symlink traversal.

No test failure or warning was reported. `python -m compileall -q moughorai tests`
and `git diff --check` both exited 0.

A post-implementation read-only audit found that the initial default-explanation
projection parsed the feature report directly instead of invoking the snapshot
service's graph-lineage and canonical-subject checks. The AI path was changed to use
the shared validator and the two stale-lineage regressions were added. That validation
then exposed a real production distinction: the PR129 wire graph preserves producer
evidence order, while the established PR134 query view normalizes that evidence.
PR138 now verifies publication lineage against the exact streaming wire digest and
continues to use PR134 independently for subject resolution. The change leaves PR137
output byte-identical. All tests, replay checks, production provenance, and repository
benchmarks reported as final in this document are from the corrected candidate;
earlier pre-fix observations were discarded as delivery evidence.

## Clean replay

A temporary complete patch was generated through an alternate Git index, checked,
and applied to a detached checkout of exact baseline `a7104cdd`. The replayed
focused suite passed:

```text
127 passed in 4.29s
```

The replayed public-API fixture suite also passed `8 passed in 0.31s`. Replay
`compileall` and whitespace checks exited 0. The replay and main worktrees contained
the same 517 production Python files with normalized-content manifest SHA-256
`dd91e3d8f24ffde94eecc7d2d0ad8a0d33a80d064ef932d8663d57692261b25c`;
the raw-byte manifest differs across clean Windows checkouts because Git performs
the configured LF/CRLF conversion. The detached worktree, test state, temporary
patch, and temporary index were removed.

## Repository validation

Official repositories were validated from pinned clean checkouts with forced
analysis, recovery disabled, one worker, fresh Atlas state, and repeated runs. The
uncommitted candidate was guarded by a SHA-256 manifest over all 517 production
Python files. Its digest remained:

```text
ca664d402e8dae3561fdd1dcb720f87dec3cf6ae31a0ea0a64e1dc6681d7c9f6
```

The benchmark adapter changed only the commit-identity assertion so the native M2
harness could validate an intentionally uncommitted worktree; it independently
recomputed and asserted this frozen production digest before and after every run.
Target repository cleanliness, identity, state reset, analysis, artifact capture,
and invalid-snapshot checks remained native.

| Repository | Result | Repeats | Durations (ms) | Snapshot bytes | Determinism |
| --- | ---: | ---: | --- | ---: | --- |
| Apache Maven `3e01a12e` | 92/92 | 3 | 30,616; 30,587; 30,461 | 33,803,423 | exact |
| Quarkus `bbc0853a` | 1442/1442 | 3 | 410,505; 403,473; 408,342 | 359,119,410 | exact |
| Spring Framework `eceebb30` | 29/29 | 3 | 105,050; 106,647; 104,529 | 146,047,923 | exact |
| Elasticsearch `273e03a8` | 545/545 | 3 | 604,868; 603,069; 593,395 | 546,031,671 | exact |

For each completed successful repository, project order, analysis report,
semantic payload, portable projection, repository report, provider-free
explanation, knowledge graph, risk section, snapshot ID, and raw snapshot were
identical across repeats.

| Repository | Raw snapshot SHA-256 | Snapshot ID | Deterministic ordering SHA-256 |
| --- | --- | --- | --- |
| Maven | `120b811394109d77c099c1071e9667cd6a3c11a633427ccc401cb9459910a24f` | `73152f42d58d4e79742fd1acc1126a47315cf71a60d85fbf8a77b94c780fca12` | `903928f5fc4a6a74b4f9b05a4d7a770d23cb2dba2f611aed0ef066b0b7f59d2b` |
| Quarkus | `8c864743ab51d0f39a0241cad11c83a96a30ffe02ae28c76b4a71364ff91eb51` | `4b4c1feaba36b8dd92821833889a3e9e005a150680888ee915d3c705fdc20bdf` | `c1d6476bbf0647e1adf2c0b3d64675980800e686c4b3fcbe12437bbe489a0736` |
| Spring | `087024992896b17d27276a1f932d12f3c6fa4a43d4715007f6603508521094b2` | `f0d730f13c09fdf6b8d005f6d89343917cecbf9d3020625d306e5e4592b3b7e1` | `ca7ed09c10a923c87467a32246ae6e4ee226ddd5064b6b6daee4b83e20d2b1ff` |
| Elasticsearch | `381b7f003d22ad7bc37e65fffb9aa32421915d76505c34dd5fefd8694d04ee78` | `73607df2b18ae04fc66a53c9a5b9fcb33a3282e232a069f63d94faed138c7274` | `d5054bd8e7fe6ab3204856c3cbd45723e57f1fd77b7de256e3dfb3374313e040` |

Maven's report, explanation, canonical graph, and risk hashes were respectively
`72115abe5e382eab546c1d7f852e26949f5661e0366683cd74e9d5aab2236b29`,
`1ece2daeda56270441dfdce3a9d89c494274a3c6dc3e547850a9005b3c9278e2`,
`2df64026aed0e7b76ea471dfb9690374f45937b04a0b5655f3f820badaeaae16`,
and `0808862883caf70711c26edbedb30d6f36735c30f515593cac64370e52d6b71b`.
Spring's corresponding hashes were
`7eb4c19b34532854fa28b6ff02793db34dd985a5df565db290fe3894440120ca`,
`f39fc32ca08125794fb8bc25be9daf4759818297749a4f139413b11e0430f873`,
`9fd1a08e67790d2c7c8d99e407766814928d4eb90778b24463aa6b0e89c748c8`,
and `935e6cfabee62d93b7a77aa746ad2dcf8e86fde776d83427cc5688345daf1b09`.
Quarkus's report, explanation, canonical graph, and risk hashes were respectively
`edfd7e124f6ddc3860acb45d76ec7c30ec445d2fe018a5073d882dae0421133f`,
`62574abe61f2e0f762d978a5319359abdaaaee4fcb8f2def2aedda8f5a50503b`,
`0a0834f8dae5509d9a0b019b2038d982df52e7ed3f609e48937fff7a60aa792f`,
and `bf7b4bf8aaaae6b170d4ec5eae5f51807206801c4e25742a77aac9532134c728`.

Elasticsearch's report, explanation, canonical graph, and risk hashes were
respectively
`3a8fb0ab9eb8466bded6bde559362f0d8d8eaf909b45ee62345cf9c239153269`,
`f60f80151c6aa19245968716abe528530e7ed74b2a6a2ebb02a1d1e074d3ffb1`,
`0f06c041c3933c4a6bd0d7cbbd7eb5bb2bc8ababe70e2fb58c881004ba5d07f6`,
and `03abd6fe26a00fa920399898786d20a8a0fdba7e3541009b99eab01ad57eedd5`.
Its canonical graph contained 355,782 nodes and 388,613 edges.
The all-artifact aggregate was
`6a7bbe94578e8b8bc434ac8a51f88966276047c9c329a0e2aec03c801393af13`.

## IntelliJ accepted diagnostic

IntelliJ Community was validated twice at pinned commit
`6affce35cb2aad82747b36e886836c44e0188e46`. Both native commands exited 0 and
reported 119 projects, 118 successes, and exactly the one documented `idea`
failure. Durations were 306,732 and 303,292 ms. The exact diagnostic was:

```text
DuplicateTypeError: Duplicate Java type 'com.intellij.testFramework.TestDataFile' in project 'idea': C:\b137\idea\platform\testFramework\src\com\intellij\testFramework\TestDataFile.java and C:\b137\idea\plugins\kotlin\tests-common\test\com\intellij\testFramework\TestDataFile.java
```

The two runs had identical analysis-order, project/status, failure/error, and
deterministic-report hashes:

```text
572e84e65d0edd96bbfabbe7caf8d9c3d22d57c0d823e3528d9f784747ac0520
dd5a83338f526ba5a09847bcd395d592a85f40072220ce8a46a55f703a103b5c
9a50086e62cb52c3fdfccc586a7cb14e570275bc70908e20399b6ceef12b2a89
85a6a37dc8404f174c31b039bcc5533fe13fbcdd19bd4cc38cb4ff915233c030
```

Stdout was byte-identical at 41,705 bytes (SHA-256
`997798bdc6436818d21116aa419e15faa4179128a7011b7488f2ce312e60f0dc`).
Stderr was byte-identical at 1,674 bytes (SHA-256
`b3f2488dc3e068ef41b3695dfc4e82df8f48d388beb44e83957acfaa04a4b6b7`)
and contained the same nine repository-owned PyDev invalid-escape
`SyntaxWarning`s. No `latest.ass` or other `.ass` file existed before, between, or
after the failed analyses. PR138 therefore preserves the accepted 118/119
module-identity limitation without disguising it or publishing an invalid snapshot.

## Snapshot and backward compatibility

Controlled PR137/PR138 comparisons on Maven and Spring showed that all 15 common
semantic-context sections are exactly identical. The only added section is
`security_intelligence`; top-level schema version, analyzer version, workspace
fingerprint, and history reference remain unchanged. Snapshot identity changes as
expected because the new producer payload is semantic state.

| Repository | PR137 bytes | PR138 bytes | Increase |
| --- | ---: | ---: | ---: |
| Maven | 33,712,720 | 33,803,423 | 90,703 (0.269%) |
| Spring | 146,017,372 | 146,047,923 | 30,551 (0.0209%) |

Against the documented PR137 Quarkus snapshot size of 358,297,696 bytes, the
PR138 snapshot added 821,714 bytes (0.229338%). Quarkus published 53 findings
(46 secrets and seven path-traversal findings), 62 evidence records, and nine
capabilities. Snapshot reload through the production service preserved all finding
identities and reported no incompatible capability.

Against the documented PR137 Elasticsearch snapshot, PR138 added 1,966,391 bytes
(0.36142556%). Elasticsearch published 287 findings, 296 closed evidence records,
and nine capabilities (eight partial and XSS not analyzed). Strict production
reload preserved every finding identity and reported no incompatible capability;
the compact security projection was 1,228,026 bytes with SHA-256
`d72ca38c4e85f3252657598a68d8068c8ef88d1078cb6b6cbca0aeba9bd8730a`.
The findings comprised 280 secrets, five general-taint findings, and two
path-traversal findings; all other producer-backed categories had zero retained
findings and remained partial rather than being characterized as safe.

The exact PR137 Maven baseline SHA-256 and snapshot ID were
`2f37c4fb3ef25eee7935ad48382b03c0b2c6d7d6403374bee674f796bb402706`
and `792f75ce7e11245bab71c6e885e950eaaa54fedc5e5b0c309df0c0ad57ed89ec`.
The Spring values were
`7520eb1d40312047173df1f8e5a6ab8569dbcbb19125b143e1f3c023b0ef0e01`
and `bca1d73193be957c32912f7ba8d3ce8e971b75bc99b29ea076a43d993042e5b4`.

On the same final Maven PR138 snapshot, detached PR137 and current PR138 each ran
`atlas refactor --no-impact --json` successfully. Both emitted exactly 2,677 bytes
through the Windows pipe with SHA-256
`ce7e3c1df04e261937fe45a9a590c48156aee4fabb70705b65caa1f53f278022`.
Canonical LF normalization produced 2,676 bytes with SHA-256
`023fd332a7eb4ea8704e8ca3afd25a571d0f7ed59aca34e16dd6aa2ad559ed40`,
and neither changed the snapshot. This proves preservation of PR137 request behavior
on the same semantic input.

Existing security findings, reports, CI, SARIF, LSP, incremental-security, taint
policy, framework, and interprocedural APIs are not rewritten. Existing public
exports remain stable; three new feature-local exports are additive. An absent
security key yields an explicit unavailable query result while remaining omitted
from the default explanation, preserving the accepted legacy explanation path.

## Supported and deferred capability

The selected Java adapter can provide bounded evidence for secrets, SQL injection,
weak cryptography, path traversal, SSRF, unsafe deserialization/reflection, and its
existing additional rules. These capabilities remain `partial` where parsing,
dynamic values, intrafile flow, unresolved identity, or selected-source coverage is
incomplete. XSS is explicitly `not_analyzed` because no reviewed authoritative XSS
producer exists.

Still deferred:

- project-wide interprocedural and cross-module/cross-project taint propagation;
- integration of compatible policy-pack, framework, incremental, and symbolic
  refinement producers;
- optional PR136 blast-radius enrichment;
- authoritative non-Java security producers and reviewed XSS evidence;
- exploit execution, penetration testing, vulnerability feeds, and automatic fixes.

Neither the complete PR137 Refactoring Advisor item nor the complete PR138 Security
Intelligence item is claimed complete. No PR139 interactive-chat functionality was
added.
