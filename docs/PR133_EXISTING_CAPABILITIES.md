# PR133 Existing Capabilities and Extension Record

## Scope and authority

PR133 implements the roadmap's AI Repository Report as a deterministic composition
of semantic facts already published by PR127 through PR132. It does not rediscover
repository facts and does not introduce another repository summary, graph, analyzer,
confidence model, evidence model, risk score, or persistent cache.

The PR129 `KnowledgeGraph` remains the canonical repository graph. Specialized
architecture, pattern, reachability, Git, dependency, and risk producers remain
authoritative in their own domains. PR133 selects, relates, and presents their
structured results; it does not replace them.

## Authoritative producer inventory

| Capability | Authoritative producer | Semantic snapshot key | Evidence and confidence boundary | PR133 availability |
| --- | --- | --- | --- | --- |
| Repository identity, inventory, languages, build systems, frameworks, entry-point candidates, project hierarchy, and dependency declaration counts | PR127 `RepositorySummaryService` | `semantic_context.repository_summary` | Deterministic repository metadata. These measurements predate the shared evidence index, and confidence is not applicable. Framework and entry-point data remain scoped candidates rather than adoption or runtime conclusions. | Available or partial when schema version 1 data exists; otherwise unavailable. |
| Architecture candidates, dependency directions, cycles, and classification conflicts | PR128 `ArchitectureDetectionService` | `semantic_context.architecture` | PR128 stores producer confidence and raw evidence records, not PR130 shared confidence results or evidence IDs. Name, hierarchy, and entry-point candidate evidence is insufficient to establish an architecture. A missing cycle is not a covered negative result. | Partial when compatible data exists; unsupported or weak conclusions remain unknown/insufficient. |
| Canonical repository topology and stable identities | PR129 `KnowledgeGraph` | `semantic_context.semantic_graph` | Resolved graph facts and edge trace references. Calls and composition remain unsupported by the normal production pipeline unless an authoritative specialized producer supplies them. | Available for compatible schema version 1 graphs; graph-backed sections become partial when absent or incompatible. |
| Design-pattern findings and pattern capabilities | PR130 `PatternDetectionService` | `semantic_context.design_patterns` | Shared evidence IDs/index, deterministic score/tier, participants, scope, producer lineage, and limitations. Empty findings do not prove pattern absence. | Available by capability; unsupported patterns remain explicitly insufficient. |
| Roots, reachability states, dead-code candidates, and coverage | PR131 `ReachabilityAnalysisService` | `semantic_context.reachability` | Shared evidence IDs/index, deterministic score/tier, project and capability coverage, lineage, and limitations. Both regular findings and `grouped-findings-v1` are compatible inputs. | Normally partial because complete calls and closed-world coverage are not established. Missing calls never prove dead code. |
| Risk factors, hotspots, metric capabilities, heatmaps, and trends | PR132 `RiskAnalysisService` | `semantic_context.risk_analysis` | Shared evidence IDs/index and full deterministic `ConfidenceResult`, with factors, units, cohorts, windows, missing signals, coverage, and limitations. Risk score and confidence remain distinct. | Available or partial when traceable metrics exist. A hotspot is an investigation priority, not a defect or vulnerability. |

The workspace configuration in `semantic_context.workspace` supplies project identity
fallbacks only. Machine-specific absolute workspace roots are not copied into the
PR133 report.

## Components reused by PR133

PR133 reuses:

- `KnowledgeGraph` deserialization, stable digest, kinds, relations, and degree
  summaries instead of rebuilding graph indexes or relationships;
- PR130 `EvidenceRecord`, `EvidenceIndex`, `ConfidenceCalculator`, confidence tiers,
  reliability constants, and deterministic evidence IDs;
- PR130–PR132 producer versions, input fingerprints, graph digests, configuration
  fingerprints, and lineage where available;
- the existing semantic-context collector and Atlas Semantic Snapshot publication
  path;
- the existing deterministic repository explanation projection and Markdown
  renderer, with the PR127–PR132 path retained as the fallback for older snapshots;
- the existing token estimator for deterministic, whole-item context selection.

Selected upstream PR130–PR132 evidence IDs are accepted only when their canonical
records exist in the corresponding upstream evidence index. PR133 creates bounded
derived report evidence that references the authoritative producer facts. It does not
copy complete upstream evidence indexes or source payloads into the report.

## PR133 extension

`RepositoryReportService` publishes one additive object at:

```text
semantic_context.repository_report
```

The initial schema version is `1` and the producer version is `atlas-pr133/1`.
The immutable report contains:

- executive summary;
- architecture;
- repository health;
- strengths;
- weaknesses;
- risks;
- technical debt;
- quality;
- recommendations;
- per-section capability and observation states;
- bounded report items with producer and evidence references;
- one compact evidence index;
- deterministic input, graph, and lineage identities;
- explicit report and selection limitations.

`RepositoryReport.from_dict(report.to_dict()).to_dict()` is the compatibility
boundary for schema version 1. PR133 is additive: snapshots without
`repository_report` remain readable, and the existing PR127–PR132 deterministic
repository explanation remains their fallback.

The default repository-level `atlas ai explain` path can render the persisted report
without an LLM. Targeted subject explanations continue to use the existing detailed
semantic-context path.

## Evidence, confidence, and coverage semantics

Exact inventory and graph measurements use `not_applicable` confidence rather than
inventing certainty scores. Interpretive report items use the shared PR130 confidence
calculator over their traceable report evidence. PR132 hotspot confidence is retained
only when its full serialized shared-confidence result and cited evidence are valid.

Legacy PR128 confidence and the score/tier-only PR130 and PR131 contracts are not
expanded into fabricated support, agreement, or coverage values. Their producer
values may be retained as attributes, while the PR133 interpretation has its own
explicit confidence basis and limitations.

Coverage remains producer-specific:

- inventory counts are not semantic coverage;
- language counts are recognized-extension file counts;
- test-file counts are not test execution, test coverage, or test density;
- architecture dependency analysis lacks a complete eligible-edge denominator;
- pattern capability availability is not proof of pattern absence;
- reachability requires explicit call, root, framework, reflection, generated,
  external-API, CFG, and closed-world coverage;
- unavailable PR132 metrics are excluded rather than scored as zero;
- absence of retained findings is never presented as a covered negative result.

## Explicit partial and unavailable behavior

Every canonical report section is serialized even when it has no supported items.
PR133 distinguishes:

- `available`: the required compatible structured producer data exists;
- `partial`: useful evidence exists but coverage, producer support, or scope is
  incomplete;
- `unavailable`: the producer is absent, incompatible, or has no usable structured
  result;
- `not_applicable`: confidence or a capability does not apply to an exact
  measurement;
- `observed`: a traceable fact or derived interpretation is present;
- `unknown`: evidence is insufficient for a conclusion;
- `not_analyzed`: the required analysis was not present.

Current intentional boundaries include:

- no authoritative generic repository-strength producer;
- no authoritative generic repository-weakness producer;
- no persisted runtime test result or coverage percentage;
- no normal complete call graph or closed-world reachability proof;
- no normal complexity, resolved test-density, or symbol-size producer;
- no supported negative architecture, pattern, reachability, risk, or debt claim
  from an empty finding list;
- no impact or blast-radius analysis before PR136;
- no PR142 general technical-debt score.

Strengths and weaknesses therefore remain explicit unknown/unavailable sections
rather than relabeling inventory facts, risks, reachability candidates, or
architecture conflicts. Technical-debt output is limited to traceable reachability or
structural candidates and is explicitly not the future PR142 engine. Recommendations
are deterministic, bounded investigation prompts linked to retained findings and
prerequisites; they are not autonomous remediation advice.

## Determinism, bounds, and source-free output

The report uses stable item identities, canonical serialization, sorted collections,
bounded top-k selections, and explicit included/omitted counts. Limits apply to
languages, build systems, dependency ecosystems, frameworks, repository areas,
important components, entry points, architecture findings, cycles, pattern types,
hotspots, debt candidates, recommendations, evidence references, and limitations.

Context selection retains whole report items and their citations within a deterministic
token budget. It does not truncate an item into an untraceable statement. The detailed
canonical graph and producer reports remain in their established snapshot keys rather
than being duplicated in `repository_report`.

PR133 output contains semantic metadata, canonical identities, counts, evidence IDs,
and bounded source-free explanations. It excludes raw source code, sensitive Git
author identities, machine-specific absolute paths, timestamps, random IDs, and LLM
prose from deterministic serialization.

## Compatibility and regression risks

- Unknown producer or report schema versions are treated as incompatible and degrade
  only the affected section.
- Older repository summaries without completeness aliases remain partial rather than
  turning missing values into zero.
- PR128 legacy confidence is not relabeled as shared PR130 confidence.
- Missing or unverifiable upstream evidence IDs cannot support retained findings.
- PR131 grouped subject prefixes must remain canonical during expansion.
- A missing PR132 metric lowers coverage and never lowers a risk score by acting as a
  zero observation.
- Default repository explanation must prefer the PR133 report without also rendering
  a duplicate legacy report. Old snapshots continue to use the legacy path.
- Targeted explanation behavior and existing public PR127–PR132 APIs remain unchanged.

## Intentionally deferred

PR133 does not implement:

- PR134 canonical subject resolution or Explain Anything;
- PR135 semantic search;
- PR136 impact prediction or blast-radius analysis;
- PR137 refactoring advice;
- PR138 security intelligence;
- PR139 interactive engineering chat;
- PR141 repository evolution or unsupported trend inference;
- PR142 general technical-debt scoring;
- PR145 knowledge-persistence consolidation;
- PDF or portfolio reporting;
- autonomous remediation;
- persistent report caches, parallel report construction, or a second report/analyzer
  pipeline.

Those capabilities must consume the canonical snapshot facts and extend the PR133
contract incrementally at their roadmap positions.
