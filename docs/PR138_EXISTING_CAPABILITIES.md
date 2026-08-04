# PR138 Existing Capabilities

Status: pre-implementation audit for the first roadmap-compliant PR138 slice.

Implemented-state note: this document intentionally preserves the baseline observed
before implementation. The PR138 candidate now runs the existing Java security
adapter inside the selected-source loop, persists a versioned source-free producer
artifact through PR70/PR74, consolidates it with PR129/PR130/PR134 infrastructure,
publishes `semantic_context.security_intelligence`, and exposes snapshot-only CLI,
public-facade, and compact default-explanation consumers. The analysis-result
producer fingerprint is now v6, so otherwise valid v5 recovered results are
invalidated and recomputed. Executed Java categories are reported as `partial` when
the fixed file-local producer limitation applies; the table's `analyzed` wording
describes producer execution for its selected intrafile scope, not complete
repository coverage. The category limitations and deferred engines recorded below
still apply. Additional rules emitted by the selected Java adapter are preserved
under `general_taint`; this does not imply that deferred policy, framework, symbolic,
or interprocedural producers ran. This remains a partial PR138 slice, not completion
of the full roadmap item.

Statements below that describe what Atlas "currently" lacks refer to the
pre-implementation audit point, not to the implemented candidate.

## Authority and scope

The official roadmap defines PR138 as **Security Intelligence**. It requires Atlas
to consolidate its existing security platform and cover secrets, SQL injection,
weak cryptography, path traversal, SSRF, XSS, unsafe deserialization, and unsafe
reflection with semantic evidence.

`ROADMAP_DEPENDENCY_MATRIX.md` makes PR129 and the existing security platform the
required inputs. PR136 impact is optional enrichment. `PR138_DESIGN.md` additionally
requires explicit analyzed and not-analyzed states, source-free output, deterministic
evidence and confidence, and continued authority of specialized taint analysis.

The complete roadmap item is larger than one safe integration change. The first
slice documented here is intentionally partial. It integrates bounded per-file Java
security results into the normal analysis and snapshot pipeline. It does not claim
that PR138 is complete.

## Existing components

| Responsibility | Existing owner | Reuse in the first slice |
| --- | --- | --- |
| Canonical repository identity and relationships | PR129 `KnowledgeGraph` | Associate a finding with its uniquely resolved project; never construct another graph |
| Shared evidence and confidence | PR130 `EvidenceRecord`, `EvidenceIndex`, and `ConfidenceCalculator` | Produce traceable evidence and deterministic confidence without a second model |
| Canonical subject resolution | PR134 `CanonicalSubjectResolver` | Resolve project identities and preserve ambiguity rather than selecting the first match |
| Optional blast-radius context | PR136 `ImpactPredictionService` | Deferred; it is not required to create or validate a security finding |
| Intraprocedural security rules | `security_analysis.SecurityAnalyzer` | Remain authoritative for findings produced by their executed rule set |
| Java security adapter | `java_security.JavaSecurityAnalyzer` and `JavaSecurityParser` | Run against an already selected Java source while its text is in memory |
| Interprocedural taint | `interprocedural_taint.InterproceduralTaintAnalyzer` | Preserved but not integrated in the first slice |
| Data-flow policy evaluation | `taint_policy.TaintPolicyEngine` and policy packs | Preserved but not integrated in the first slice |
| Framework-specific taint | `framework_models.FrameworkAwareAnalyzer` | Preserved but not integrated in the first slice |
| Incremental Java security | `incremental_security.IncrementalJavaSecurityScanner` | Preserved; its cache is not reused as semantic-snapshot storage |
| Module discovery and aggregation | `multi_module_security.MultiModuleSecurityScanner` | Preserved; it is not a cross-module taint engine |
| Security taxonomy and remediation | `security_knowledge.SecurityKnowledgeBase` | Reuse fixed metadata and remediation text through a source-free projection |
| Existing delivery surfaces | security CI, SARIF exporter, and security LSP | Remain compatible and continue consuming legacy `SecurityFinding` values |
| Operational measurement | M2 `MeasurementSession` | Measure security analysis and consolidation without affecting semantic identity |

The existing security platform is not currently part of the normal `atlas analyze`
semantic pipeline. `JavaLanguageAnalyzer` parses selected Java sources but does not
run the security adapter, and `SemanticContextCollector` does not collect a security
artifact. Existing semantic snapshots therefore have no PR138 security-intelligence
producer contract. Missing data in those snapshots is unavailable, not evidence that
the repository is safe.

## Current category coverage

The table distinguishes an existing producer from first-slice production support.
An `analyzed` state means that the named producer actually ran for the reported Java
scope. It never means that every runtime behavior was proven safe.

| PR138 category | Existing reliable producer | First-slice state | Limitation |
| --- | --- | --- | --- |
| Secrets | `SecurityAnalyzer` literal and credential-assignment checks | `analyzed` for selected Java files | Bounded to patterns understood by the existing producer; secret values are never retained |
| SQL injection | Existing Java taint rules | `analyzed` for supported intrafile flows | No first-slice interprocedural or cross-project flow coverage |
| Weak cryptography | Existing direct API and algorithm checks | `analyzed` for supported Java calls | Dynamic algorithm selection remains unresolved |
| Path traversal | Existing Java taint rules | `analyzed` for supported intrafile flows | Missing or unresolved calls do not prove safety |
| SSRF | Existing Java taint rules | `analyzed` for supported intrafile flows | Network reachability and runtime destination policy are not modeled |
| XSS | No existing authoritative rule or knowledge entry | `not_analyzed` | A name-only output-sink rule would not satisfy the evidence contract |
| Unsafe deserialization | Existing Java taint and direct API rules | `analyzed` for supported intrafile flows | Dynamic dispatch and project-wide type constraints remain partial |
| Unsafe reflection | Existing Java taint rules | `analyzed` for supported intrafile flows | Reflective targets and unresolved values remain unknown |
| General taint and existing additional rules | Existing command, XXE, configuration, framework, and policy producers | Producer-specific or deferred | They are not silently promoted into a complete PR138 category claim |

There is no production-supported XSS conclusion in the current repository. XSS must
remain `not_analyzed` until a reviewed rule is added to an existing authoritative
security engine and is covered by resolved source-to-sink evidence.

The current multi-module scanner builds module order and aggregates independent
module reports. It does not propagate taint through calls across module boundaries.
Cross-module and cross-project taint therefore remain not analyzed in the first
slice, despite the existence of module-level aggregation.

## Evidence and model gaps

Legacy `SecurityFinding` values are suitable for their existing CI, SARIF, and LSP
consumers but cannot be copied directly into a semantic snapshot:

- their fingerprint contains a path rather than snapshot and canonical-subject
  lineage;
- they do not carry a producer version or an evidence index;
- traces and messages can contain source-shaped names or locations;
- security-knowledge remediation includes safe and unsafe code examples;
- unresolved and depth-bounded paths are not a closed-world proof;
- exact strict `from_dict()` round trips are not defined for the complete report.

PR138 therefore needs a narrow adapter around existing results. It must not replace
the legacy types or alter their established fingerprints.

## Selected production boundary

The smallest normal-pipeline integration point is the existing selected-Java-source
loop in `JavaLanguageAnalyzer`:

1. workspace and Java source-root selection remain authoritative;
2. each selected source is read once by the existing Java analyzer;
3. the existing `JavaSecurityAnalyzer` examines the same in-memory text before it is
   released;
4. no second repository walk or content read is introduced;
5. a versioned project artifact records the executed language/scope, analyzed file
   count, warnings, and authoritative findings;
6. PR70 result encoding preserves that artifact across recovery;
7. `SemanticContextCollector` consolidates the artifacts only after the PR129 graph
   exists, so canonical identity is resolved rather than guessed.

This boundary avoids using `RepositorySecurityScanner` in semantic collection. That
scanner owns its existing standalone CI behavior, but its independent recursive walk
and source reads would duplicate workspace discovery and source selection.

## Compatibility and regression risks

- Existing security APIs, fingerprints, CI decisions, SARIF, and LSP diagnostics must
  remain unchanged.
- Older snapshots without `security_intelligence` must continue to load and report
  the capability as unavailable.
- A failed or unsupported producer must not disappear into an empty-success result.
- Project ambiguity must suppress canonical association rather than choose a subject
  nondeterministically.
- Raw secrets, literals, source text, absolute paths, provider prose, and remediation
  code examples must not cross the snapshot or AI boundary.
- Findings and capabilities must not depend on hash iteration, filesystem completion
  order, timing, or worker completion order.
- Additional Java parsing work can be material on large repositories and must be
  measured before the slice is accepted.
- Adding the new semantic-context field deliberately changes snapshot identity and
  size; unrelated existing sections must remain semantically identical.

## Benchmark and fixture status

Atlas has focused security tests with small inline programs for legacy security,
Java parsing, interprocedural taint, policies, incremental reuse, modules, knowledge,
CI, and LSP behavior. It does not currently have a dedicated security benchmark
fixture or security corpus.

The first slice therefore requires a bounded component benchmark built from existing
structured test scenarios and the normal repository benchmark protocol. It must not
add a new large repository merely for PR138.

At the pre-implementation audit point, no tests or benchmarks had been executed for
the proposed slice. Final measured results belong in the separate verification and
performance reports.
