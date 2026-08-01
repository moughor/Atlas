# PR133 Verification Report

## Roadmap compliance

PR133 implements the roadmap-defined AI Repository Report. It composes bounded,
source-free facts already produced by PR127 through PR132 and does not introduce
another repository graph, semantic analyzer, evidence model, confidence model,
or repository model. PR129 remains the canonical repository graph. PR134 and
later roadmap capabilities are not included.

The implementation reuses the PR127 repository summary, PR128 architecture
findings, PR129 canonical `KnowledgeGraph`, PR130 evidence and confidence
contracts, PR131 reachability findings, PR132 risk findings, the existing
semantic snapshot store, and the existing AI explanation command.

## Capability status

| Report section | Status | Authoritative inputs |
| --- | --- | --- |
| Executive summary | Available when compatible PR127 and PR129 data are both present | Repository summary, workspace metadata, and canonical graph counts |
| Architecture | Partial or unavailable | Traceable PR128 findings and bounded PR129 degree summaries |
| Repository health | Partial | Exact available PR127 through PR132 measurements; missing analyses remain unavailable |
| Strengths | Unavailable | No authoritative positive assessment producer exists |
| Weaknesses | Unavailable | No authoritative negative assessment producer exists |
| Risks | Partial or unavailable | Traceable PR132 risk findings and their deterministic confidence |
| Technical debt | Partial | Traceable PR128 cycles and conservative PR131 dead/unreachable candidates only |
| Quality | Partial | Capability and coverage facts; no invented quality score |
| Recommendations | Partial | Evidence-backed follow-up actions capped by their source confidence |

Every retained report item cites evidence owned by the PR133 report lineage.
Upstream evidence is verified before projection. Missing, incompatible, or
unsupported capabilities remain explicit rather than becoming negative claims.

## Determinism, bounds, and compatibility

- Report and selection serialization have exact `to_dict()` / `from_dict()`
  round trips.
- Reordered equivalent inputs produce identical reports, fingerprints, evidence
  IDs, and selected output.
- The default repository explanation renders the persisted PR133 report without
  invoking an LLM provider or duplicating the legacy projection.
- Selection is deterministic, uses a strict 7,000-token budget, retains whole
  report items and their evidence closure, and records exact omitted counts.
- Report sections, items, limitations, evidence references, graph summaries, and
  rendering are bounded.
- Snapshots predating PR133 remain readable through the accepted PR127 through
  PR132 fallback and explicitly report report availability.
- Snapshots and AI projections contain no raw source. Absolute filesystem paths
  are rejected or removed from fallback projections.
- Explicit subject explanations retain their pre-PR133 provider-backed behavior.

## Tests executed

The focused PR133 suite was executed after the final production changes:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr133_focused10 tests/test_pr133_repository_report.py
25 passed in 0.72s
```

The related PR114 and PR120, PR127 through PR133, and AI explanation regression
tests were executed after the final hardening changes:

```text
python -B -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr133_related_final3 tests/test_ai_explain_accuracy.py tests/test_pr114_explain_engine.py tests/test_pr120_atlas_ai_release.py tests/test_pr127_repository_summary.py tests/test_pr128_architecture_detection.py tests/test_pr129_knowledge_graph.py tests/test_pr130_design_patterns.py tests/test_pr131_reachability.py tests/test_pr132_risk_hotspots.py tests/test_pr133_repository_report.py
141 passed in 3.66s
```

The first requested unqualified full-suite invocation could not provide a valid
suite result because Windows denied access to pytest's global temporary root:

```text
python -m pytest -q
PermissionError: [WinError 5] Access is denied:
  C:\Users\MoughorOC\AppData\Local\Temp\pytest-of-MoughorOC
exit code: 1
```

This was an environment setup failure during `tmp_path` fixture creation, not a
passing test run. A full retry with a repository-local base temporary directory
completed, but its final terminal summary was lost by tool-output compaction, so
no result is claimed for that invocation. To retain auditable evidence, the
complete suite was run with an isolated base directory and JUnit output:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr133_full_delivery_retry --junitxml=.pr133_full_suite.xml
3575 passed, 1 skipped in 14.57s
exit code: 0
```

`python -m compileall moughorai` completed successfully. `git diff --check`
reported no whitespace errors; Git emitted only LF-to-CRLF conversion notices.

## Synthetic scale measurement

The deterministic synthetic benchmark was executed five times with a 10,000
project fixture. Snapshot loading and graph deserialization are excluded from
report build timings.

| Measurement | Result |
| --- | ---: |
| Canonical graph | 10,001 nodes / 19,999 edges |
| Build median / p95 | 0.170746 s / 0.192375 s |
| Selection p95 | 0.024203 s |
| Baseline snapshot | 11,795,506 bytes |
| PR133 projected increase | 78,459 bytes (0.665160%) |
| Peak traced allocations | 18,170,749 bytes |
| Process peak working set | 201,580,544 bytes |

All five report, selected-report, and projected-snapshot hashes were stable.
The report hash was
`0c3c60ef07bcc64a67bed4e1cbe14bfcfe7fb355049b9013165c9335e4d3dd59`.
A 100,000- or 1,000,000-project synthetic run was not executed and is not
claimed; Quarkus provides the measured 149,048-node large-repository case.

## Apache Maven validation

The normal Atlas pipeline was freshly executed against Apache Maven:

```text
atlas analyze C:\AITest\maven-master\maven-master --force --no-recover
projects: 92
succeeded: yes
```

All 92 projects succeeded with zero failed projects. The verified snapshot
contained a canonical graph with 22,427 nodes and 25,254 edges. Five report
replays were deterministic:

| Measurement | Result |
| --- | ---: |
| Build median / p95 | 0.221151 s / 0.248989 s |
| Selection p95 | 0.031860 s |
| Baseline snapshot without PR133 report | 30,976,244 bytes |
| PR133 projected increase | 177,465 bytes (0.572907%) |
| Process peak working set | 427,560,960 bytes |

The stable report hash was
`0da6de7d4ce5059f7ea4386e5912b532c64753007072585e467756b01b79524f`.

## Quarkus validation

The existing checksum-verified Quarkus semantic snapshot was replayed. It
records 1,442 projects and contains a canonical graph with 149,048 nodes and
167,850 edges. Five report replays were deterministic:

| Measurement | Result |
| --- | ---: |
| Build median / p95 | 1.598552 s / 1.615733 s |
| Selection p95 | 0.019823 s |
| Baseline snapshot without PR133 report | 336,858,088 bytes |
| PR133 projected increase | 102,140 bytes (0.030312%) |
| Process peak working set | 3,788,746,752 bytes |

The stable report hash was
`6f658e5a13729da9aa20eb26ce9dd29681e3b99d869351f2a3a3b48f9d0ada5e`.
This is a verified snapshot replay; a fresh Quarkus analysis was not executed
for this delivery and is not claimed.

## Deliberate limitations and deferred work

- The report does not fabricate strengths, weaknesses, impact analysis,
  blast-radius analysis, historical trends, or absent quality measurements.
- Risk indicators remain investigation priorities, not defects or
  vulnerabilities.
- Technical-debt output is limited to existing traceable PR128 and PR131
  evidence; richer prioritization remains PR142 work.
- The default repository report is token bounded. Explicit targeted explanation
  still serializes the pre-PR133 full semantic context for compatibility;
  subject-aware bounded selection belongs to PR134 and can remain expensive for
  very large snapshots.
- Optional LLM narrative generation, PDF output, portfolio reports, autonomous
  remediation, and later roadmap analyses are intentionally deferred.
- Feature-local report composition remains consolidated in its service module.
  Extracting speculative shared infrastructure before a second real consumer
  would conflict with Atlas engineering principles.

No PR134 or later functionality was implemented.
