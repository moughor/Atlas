# PR133 — AI Repository Report

## Purpose

PR133 adds one canonical, deterministic repository report assembled from facts
already produced by Atlas. It does not rediscover repository structure and does
not introduce another repository summary, graph, evidence model, confidence
model, risk score, or semantic analyzer.

The report consumes, when available:

- the PR127 repository summary;
- PR128 architecture findings;
- the PR129 canonical `KnowledgeGraph` and its deterministic degree summaries;
- PR130 design-pattern findings;
- PR131 reachability and dead-code coverage;
- PR132 risk, hotspot, metric, and trend findings.

Unavailable inputs remain unavailable. The report does not infer a replacement
analysis from names, absent edges, or LLM output.

## Canonical model

The `moughorai.repository_report` package owns the single PR133 report model.
`RepositoryReport` is immutable and contains:

- an input fingerprint, canonical graph digest, and report lineage;
- a producer version and schema version;
- bounded report items;
- the nine canonical sections and their item references;
- a frozen shared `EvidenceIndex`;
- report-level limitations;
- deterministic context-selection metadata.

Each `RepositoryReportItem` records its stable item ID, kind, subject, factual
statement, scope, priority, attributes, capability state, observation state,
confidence basis, producer IDs, evidence IDs, limitations, related items, and
prerequisites. Items are serialized once and may be referenced by more than one
section without copying their payload.

The item capability state is the qualitative report-coverage contract. Exact
measurements do not receive an invented numeric coverage score. Findings retain
the producer's numeric coverage only when a complete shared `ConfidenceResult`
exists; otherwise coverage stays partial, unavailable, or insufficient.

`RepositoryReportSection` retains its total, included, and omitted item counts.
Every canonical section is present exactly once, including sections whose
analysis is unavailable.

The model provides deterministic `to_dict()`, `from_dict()`, canonical JSON, and
stable-digest behavior. It rejects unsupported schemas, non-canonical evidence,
missing item or evidence references, inconsistent counts, non-finite values,
and machine-specific absolute paths.

Every retained PR133 evidence record is bound to its citing report item, PR133
producer version, and report lineage. The frozen report evidence index contains
exactly the records cited by retained items; foreign, cross-subject, and
unreferenced records are rejected.

## Sections

The report has nine sections in a fixed order.

1. **Executive summary** — repository identity, project and inventory scale,
   canonical graph scale, bounded degree-based important components, languages,
   build systems, framework or related-technology metadata, module hierarchy,
   declared dependency records, and entry-point candidates.
2. **Architecture** — evidence-calibrated PR128 conclusions, dependency-cycle
   findings, classification conflicts, and bounded PR130 pattern findings.
3. **Repository health** — inventory completeness, classified test-source
   inventory, and PR131 reachability coverage. Test-source presence is not
   promoted to test execution or coverage.
4. **Strengths** — explicitly unavailable until an authoritative structured
   strength producer exists. Inventory presence, patterns, and absence of
   findings are not promoted to strengths.
5. **Weaknesses** — explicitly unavailable until an authoritative structured
   weakness producer exists. Risks, reachability candidates, and architecture
   conflicts stay in their evidence-scoped sections.
6. **Risks** — bounded PR132 hotspots with upstream confidence, factors,
   evidence references, missing signals, and limitations. A risk indicator is
   not presented as a bug, defect, or vulnerability.
7. **Technical debt** — bounded, evidence-backed dependency-cycle and PR131
   reachability candidates. This is not the future PR142 Technical Debt Engine.
8. **Quality** — available inventory, reachability, and PR132 metric-capability
   observations, with unavailable runtime test results, coverage, complexity,
   or test-density signals stated explicitly.
9. **Recommendations** — deterministic investigation prompts derived only from
   retained structured findings. Every recommendation links to its source item
   and lists prerequisites; it is not autonomous remediation advice.

## Capability and observation states

Capability and conclusion state are separate contracts.

Capability states are:

- `available` — the required structured producer and evidence are available;
- `partial` — useful structured evidence exists but coverage or required signals
  are incomplete;
- `unavailable` — the required producer or evidence is absent or incompatible;
- `not_applicable` — the capability does not apply to the reported item.

Observation states are:

- `observed` — the statement is supported by cited structured evidence;
- `unknown` — the available evidence cannot establish the conclusion;
- `not_analyzed` — the relevant structured analysis did not run or is absent.

Missing evidence never becomes a zero value, a clean bill of health, or proof
that an issue is absent. A covered negative conclusion is permitted only when an
authoritative producer records that the check ran with sufficient coverage.

## Evidence and confidence

PR133 reuses the PR130 shared evidence and confidence contracts.

- PR127–PR129 facts receive deterministic report evidence records that refer to
  their structured snapshot fields or canonical graph relationships.
- PR130–PR132 findings retain references to their upstream evidence IDs and
  producer identities through bounded source references.
- Evidence IDs are derived from normalized evidence content and report lineage.
- Exact measurements use the `not_applicable` confidence basis rather than an
  invented probability.
- Findings preserve valid upstream confidence or use the shared deterministic
  calculator when PR133 must calculate confidence for a report interpretation.
- Missing required roles produce `insufficient`; an LLM cannot add evidence or
  change confidence.

The report evidence index contains only records referenced by retained items.
It does not copy complete PR130–PR132 evidence indexes or the canonical graph.

## Determinism and rendering

The service normalizes and orders inputs before assigning IDs, selecting top-k
facts, creating evidence, and serializing the report. Report identity includes
the facts that affect emitted items as well as the canonical graph digest.
There are no timestamps, random identifiers, machine-specific roots, or external
LLM prose in the canonical payload.

The default repository explanation uses `RepositoryReportRenderer`. The renderer
is presentation-only: it does not derive findings, calculate confidence, fill
missing sections, or call an LLM. It renders the selected canonical items once
and uses compact references when an item belongs to multiple sections. Snapshot
metadata is escaped before it is emitted as Markdown.

## Token-budgeted context selection

`RepositoryReportContextSelector` is the first consumer of the shared
token-budgeted context-selection capability. Its default budget is **7,000
estimated input tokens** using the existing deterministic Atlas token estimator.

The selector:

- always preserves the section envelope and capability states;
- treats repository identity, repository scale, and canonical graph scale as
  mandatory items;
- orders optional items by explicit priority and stable item ID;
- selects the longest fitting priority prefix;
- keeps whole items rather than truncating statements or citations;
- includes only evidence records referenced by selected items;
- preserves related-item prerequisites;
- records exact included and omitted counts and its final token estimate.

If the mandatory envelope cannot fit, selection fails explicitly rather than
silently discarding identity or evidence.

## Bounded and source-free output

The stored report is a compact projection, not another repository database.
Current producer bounds include:

- 10 languages and 10 build systems;
- 10 dependency ecosystems and 12 framework or technology names;
- 12 major repository areas and 10 important graph components;
- 12 entry-point candidates;
- 12 architecture findings, 5 cycles, and 12 members per cycle;
- all 11 PR130 pattern types;
- 10 risk hotspots, 10 technical-debt candidates, and 10 recommendations;
- 3 representative upstream evidence references per item;
- 4 item limitations and 5 section limitations.

Totals and omitted counts remain visible when details are excluded. The report
does not serialize complete symbol tables, graphs, project inventories, source
files, raw source text, Git author identities, or absolute filesystem paths.
Embedded absolute paths are rejected at the report boundary.

## Snapshot integration

The report is published additively at:

```text
semantic_context["repository_report"]
```

Its current contracts are:

```text
schema_version: 1
producer_version: atlas-pr133/1
```

The ASS envelope and semantic-context schema remain backward-compatible. The
report is built after PR132 from the same semantic context and the existing PR129
graph; it does not trigger another analysis or Git query.

Snapshots created before PR133 remain readable. When the key is missing,
malformed, or incompatible, default explanation marks the canonical report as
unavailable and falls back to the accepted bounded PR127–PR132 repository
projection. It does not reinterpret missing PR133 data as an empty report.
Machine-specific absolute paths are omitted from this compatibility projection.

## AI Explain behavior

`atlas ai explain` remains the roadmap-defined interface; PR133 does not add a
second report command.

- The default `workspace` or `repository` request loads the persisted report,
  applies the deterministic 7,000-token selector, and renders Markdown without
  constructing or calling an LLM provider.
- A targeted `--subject` request preserves the existing ASS-grounded provider
  path. Targeted narrative output does not replace the canonical PR133 facts.
- Both paths retain existing conversation-memory and snapshot-reference
  behavior.
- `atlas ai context` exposes the structured `repository_report` key for tools
  that require machine-readable output.

## Limitations and deferred work

- Per-project workspace-run completion evidence is not persisted in replayed
  snapshots; snapshot presence alone is not reported as project-level coverage.
- Runtime test results and coverage percentages are unavailable unless a future
  authoritative producer persists them.
- PR128 conclusions remain limited by their evidence; weak name or hierarchy
  candidates stay unknown or insufficient.
- Canonical call and composition edges remain unavailable where no authoritative
  producer populated them.
- Framework metadata can be project-local, test/sample, documentation,
  optional-integration, or build-tooling evidence and does not establish
  repository-wide adoption by itself.
- PR132 trends remain unavailable without a compatible prior structured report.
- Rich technical-debt prioritization belongs to PR142.
- Optional LLM narrative generation, PDF output, portfolio reports, autonomous
  remediation, and unsupported trend claims are intentionally deferred.
- PR134 Explain Anything remains separate and must consume snapshots and the
  canonical graph rather than depending on a generated report narrative.
- The PR133 token selector applies to the default repository report. Explicit
  targeted explanations retain the pre-PR133 full-ASS prompt path for backward
  compatibility; subject-aware bounded selection is deferred to PR134. Very large
  targeted snapshots can therefore remain expensive until that capability exists.

## Measured performance

The delivery benchmark uses five repeats and records median/p95 latency, snapshot
bytes, canonical graph size, deterministic hashes, process peak working set, and
optional peak Python allocations. Snapshot loading and graph deserialization are
excluded from report build timings.

| Input | Graph | Build median / p95 | Selection p95 | Snapshot growth |
| --- | ---: | ---: | ---: | ---: |
| Synthetic 10K | 10,001 nodes / 19,999 edges | 0.171 s / 0.192 s | 0.024 s | 0.665160% |
| Apache Maven replay | 22,427 nodes / 25,254 edges | 0.221 s / 0.249 s | 0.032 s | 0.572907% |
| Quarkus replay | 149,048 nodes / 167,850 edges | 1.599 s / 1.616 s | 0.020 s | 0.030312% |

The synthetic 10K run measured 18,170,749 bytes of peak traced PR133 allocations
and a 201,580,544-byte process peak working set. Process peak working set includes
the benchmark fixture and canonical graph, so it is not interpreted as PR133-only
growth. The Maven and Quarkus process peaks were 427,560,960 and 3,788,746,752
bytes respectively. The benchmark accepts up to one million synthetic projects;
100K and 1M synthetic runs were not executed for this delivery. The real Quarkus
replay supplies the measured 149K-node large-repository case.
