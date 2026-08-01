# PR132 Risk and Hotspot Analysis

## Purpose

PR132 produces deterministic, evidence-backed repository risk indicators over
the canonical PR129 knowledge graph. A risk indicator prioritizes investigation;
it is not a bug, defect, vulnerability, or prediction that a change will fail.

The semantic snapshot adds one source-free key:

```text
semantic_context["risk_analysis"]
```

Older snapshots remain valid. Consumers must report PR132 as unavailable when
the key is absent.

## Canonical inputs

The normal production pipeline can currently publish:

- relation-scoped canonical graph fan-in and fan-out;
- project inventory bytes;
- project change frequency from a bounded Git history window;
- aggregate change-author concentration from that same Git window.

The pipeline explicitly reports these signals as unavailable unless a structured
producer supplies them:

- code complexity;
- resolved low test density;
- symbol-level size;
- call-specific fan-in and fan-out;
- historical trend.

PR129 `ownership` means structural containment. It is never interpreted as
developer ownership. Repository test-file counts are inventory facts and are
never presented as test coverage or resolved test density.

Project inventory now publishes `inventoried_file_size_error_count`. Structured
inventory bytes participate only when this count is zero. A stat failure makes
that project's size signal unavailable, so missing bytes cannot become a
zero-risk observation. Snapshots predating the completeness field remain
readable and report modern inventory size as unavailable; the legacy `size`
compatibility input remains explicitly partial.

## Risk formula

The configured weights are:

| Metric | Weight |
| --- | ---: |
| Complexity | 0.25 |
| Fan-in | 0.20 |
| Fan-out | 0.15 |
| Change frequency (commits touching a project) | 0.15 |
| Change-author concentration proxy | 0.10 |
| Low test density | 0.10 |
| Size | 0.05 |

Only normalized, evidence-backed observations participate. If the available
metric set is `A`, the score is:

```text
sum(weight[m] * normalized[m] for m in A)
------------------------------------------------
          sum(weight[m] for m in A)
```

The risk score and evidence confidence are independent. Removing an unavailable
factor renormalizes the risk score, while confidence coverage still reflects the
missing configured weight.

The Git factor uses the exact number of commits touching a project in the bounded
repository history window. Text additions and deletions are retained as evidence
detail, but are not silently combined into a second score. Contributor
concentration is the largest author share of project-touching commits in the
same window. It is not ownership, blame share, CODEOWNERS coverage, bus factor,
or developer performance. Contributor identifiers become pseudonymous digests
inside the Git service and are not published in PR132 output; hashing is not an
anonymity guarantee.

## Degree semantics

`KnowledgeGraph.degree_summaries()` collects degrees in a single `O(V + E)`
pass and counts distinct neighbouring canonical IDs. It accepts explicit
relationship, subject-kind, and neighbour-kind filters. Deterministic result
materialization additionally sorts the selected subject IDs.

PR132 uses:

- project `depends_on` edges whose neighbours are projects, declared
  dependencies, or frameworks;
- symbol `imports`, `inheritance`, `composition`, `calls`, and `overrides` edges
  whose endpoints are semantic symbols.

`ownership` and `member_of` are excluded. Evidence multiplicity does not inflate
counts. A missing relationship producer is disclosed as partial coverage; it is
not converted to a zero count for that relationship.

## Cohorts and normalization

Cohorts are exactly:

```text
language=<language>|kind=<canonical-kind>|scope=<scope>
```

Normalization never mixes producers or observation windows. For cohorts
containing at least 20 observations with the same metric, unit, producer, and
window, PR132 uses deterministic average-rank percentiles:

```text
(count(values < x) + (count(values == x) - 1) / 2) / (n - 1)
```

Equal raw values therefore receive equal normalized values. Canonical subject ID
is used only to order genuinely equal final scores. Ranking uses unrounded
normalized and composite values; six-decimal rounding occurs only when results
are published.

For cohorts smaller than 20, the following versioned absolute bands apply. Each
row lists upper bounds producing normalized values `0`, `0.25`, `0.5`, `0.75`,
then `1` above the final finite bound.

| Metric and unit | Finite upper bounds |
| --- | --- |
| Cyclomatic complexity | 1, 5, 10, 20 |
| Fan-in/out distinct neighbours | 0, 1, 3, 7 |
| Commits touching a project | 0, 1, 3, 7 |
| Contributor concentration ratio | 0.25, 0.50, 0.75, 0.90 |
| Low-test-density risk ratio | 0.10, 0.25, 0.50, 0.75 |
| Project inventory bytes | 100,000; 1,000,000; 10,000,000; 100,000,000 |

Small cohorts carry a low-coverage limitation. Cohorts of 20 or more with no
variance also use the documented absolute bands instead of fabricating a
percentile spread. Unsupported units are rejected at the structured producer
boundary and are never normalized by guesswork.

## Structured producer boundary

Optional producers use `RiskMetricInput` and shared `EvidenceRecord` instances.
The accepted units are deliberately narrow: `cyclomatic_complexity`,
`distinct_neighbors`, `commits`, `ratio`, `risk_ratio`, and `bytes`, each only
for its corresponding metric. Evidence records must carry their canonical
deterministic evidence ID; forged or inconsistent IDs are rejected. A coverage
value of zero remains an unavailable observation and cannot enter ranking or a
heatmap. Conflicting producers for the same subject and metric are rejected
rather than resolved by input order.

Producer and window fields are bounded semantic identifiers, not free-form text.

External evidence source references and limitation text are not copied into the
PR132 snapshot. Conclusions cite canonical upstream evidence IDs; when upstream
limitations exist, PR132 publishes only their count and a fixed instruction to
inspect those records. This prevents arbitrary producer text from bypassing the
source-free snapshot boundary.

## Output contract

The schema contains:

- producer, schema, input, graph, configuration, and lineage identities;
- bounded ranked hotspots;
- raw and normalized metric factors, units, windows, cohorts, producers, and
  coverage;
- configured and effective weights and each factor's contribution;
- deterministic confidence and evidence IDs;
- missing signals, limitations, and compatible-history trend;
- capability availability and observation counts;
- aggregated heatmap bins by comparable cohort;
- analyzed, eligible, and excluded scope counts;
- a compact evidence index.

`RiskAnalysisReport.from_dict(report.to_dict()).to_dict()` is exact. Report and
evidence ordering is independent of input order.

Structured output remains bounded even when external producers use many
producer/window identities. Each metric publishes at most 50 heatmap cohorts
and 32 producer identities, selected deterministically; omitted cohort,
subject, and producer counts remain explicit. Aggregate evidence retains at
most 32 upstream references plus its lineage reference.

The feature-local LRU cache key includes the graph digest, selected repository
metadata, source classifications, Git head and window, structured observations,
configuration, producer/schema versions, failed-project set, and compatible
prior-report identity. Cached reports freeze their evidence index, and cache
access is synchronized for shared service instances. The cache is in-memory and
feature-local; no persistent cache is introduced.

## Scope handling

Production subjects are ranked by default. Test, generated, and unknown subjects
are retained in coverage statistics but excluded unless explicitly enabled in
`RiskConfiguration`. A project is production only when its structured inventory
contains non-test source files; an empty aggregator remains unknown rather than
being silently promoted.

Symbol scope first consumes an explicit source classification when available.
Its compatibility fallback recognizes conventional source-root structure such
as `src/test` and `src/testFixtures`; that fallback is path-based, is reported as
a limitation, and deliberately leaves unsupported explicit classifications in
the `unknown` scope.

Repository-summary project counts and symbol fallback classification reuse the
same conventional test-source path helper. A project rooted under a structured
test/sample area is not promoted to production merely because it contains a
conventional `src/main` subtree.

## Complexity heatmap

Heatmaps are compact normalized bucket counts, not copies of graph nodes or
edges. The complexity heatmap is explicitly unavailable until a structured
complexity producer supplies observations. Runtime profiling, name matching,
graph degree, and LLM output cannot substitute for complexity evidence.

## Complexity and performance

- graph digest: streaming deterministic hash;
- degree collection: `O(V + E)`, followed by deterministic selected-ID sorting;
- cohort normalization: deterministic sorting within cohorts;
- top-k selection: `O(V log k)`;
- snapshot output: bounded hotspots plus aggregate heatmaps;
- Git: one bounded repository-wide history command, never one command per file
  or symbol.

No all-pairs graph operation or expensive centrality algorithm is used.
Git file-to-project attribution walks path ancestors from deepest to root; it
does not scan every project for every changed path. Git subprocess output is
decoded explicitly as UTF-8 so behavior does not depend on the Windows locale.

## Public API

`RiskAnalysisService`, `RiskConfiguration`, `RiskMetricInput`,
`RiskAnalysisReport`, the result DTOs, and their enums form the typed PR132
surface. DTOs are immutable and serialize deterministically. `GitHistoryWindow`
and `GitFileChange` are public read-only evidence transports returned by the
existing Git context service; their paths and counts are validated. Canonical
degree summaries remain additive PR129 graph queries.

## Deferred work

- production complexity producers connected at analyzer boundaries;
- resolved test-to-production mappings and coverage evidence;
- symbol span/LOC publication;
- rename-aware long-term Git evolution;
- predictive machine learning;
- developer performance scoring;
- PR133 repository reporting and later roadmap consumers.
