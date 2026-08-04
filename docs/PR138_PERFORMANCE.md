# PR138 Performance Report

## Measurement boundary

PR138 adds a persisted semantic producer, so normal snapshots are expected to
change. Measurements separate:

- repository analysis and snapshot growth;
- snapshot-only `atlas security` request latency, output, and process working set;
- bounded consolidation scaling;
- compatibility of the existing PR137 request on the same PR138 snapshot.

All production measurements used the frozen 517-file production manifest SHA-256:

```text
ca664d402e8dae3561fdd1dcb720f87dec3cf6ae31a0ea0a64e1dc6681d7c9f6
```

The official repository analyses ran concurrently with other long benchmark jobs.
Their elapsed times are valid observations, but they are not isolated evidence of a
causal performance improvement or regression. Correctness, artifact determinism,
and snapshot-size comparisons are exact.

## Snapshot-only request performance

Five fresh Python processes queried the same Maven snapshot with canonical JSON
output. Every process exited 0, wrote no stderr, returned the same four persisted
findings and nine capabilities, and emitted exactly 63,561 bytes with
SHA-256
`968778ed8d7e802505de5c98f333c0cf544c430d9bb62f09caaa1c0ae4f744db`,
and left the input snapshot byte-identical.

| Run | Wall time (ms) | Peak working set (bytes) |
| ---: | ---: | ---: |
| 1 | 2,802.131 | 216,367,104 |
| 2 | 2,800.219 | 216,358,912 |
| 3 | 2,802.859 | 217,018,368 |
| 4 | 2,807.466 | 216,342,528 |
| 5 | 2,785.150 | 216,100,864 |
| **Median** | **2,802.131** | **216,358,912** |

An opt-in profile corroborated 2,779.952 ms wall time and 216,502,272 bytes external
peak working set. Maximum sampled process RSS was 189,644,800 bytes. Measured phases
were:

| Phase | Duration (ms) |
| --- | ---: |
| Persistence/load | 14.910 |
| Resolver index | 873.327 |
| Subject index | 1,052.235 |
| Query | 13.283 |
| Rendering | 0.631 |
| Serialization | 53.001 |

The figures include Python startup, loading the full semantic snapshot, graph and
resolver reconstruction, and operating-system cache effects; they are not isolated
allocations of the security domain service. The profile sidecar is opt-in and did
not alter semantic output or the snapshot.

## Bounded consolidation scale

A deterministic component measurement exercised the public consolidation boundary
with canonical producer inputs supplied in chunks no larger than the 4,096-finding
producer cap; fixture generation was outside the measured interval. Reversing input
order produced exact object and JSON equality. Category coverage is computed once per
normalized producer set rather than rescanned for every retained finding.

| Retained findings | Evidence records | Build | Serialization | Round trip | JSON bytes |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 1,009 | 0.714539 s | 0.018982 s | 0.895980 s | 3,596,033 |
| 10,000 | 10,009 | 7.222383 s | 0.292352 s | 9.176689 s | 35,824,637 |

The 1,000- and 10,000-finding canonical JSON SHA-256 values were respectively
`4ffc29171a62f04c8ef5b8dbdca7190f34489f9a14e57666b8c7a233cc086c37`
and `7696e3f8a583334594ed413a4c8e84ac3922c63462a77229f9d854a9b50eb996`.
Reversed builds took 0.712560 and 7.305521 seconds and produced the exact same
objects and bytes. A three-report reversed-input case also preserved exact dict/JSON
output, coverage, ordering, and confidence. No pre-PR138 feature-identical scale
harness exists, so these are absolute final measurements rather than an improvement
claim.

The service rejects input work above documented limits, retains at most 10,000
findings per request, caps each producer at 4,096 retained findings, and retains at
most 256 canonical trace locations per finding. Omitted work and truncation remain
explicit.

## Repository observations and snapshot growth

| Repository | PR138 runs (ms) | PR138 median | PR137 snapshot bytes | PR138 snapshot bytes | Growth |
| --- | --- | ---: | ---: | ---: | ---: |
| Maven | 30,616; 30,587; 30,461 | 30,587 | 33,712,720 | 33,803,423 | 90,703 (0.269%) |
| Quarkus | 410,505; 403,473; 408,342 | 408,342 | 358,297,696 | 359,119,410 | 821,714 (0.229338%) |
| Spring | 105,050; 106,647; 104,529 | 105,050 | 146,017,372 | 146,047,923 | 30,551 (0.0209%) |
| Elasticsearch | 604,868; 603,069; 593,395 | 603,069 | 544,065,280 | 546,031,671 | 1,966,391 (0.36142556%) |

Maven produced four retained findings, 13 evidence records, and nine capability
records (eight partial and one not analyzed). Its compact canonical security section
was 63,561 bytes; pretty JSON was 80,261 bytes. Spring produced no finding, nine
evidence records, and the same eight-partial/one-not-analyzed capability distribution;
its compact section was 20,114 bytes and pretty JSON was 26,385 bytes. A zero-finding
result describes only executed producer scope and is never rendered as secure.
Quarkus produced 53 findings (46 secrets and seven path-traversal findings), 62
evidence records, and the same eight-partial/one-not-analyzed capability
distribution. Its compact and pretty security sections were 565,815 and 724,469
bytes respectively; no finding was omitted or truncated.
Elasticsearch produced 287 findings, 296 evidence records, and the same capability
distribution, with zero incompatible capabilities. Its compact security section was
1,228,026 bytes. Strict snapshot reload preserved all 287 deterministic finding IDs.
Its canonical graph contained 355,782 nodes and 388,613 edges.

The expected IntelliJ diagnostic ran twice in 306,732 and 303,292 ms. Both runs
reported the same 118/119 result and exact failure identity, and neither published a
semantic snapshot. No PR138 snapshot-size or security-request measurement is
therefore reported for that unsuccessful workspace.

For Maven and Spring, all 15 persisted semantic sections common to PR137 and PR138
were exact object-equal; only `security_intelligence` was added. The existing
knowledge graph, risk section, repository-report data, ordering, analyzer version,
workspace fingerprint, and history data remained unchanged. The provider-free
default explanation changed additively because it now includes the compact security
section; targeted symbol explanation remained unchanged. Snapshot IDs changed
because the new feature is persisted semantic state.

Raw mean timing comparisons with the earlier PR137 validation were +0.803% for Maven
and +15.158% for Spring. Different concurrent load and small cohort sizes make these
non-controlled observations; no causal regression is claimed. The measured snapshot
growth is far below the 10% planning target on both controlled snapshots. A separate,
isolated cohort would be required to evaluate the 25% cold-analysis and 20% peak-RSS
planning targets causally.

## PR137 compatibility measurement

Detached PR137 code and current PR138 code queried the same final Maven PR138
snapshot with `refactor --no-impact --json`. Both exited 0 and emitted the exact same
2,677-byte Windows-pipe output with SHA-256
`ce7e3c1df04e261937fe45a9a590c48156aee4fabb70705b65caa1f53f278022`.
After canonical LF normalization, both were 2,676 bytes with SHA-256
`023fd332a7eb4ea8704e8ca3afd25a571d0f7ed59aca34e16dd6aa2ad559ed40`.
The snapshot SHA-256 remained
`120b811394109d77c099c1071e9667cd6a3c11a633427ccc401cb9459910a24f`
before and after both queries. Single observed wall times were 1,831.166 ms and
1,618.716 ms; peak working sets were 217,333,760 and 216,739,840 bytes. These prove
functional and byte-output compatibility, not a speed or memory improvement.

There is no feature-identical PR137 `atlas security` command, so PR138 request
latency is reported as an absolute measurement rather than an A/B comparison.

## Performance limitations

- The scale case measures canonical consolidation. In normal Java production,
  every source file that emits findings currently merges and re-normalizes the
  bounded per-project finding set. Positive-dense repositories may therefore pay
  repeated sorting cost before the 4,096-finding producer cap; that path remains to
  be isolated and measured before an optimization is justified.
- Top-level `omitted_finding_count` and `truncated` describe consolidation and
  request selection. Findings omitted by an individual producer are represented by
  its deterministic warning count and standardized limitation rather than silently
  being folded into the response-level counter.
- Snapshot loading and canonical resolver reconstruction dominate the representative
  security request; optimizing them would be shared-platform work and is not widened
  into PR138 without an isolated profile and roadmap scope.
- The existing Java producer is file-local. Project-wide interprocedural analysis
  cannot be added merely to improve coverage without measuring source retention,
  memory, and cross-module identity.
- Security payload size is approximately linear in retained findings and evidence.
  Existing bounds prevent accidental unbounded publication, but a future producer
  with materially larger positive result sets requires another repository-scale
  measurement.
- Repository timing captures overlapped with other benchmark processes. Repeatable
  hashes and sizes are authoritative; timing deltas are observational only.
- The additive Java producer isolates ordinary analyzer exceptions so Java semantic
  analysis can continue with explicit partial coverage. Fatal-resource distinction
  is not separately modeled in this slice and remains a defensive-programming review
  point for the shared analyzer boundary.
