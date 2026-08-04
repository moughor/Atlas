# PR138 Deterministic Security Intelligence

## Scope

PR138 consolidates findings produced by Atlas's existing security platform. It does
not introduce a second scanner, taint graph, call graph, confidence model, evidence
model, subject resolver, repository model, or cache.

The first independently useful slice is deliberately narrow: selected Java source
files are analyzed by the existing intraprocedural Java security adapter during the
normal language-analysis pass, and the resulting project artifacts are consolidated
into compact, source-free security intelligence. This slice supports available
intrafile evidence for secrets, SQL injection, weak cryptography, path traversal,
SSRF, unsafe deserialization, and unsafe reflection.

Additional findings already emitted by the selected Java adapter are retained under
`general_taint`. That broad category preserves existing structured evidence; it does
not claim that deferred policy-pack, framework, symbolic, or interprocedural engines
executed.

The following remain explicitly outside this slice:

- XSS detection;
- project-wide interprocedural taint integration;
- cross-module and cross-project taint propagation;
- PR136 blast-radius enrichment;
- non-Java security analysis;
- automatic fixes, exploit execution, runtime penetration testing, and vulnerability
  feeds.

Those capabilities are `not_analyzed` or deferred, never inferred from names or an
absence of findings. The full PR138 roadmap item therefore remains partial after this
slice.

## Roadmap relationship

The authoritative roadmap assigns Refactoring Advisor to PR137 and Security
Intelligence to PR138. This slice therefore begins the next official roadmap item; it
does not continue PR137. PR137's cycle-backed advisor remains its deliberately narrow
first slice, and implementing PR138 does not make the wider PR137 extraction,
simplification, package-movement, or modularization objectives complete.

## Architecture

The production flow is:

```text
normal workspace and source-root selection
  -> selected Java source read by JavaLanguageAnalyzer
  -> existing JavaSecurityAnalyzer on the same in-memory text
  -> versioned per-project producer artifact
  -> normal recovery-compatible result encoding
  -> PR129 KnowledgeGraph and PR134 project resolution
  -> PR138 source-free consolidation
  -> shared PR130 evidence and confidence
  -> additive semantic_context.security_intelligence
  -> deterministic CLI and compact AI projection
```

Security analysis does not trigger another filesystem traversal. It does not retain
source after the existing Java source boundary. The canonical graph supplies identity
and context; it does not replace the specialized taint producer or reinterpret a
missing canonical `calls` edge as safety evidence.

## Query and presentation contracts

`atlas security [ROOT]` loads a verified semantic snapshot and never invokes workspace
discovery or a source analyzer. It supports repository, single-project, and canonical
symbol scopes; repeatable project, language, category, severity, and canonical-subject
filters; deterministic result limits; human or canonical JSON rendering; optional
priority-component detail; and opt-in M2 measurement. Symbol scope requires at least
one canonical subject ID, and project scope requires exactly one project.

The version-1 public facade exports `SecurityIntelligenceRequest`,
`SecurityIntelligenceReport`, and `SecurityIntelligenceService`. Existing security
publications remain separate and backward compatible. The new service can consolidate
compatible producer artifacts during snapshot creation or answer requests from the
already published feature section.

The provider-free default `atlas ai explain` path renders a compact aggregate
Security Intelligence section. It includes status, total and included finding counts,
category states, included severity and confidence summaries, evidence-reference
counts, and fixed limitation counts or wording. It does not include finding IDs, rule
IDs, project IDs, paths, remediation details, source text, literals, or large symbol
lists. The internal AI projection retains at most 12 findings before aggregation and
at most 20 categories. Before compaction, the repository projector loads the feature
through `SecurityIntelligenceService.from_snapshot()` so graph lineage and every
retained canonical subject receive the same validation as CLI and public-service
queries. Stale or incompatible data degrades explicitly and cannot bypass that
validation through the AI path. Targeted PR134 symbol explanations are unchanged.

## Capability states

Every taxonomy category has an explicit state:

- `analyzed`: an identified compatible producer ran for the stated language and
  scope;
- `partial`: the producer ran but coverage, resolution, truncation, or identity is
  incomplete;
- `not_analyzed`: no compatible producer ran for that category and scope;
- `incompatible`: producer data exists but its schema or lineage cannot be trusted.

An analyzed category with zero findings means only that the bounded producer emitted
no finding for its executed scope. It must not be rendered as "safe", "secure", or
"no vulnerability exists". Missing calls, dynamic values, unsupported statements,
unresolved targets, parser warnings, and scope truncation reduce coverage or produce
explicit limitations.

XSS is `not_analyzed` in this slice because Atlas currently has no authoritative XSS
producer. Project-wide interprocedural, cross-module, non-Java, and optional PR136
coverage is recorded through fixed limitations rather than inferred from empty
results.

## Finding envelope

Each consolidated finding contains only bounded semantic facts:

- deterministic finding ID;
- roadmap category and original rule ID;
- authoritative severity;
- canonical subject when one exact project/language/path match exists, plus project
  and language scope;
- source-free semantic-location identity and bounded position metadata when safe;
- producer and producer schema version;
- bounded trace-location metadata when the producer supplied it;
- shared confidence result;
- evidence IDs;
- CWE and OWASP classifications;
- limitations and capability scope.

Approved remediation summaries may be added only while building a bounded AI
projection from `SecurityKnowledgeBase`; they are not stored as finding prose or code
examples.

Legacy finding fingerprints remain unchanged in the existing security APIs. At the
new snapshot boundary PR138 retains only a one-way SHA-256 correlation reference,
then derives a separate finding ID from normalized producer identity, lineage,
project, category, rule, and semantic location. Neither the raw path-bearing legacy
fingerprint nor a producer-controlled literal becomes a source reference.

Compatible producer findings merge only when project, language, category, rule ID,
relative path, line, and column are identical. Different projects, languages, paths,
or positions remain separate findings. Within one merged identity, severity and
legacy-confidence disagreement is reported explicitly; the highest authoritative
severity is retained and every producer keeps its structured evidence reliability.
Input order never selects a winner silently.

## Evidence and identity

PR138 reuses the shared evidence contract:

- `EvidenceRecord` identifies the specialized producer result;
- `EvidenceIndex` deduplicates and closes every retained finding's evidence IDs;
- every capability state, including a zero-finding analyzed state, references one
  aggregate execution-evidence record rather than relying on an empty finding set;
- persisted report lineage is checked against the exact PR129 serialized graph with
  `KnowledgeGraph.stable_payload_digest()`. This streaming check does not construct a
  competing graph and does not replace the PR134 resolver's established query-view
  digest;
- source references contain canonical IDs and one-way specialized-result IDs, never
  raw source or secret material;
- finding IDs cover project, language, category, rule ID, relative path and position,
  producer versions, snapshot lineage, optional canonical subject, and the closed set
  of supporting evidence IDs;
- evidence is rejected or downgraded when lineage, schema, project identity, or
  source-free validation fails;
- raw evidence JSON must use the canonical serialized types; coercible booleans,
  numbers, incomplete records, and non-string detail values are rejected before the
  shared evidence parser can normalize them;
- every retained canonical subject is re-resolved through the indexed PR134 resolver
  against the exact PR129 graph digest when a snapshot is loaded. A missing or
  metadata-inconsistent subject makes the published security section incompatible.

Producer evidence records separately retain observed and eligible scope counts,
severity, legacy-confidence reliability, trace count, and source-free location
identity. A bounded merged-trace digest binds retained trace locations to that
evidence. Capability evidence binds state, coverage, projects, languages, producer
versions, source-file and finding counts, limitations, and request scope to a
one-way reference for its producer inputs. Because evidence IDs participate in the
finding and report contracts, changes to those structured facts cannot replay under
the old evidence identity and no producer prose is included.

Current legacy Java findings do not contain a reliable canonical method or type ID.
The first slice resolves a subject only when the canonical graph contains one unique
candidate with the same project, language, and exact project-relative path (or its
workspace-relative suffix). Ambiguity or absence stays unresolved. It must not
manufacture a member identity from a class name, rule name, or line number. A later
producer may supply a canonical member ID additively.

Paths and names can help locate already established evidence, but they cannot prove a
security conclusion. A canonical graph relationship supplies context only when its
edge has authoritative traceable evidence. Missing canonical call data lowers
coverage and never proves that a flow is impossible.

## Confidence

PR138 uses `ConfidenceCalculator`; it does not translate the legacy `Confidence`
enum directly into an unreviewed numeric score.

The compatible executed producer result is the required evidence role. Exact
canonical-subject evidence is optional because a valid producer finding must survive
unresolved or ambiguous repository identity. Structured analyzer evidence uses the
producer's mapped reliability. Finding confidence combines that evidence support,
the exact observed-to-eligible producer-scope ratio, severity agreement across merged
evidence, and optional canonical evidence specificity. Missing or ambiguous canonical
identity remains visible and cannot increase specificity. Producer warnings,
limitations, truncation, missing calls, and omitted reports make capability or report
coverage partial or unknown; they are not silently converted into per-finding proof.

Confidence is separate from severity and priority. An incomplete analysis can retain
a critical producer severity while carrying insufficient confidence or partial
coverage. An LLM cannot create, raise, or lower confidence.

## Priority and ordering

The first slice computes a bounded review-priority score, not an exploitability or
safety probability. Its components are authoritative severity, structured trace
completeness, and exact canonical scope; runtime exposure and PR136 impact remain
unavailable components with zero contribution and explicit limitations. The score
is normalized over available component weights and reports its coverage separately.
Findings are ordered deterministically using:

1. descending authoritative severity;
2. descending priority score;
3. category;
4. project and semantic location;
5. rule ID and deterministic finding ID.

Exploit prerequisites, runtime exposure, ownership, public reachability, and PR136
blast radius are recorded as unavailable unless a compatible producer supplies them.
They are not assigned favorable default values. PR136 enrichment is deferred and is
never required to preserve a base security finding.

## Source-free boundary

The semantic snapshot and AI projection may contain canonical identities, fixed rule
and taxonomy identifiers, aggregate counts, line/column positions, one-way location
IDs, evidence IDs, confidence components, limitations, CWE/OWASP references, and
approved remediation prose.

They must not contain:

- source text, comments, or arbitrary literals;
- a discovered secret or credential value;
- raw taint expressions or source fragments;
- absolute machine paths, usernames, hostnames, or private remotes;
- the path-bearing legacy fingerprint as a citation;
- safe or unsafe remediation code examples from `SecurityKnowledgeBase`;
- provider or LLM prose presented as evidence.

Unsafe upstream text is omitted or makes the affected finding incompatible. Redaction
must happen before deterministic ID construction so sensitive input cannot be encoded
indirectly into retained details.

## Additive snapshot contract

The first slice adds one feature-local object:

```text
semantic_context.security_intelligence
```

Its schema is independently versioned and contains capabilities, compact findings,
aggregate coverage, evidence records, producer lineage, and limitations. It does not
change the top-level semantic snapshot schema.

Older snapshots without this key remain valid and produce an unavailable security
capability when queried through `SecurityIntelligenceService` or `atlas security`.
The default repository projection instead omits the new section when the key is
absent, preserving the accepted pre-PR138 provider-free explanation byte-for-byte. A
present but malformed or unsupported feature value is reported explicitly as
incompatible or unavailable. These cases do not invalidate unrelated repository
summary, architecture, graph, risk, search, impact, or refactoring data.

PR138 advances the PR70/PR74 analysis-result producer fingerprint from v5 to v6
because recovered Java semantic documents must contain the new producer artifact.
Valid v5 results are invalidated and recomputed rather than being accepted as an
empty successful security analysis. This recovery invalidation is separate from ASS
compatibility: existing semantic snapshots remain readable and the top-level
semantic snapshot schema stays unchanged.

Because this is a new semantic producer, new snapshots deliberately receive a new
snapshot identity and semantic-payload hash. Existing accepted goldens must not be
silently rewritten. Verification compares every pre-PR138 section separately and
requires it to remain identical while recording the exact new section and total size
delta.

## Determinism and bounds

- Projects, capabilities, findings, evidence, limitations, and producer records use
  canonical sorting.
- Finding and evidence IDs derive only from normalized semantic inputs.
- Worker completion order, timing, Python hash order, and LLM output never participate
  in semantic identity.
- Every model provides an exact `to_dict()` / `from_dict()` round trip.
- A producer retains at most 4,096 findings and 256 trace locations per finding;
  producer projection rejects more than 100,000 input findings in one bounded pass.
- Consolidation retains at most 10,000 producer reports, rejects eligible retained
  finding work above 100,000, rejects producer-report input work above 100,000,
  and returns at most 10,000 findings per request. Exact duplicate reports and
  repeated classification metadata are deduplicated deterministically. Merged
  traces retain the canonical first 256 unique locations and report the exact
  omitted count. Truncation and omitted counts are explicit and deterministic.
- The default explanation aggregates at most 12 selected findings and 20 categories.
- Full taint paths, source values, prompts, and answers are not persisted.
- Isolated producer failure leaves the affected scope partial or unavailable and does
  not fabricate an empty successful analysis.

## Compatibility

PR138 is additive. Existing `SecurityFinding`, `SecurityReport`, security CI,
baseline, SARIF, LSP, incremental-security, taint-policy, framework, and
interprocedural APIs retain their behavior. The consolidation adapter consumes their
structured outputs and does not rewrite them.

PR129 remains the canonical repository graph. Specialized security and taint models
remain authoritative in their domains. PR134 remains the canonical resolver. PR130
remains the evidence and confidence owner. No PR139 interactive-chat behavior is
introduced.

## Rejected alternatives

- A second security scanner or taint graph duplicates existing engines.
- Reconstructing security conclusions from canonical graph names, framework names,
  dependencies, semantic-search hits, or LLM text lacks authoritative flow evidence.
- Treating missing calls or findings as negative evidence is unsafe.
- Running `RepositorySecurityScanner` inside semantic collection duplicates
  filesystem discovery, source selection, and reads.
- Copying legacy reports or knowledge entries directly into snapshots crosses the
  source-free boundary and lacks canonical lineage.
- Retaining or rereading all Java source merely to enable project-wide
  interprocedural analysis has unmeasured memory and I/O cost and is deferred.
- Adding a name-only XSS sink would not meet the evidence requirement.
- Making PR136 mandatory conflicts with the roadmap dependency matrix.
- Persisting complete taint paths, prompts, or generated explanations creates
  unnecessary snapshot growth.

## Performance and validation targets

The planning targets in `PERFORMANCE_TARGETS.md` are:

- security-summary snapshot growth at or below 10 percent;
- cold-analysis time growth at or below 25 percent;
- PR-level peak RSS growth at or below 20 percent.

These targets require measurement; they are not assumed. A controlled validation
uses the clean PR137 commit and PR138 candidate on the same pinned repositories,
runtime, checkout paths, worker count, and fresh-state protocol. Existing semantic
sections, project counts, order, and failures are correctness gates before timing.

A bounded component benchmark should reuse structured PR38, PR39, and PR45 scenarios,
perform a warm-up, retain at least five samples, record process RSS and scoped Python
allocation distinctly, and verify exact output hashes. The current M2 instrumentation
records Java security production inside the existing Java parsing phase and records
workspace consolidation separately as `security_intelligence.consolidation`; it does
not claim an independently isolated per-file producer phase. A second independent
batch is required before treating an observed performance candidate as a regression.

There is no feature-identical PR137 security request, so PR138 request performance is
reported as absolute load, resolution, consolidation, and rendering observations.
It must not be described as an improvement over a nonexistent command. Old accepted
snapshots exercise deterministic unavailable behavior; positive behavior requires a
real producer artifact or a new PR138 snapshot.

## Remaining PR138 work

- add a reviewed XSS rule to an existing authoritative engine;
- integrate project-wide interprocedural taint without duplicate source reads or
  unbounded retained source;
- establish true cross-module and cross-project taint propagation;
- integrate compatible policy-pack, framework, incremental, and symbolic-refinement
  results;
- add optional PR136 blast-radius context without changing base findings;
- add authoritative non-Java security producers;
- extend the compact aggregate AI security review only as additional structured
  facts become available;
- measure and, only if justified, optimize security analysis at repository scale.

Until those producers and measurements exist, their capabilities remain explicitly
unavailable or partial. Exact test and benchmark results are intentionally recorded
only in the final verification and performance reports; this architecture document
does not claim results.
