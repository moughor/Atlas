# Spring Portable-Path Hardening and Golden Review

## Decision

**M1.2 REQUIRED.** The portable-path false positive is fixed without weakening the
publication boundary, and two corrected Spring analyses succeed deterministically.
Spring is not promoted in M1.1 because the authoritative Java producer fix changes
accepted Maven and Quarkus semantics. Their goldens remain untouched until a
reviewed M1.2 recapture.

This work started from Atlas commit
`fb2c0956fb0a9bde6a491c6def856b402e1bb51d`. Spring was verified against the
official `https://github.com/spring-projects/spring-framework.git` origin at
`eceebb3077dda9e1b19d73c0398ef022cd91f99c`.

## Failure and provenance

`collect_snapshot_artifacts(..., repository_root=...)` failed while constructing
the portable Spring projection. The exception originated in
`benchmarks/stability_manifest.py` at the call to
`portable_snapshot_payload()` and its final machine-path guard. It reported:

```text
$["semantic_context"]["semantic_graph"]["nodes"][59169]["qualified_name"]
```

The bounded semantic value was:

```text
org.springframework.http.ResponseCookie.Rfc6265Utils#String(newchar[]{'(',')','<','>','@',',',';',':','\\','"','/','[',']','?','=','{','}',' '})
```

The node ID was `method:bef4fdd322a7937c2bc11e76`, its project was
`spring-web`, and it had no direct evidence array. The matching global symbol
provided producer lineage. Its metadata included an impossible return type with
an assignment and initializer-like parameters.

The original semantic concept is a field initialized by a constructor call. The
Java parser previously selected the first top-level opening parenthesis before
checking whether a preceding top-level assignment made the declaration a field.
The Java symbol builder then deterministically serialized the initializer as a
synthetic method. The portable validator independently interpreted the two escaped
backslashes and following quote as the start of a UNC path.

The defect classification is therefore:

- **C — malformed path-like semantic data from the Java producer**; and
- **E — over-broad Windows UNC detection**.

This was not a JSON representation-layer error: the validator inspected the decoded
Python string. It was not a machine path and contained no checkout, username, temp,
or source content. Maven and Quarkus also contained misclassified initializer
symbols, but none contained the singular escaped sequence that triggered the old
UNC branch.

## Portable projection contract

The portable projection is intentionally recursive rather than schema-whitelisted.
It replaces only the verified checkout root, its URI and encoded spellings, and the
path-scoped workspace fingerprint. It preserves every semantic field, scans mapping
keys, values, lists, extension fields, and repeatedly decoded strings, and rejects
remaining machine roots.

| Field category | Backslash allowed? | Absolute path allowed? | Required normalization |
| --- | ---: | ---: | --- |
| Repository-relative path | No in canonical path fields | No | `/` separators; no upward traversal; checkout root becomes `REPOSITORY_ROOT` |
| Java signature or identifier | Yes, as semantic escaping | No machine root | Preserve exact semantic text; apply precise recursive machine-root detection |
| Evidence ID | Only when its producer format permits it | No | Preserve deterministic ID; never embed a machine root |
| Free-form limitation text | Yes | No | Preserve text; recursively reject literal or encoded machine roots |
| Serialized expression | Yes | No machine root | Preserve exact semantic text; do not reinterpret an isolated escape as a path |
| Unknown extension field or key | Yes when non-path text | No | Preserve and recursively scan; unknown fields never bypass validation |

A UNC root now requires a server component, a separator, and a share component.
Actual `\\server\share`, `//server/share`, encoded UNC, device, named-pipe,
drive-root, file-URI, and absolute POSIX values remain prohibited. An incomplete
escape such as the representation of a Java backslash character is not a UNC root.

## Producer and identity corrections

The Java parser now evaluates top-level assignment position before classifying a
member with parentheses. A parenthesis denotes a callable only when it precedes the
assignment. Constructor and factory invocations in field initializers consequently
produce fields rather than synthetic methods.

That correction exposed a valid Java namespace case in Spring: a field and a nested
type can share the same qualified spelling. `JavaSymbolIndex` already retained both,
but `GlobalSymbolDatabase` rejected them. Global identity now remains unique by
project, qualified name, and symbol kind. Exact duplicate symbols are still rejected;
`find_qualified()` exposes all deterministic matches, while the legacy singular
lookup retains a deterministic first match. The semantic collector deduplicates by
the existing kind-aware symbol ID.

No public snapshot schema, graph model, manifest format, confidence model, evidence
model, cache, or semantic pass was added.

PR70 persistent results and PR74 recovery journals now carry an additive analysis-
result producer fingerprint. Legacy schema-v1 payloads remain readable, but their
unversioned results are invalidated instead of being silently reused after this
producer correction. The journal schema number remains unchanged; future semantic
producer changes must advance the explicit fingerprint.

## Security review

The change does not whitelist Spring, a node index, `qualified_name`, Java fields,
or any schema key. The recursive guard still covers:

- mapping keys and values;
- nested sequences and mappings;
- evidence and limitation payloads;
- optional AI narrative fields;
- unknown extension fields;
- repeatedly percent-encoded values.

Focused negative tests retain drive paths with either separator, raw and encoded
UNC paths, device and named-pipe paths, file URIs, temp paths, absolute POSIX paths,
and deterministic nested error locations. Positive tests cover the exact escaped
Spring semantic value, Java and regex escapes, character literals, arbitrary
identifiers, and deterministic JSON round trips.

Residual lexical ambiguity is conservative: generic text that is structurally
indistinguishable from a complete UNC root remains rejected. Quote-adjacent POSIX
forms and punctuation-adjacent drive roots are pre-existing detector limitations and
were not broadened in this narrowly scoped fix.

## Validation

Targeted validation:

```text
79 passed in 0.88s
216 passed in 10.47s
83 passed in 0.88s
122 passed in 1.38s
45 passed in 0.90s
102 passed in 1.45s
56 passed in 0.87s
```

The final full suite after all producer and identity changes reported:

```text
3772 passed, 1 skipped in 24.58s
```

The sole skip was `tests/test_production_review_remediations.py:107` because file
symlinks are unavailable on the Windows host. `compileall` completed, and
`git diff --check` reported only Git's informational LF-to-CRLF conversion warnings.

Two final corrected full Spring runs each discovered and succeeded on all 29
projects. They took 84.677 and 83.150 seconds. The executable runtime was verified to
load the current Atlas worktree, and their portable gates were identical:

| Artifact | SHA-256 |
| --- | --- |
| Semantic payload | `f22b87982d31f381f55c7c709aba822cbf1f7e5883a0f33a865cf7e135a18764` |
| Portable semantic | `e73ad3126be2565f7efe99800d6e51f09fbfea530ba174ff21464c2e665762fb` |
| Repository report | `ba02987b29a45033f6c81aefb33293968ecef72b75c4070dafd991aac1543c40` |
| Provider-free explanation | `a2e43f159f834be5cfa3ef619727299c7f6ea9b3395e9697c1d9ad78890f5a8d` |
| Risk analysis | `03fd2d0d8a746951d98dc0ffa01a5bb033b98c043a90e4583b44b81ab6141abe` |
| Knowledge graph | `9fd1a08e67790d2c7c8d99e407766814928d4eb90778b24463aa6b0e89c748c8` |
| Workspace order | `4586f23aa5d62a65187adc9202a065d332475fa957f38abf67b04d79145658c4` |

Raw snapshot IDs and raw hashes differed because they retain operational history
lineage; raw equality is not the cross-run portable gate. Both raw files were exactly
146,029,292 bytes. The compact portable projection was 100,760,747 bytes. The
canonical graph contained 104,095 nodes and 114,190 edges, and the corrected snapshot
contained zero method return types with an assignment.

## Maven and Quarkus comparison

Fresh analyses remained functionally green and deterministically ordered:

| Repository | Projects | Failures | Analysis time | Order gate |
| --- | ---: | ---: | ---: | --- |
| Apache Maven | 92 | 0 | 24.697 s | unchanged |
| Quarkus | 1,442 | 0 | 357.224 s | unchanged |

Their accepted M1.1 portable hashes do not match the corrected producer output:

| Repository | Artifact | Accepted M1.1 | Corrected producer |
| --- | --- | --- | --- |
| Maven | Portable semantic | `d49835d18719a02f17e2118dcf244d96acac4bbf9d365e3c589fb987df28b66b` | `a591962406d5f5f784d491e025652aa73043478bbacebe52638052181ec8e1f5` |
| Maven | Knowledge graph | `37743e2e5ba29ab0da8164065109aea4f73e0d927b0e02a687232e67b0129669` | `2df64026aed0e7b76ea471dfb9690374f45937b04a0b5655f3f820badaeaae16` |
| Quarkus | Portable semantic | `8c867e8c31fb4203ce7bfb955907dd68c852ec3f1c4dcf9a5f70a1b10372e9b4` | `9297de564e0a091ffc5e497a40ab238ba33ef904e74973fb0af9f51a117d3943` |
| Quarkus | Knowledge graph | `21c47c475718ccd02128c95e2cf64a5ec461c4dbddc2612b4dee381a42b9a122` | `0a0834f8dae5509d9a0b019b2038d982df52e7ed3f609e48937fff7a60aa792f` |

Reports, explanations, and risk hashes also changed because they consume corrected
symbol and graph facts. This is reviewed producer drift, not a validator-only hash
change. The checked-in Maven and Quarkus baselines were not modified.

## Spring eligibility

| Gate | Result | Evidence |
| --- | --- | --- |
| Provenance | Pass | Official origin and exact pinned commit verified |
| Clean initial checkout | Fail | Operational checkout already contains generated `.atlas`; no fresh canonical `prepare` was performed |
| Analysis | Pass | Two corrected runs, 29/29 each |
| Determinism | Pass | All portable semantic/report/explain/risk/graph/order hashes identical |
| Portable projection | Pass | Full recursive projection succeeds; compact size measured |
| Source-free | Pass | Existing source-free projection contract and recursive machine-path guard pass |
| Linked replay | Fail | No accepted Spring fresh manifest exists for canonical replay lineage |
| Performance metadata | Fail | Two diagnostic samples, not a canonical three-sample capture from a fresh initial state |

Spring therefore remains diagnostic until M1.2. A future promotion must create a
fresh checkout through `canonical_baseline prepare`, capture at least three samples
against the exact final Atlas producer commit, review and version the Maven/Quarkus
semantic drift, write the source-free eight-file Spring bundle, and verify linked
replay. The current generated `.atlas` tree and diagnostic artifacts must not be
committed.

## Maintainer review

| Area | Decision | Reason |
| --- | --- | --- |
| Validator fix | Keep | Requires complete UNC structure without allowing generic backslashes |
| Producer fix | Keep | Corrects widespread deterministic field/method misclassification |
| Symbol identity fix | Keep | Represents a legal field/type namespace collision without weakening exact duplicate rejection |
| Recovery fingerprint | Keep | Prevents pre-fix semantic documents from surviving an Atlas upgrade |
| Schema changes | Remove/not applicable | No schema change is required |
| Tests | Keep | Cover the defect, security boundary, identity, round trip, and compatibility |
| Spring golden | Defer | M1.2 recapture and clean canonical lineage are required |
| Documentation | Keep | Records the corrected contract, reviewed drift, and promotion gate |

No temporary diagnostic, broad backslash bypass, repository-specific branch,
accepted-golden update, generated benchmark checkout, or `.atlas` content belongs in
the Atlas commit.
