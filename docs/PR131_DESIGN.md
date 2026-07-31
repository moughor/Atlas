# PR131 — Dead Code and Reachability Analysis

## Status

Design draft.

PR131 extends the Atlas 2.x repository intelligence platform with deterministic dead-code and reachability analysis.

The implementation must reuse the PR129 canonical knowledge graph and existing specialized control-flow, entry-point, framework, and call-graph evidence. It must not create a competing repository graph, duplicate existing analyzers, or treat missing relationships as proof that code is unreachable.

PR131 produces structured reachability states, confidence scores, evidence records, limitations, and coverage information suitable for later consumers such as PR132 Risk Analysis, PR133 Repository Reports, PR136 Impact Prediction, PR137 Refactoring Advisor, and PR139 Interactive Engineering Chat.

---

# 1. Goal

Determine which repository symbols are reachable, potentially reachable, unused, or likely dead while preserving uncertainty and framework-specific behavior.

PR131 must distinguish between:

* statically reachable code;
* statically unreachable code;
* unused but externally callable code;
* reflection-discovered code;
* framework-managed code;
* Service Loader-discovered code;
* annotation-generated or generated code;
* test-only reachable code;
* code for which reliable reachability evidence is unavailable.

The result must use confidence and explicit limitations rather than unsupported binary decisions.

---

# 2. Non-Goals

PR131 does not:

* delete code;
* modify repository sources;
* generate automatic patches;
* replace existing control-flow or call-graph analyzers;
* infer runtime behavior using an LLM;
* claim that missing call edges prove dead code;
* resolve every form of reflection;
* perform dynamic runtime instrumentation;
* replace PR137 Refactoring Advisor;
* replace PR138 Security Intelligence;
* introduce a new general-purpose graph model;
* classify public APIs as dead solely because no internal caller exists.

---

# 3. Existing Capabilities to Reuse

Before implementation, the PR record must identify the concrete existing Atlas components used for:

* canonical symbol identities;
* project, package, module, type, method, and field ownership;
* repository and project entry points;
* inheritance and override relationships;
* dependency relationships;
* existing control-flow graphs;
* existing call graphs;
* framework detection;
* annotation metadata;
* generated-source detection;
* test versus production classification;
* Service Loader metadata;
* workspace snapshots;
* semantic evidence;
* shared confidence calculation;
* cache and invalidation behavior.

PR131 must extend these components through adapters or consumers where necessary.

A component may be replaced only when a demonstrated limitation prevents compatible extension.

---

# 4. Architectural Position

PR131 consumes:

* PR129 canonical `KnowledgeGraph`;
* repository and project entry-point evidence;
* existing control-flow information;
* existing framework detection results;
* generated-source metadata;
* test/production classification;
* optional authoritative specialized call graphs;
* optional annotation, reflection, and Service Loader evidence.

PR131 produces:

* reachability roots;
* reachability paths where available;
* per-symbol reachability findings;
* repository and project coverage;
* confidence scores;
* evidence references;
* limitations;
* aggregated dead-code candidates.

PR131 must not modify the PR129 graph.

Specialized call-graph evidence remains authoritative within its own domain. PR131 may adapt specialized graph subjects to canonical subject IDs, but it must not copy those calls into a second competing repository graph.

---

# 5. Core Principle

Absence of evidence is not evidence of absence.

A symbol with no known incoming call is not automatically dead.

Atlas must first consider:

* public API exposure;
* framework lifecycle;
* dependency injection;
* reflection;
* serialization;
* Service Loader discovery;
* annotation processing;
* generated-code contracts;
* native integration;
* test-only usage;
* external consumers;
* unsupported language or project scopes;
* incomplete call-graph coverage.

When reliable evidence is missing, Atlas must report reduced coverage or an unknown state instead of claiming unreachable code.

---

# 6. Reachability Model

## 6.1 Reachability states

Each analyzed symbol receives one primary state.

### `reachable`

The symbol is reachable from at least one accepted root through reliable semantic relationships.

Examples:

* application entry point to method call;
* test entry point to test helper;
* framework entry point to managed component;
* Service Loader provider declared in repository metadata.

### `reachable_test_only`

The symbol is reachable from test roots but not from known production roots.

This state must not be presented as dead code.

It may later be consumed by risk, refactoring, or reporting features.

### `externally_reachable`

The symbol has no known internal reachability path but is externally callable or part of an exposed API contract.

Examples:

* public API type in a published module;
* public extension interface;
* exported package member;
* plugin interface intended for third-party implementations.

This state must not be treated as dead code without stronger evidence.

### `framework_managed`

The symbol is discovered, instantiated, or invoked by a recognized framework contract.

Examples may include:

* dependency-injection components;
* framework controllers;
* lifecycle hooks;
* event handlers;
* framework configuration classes;
* test-engine extensions;
* persistence entities;
* serializers or deserializers.

This state requires framework-specific structural evidence. Names alone are insufficient.

### `reflection_discovered`

The symbol is referenced through reliable reflective metadata or a resolved reflective target.

Examples:

* a constant class name passed to a recognized reflective API;
* configuration metadata naming a type;
* annotation metadata that causes reflective discovery;
* framework registration metadata.

Unresolved or dynamic reflection must reduce coverage rather than automatically marking every candidate reachable.

### `service_loader_discovered`

The symbol is registered through a supported Service Loader mechanism or equivalent provider configuration.

The provider declaration, implementation identity, and service contract should be traceable.

### `generated_or_annotation_managed`

The symbol is generated, consumed by generated code, or participates in an annotation-processing contract that cannot be represented by ordinary static calls.

Examples:

* generated source roots;
* annotation processor outputs;
* generated factories;
* generated serializers;
* generated dependency-injection bindings.

### `conditionally_reachable`

The symbol is reachable only under a build profile, optional dependency, feature flag, plugin configuration, platform, or environment condition.

The condition must be recorded in evidence or limitations where available.

### `unused`

No usage has been identified in the analyzed scope, but Atlas cannot establish that the symbol is unreachable.

This is a weaker conclusion than `likely_dead`.

Typical reasons:

* public or protected visibility;
* incomplete call graph;
* possible external consumers;
* unsupported reflective behavior;
* generated or native integration uncertainty.

### `likely_dead`

Strong evidence indicates that the symbol is not reachable from known roots and is not protected by any recognized external, framework, reflection, generated, Service Loader, or compatibility contract.

This state must require sufficient coverage and confidence.

### `unreachable`

The symbol is proven unreachable within a bounded semantic scope.

This state should be reserved for cases where the relevant control-flow or reachability domain is complete enough to support the conclusion.

Example:

* statement or block unreachable within a fully analyzed method CFG;
* private method in a closed type with complete incoming-call evidence and no reflective or framework contract.

Repository-wide symbols should rarely receive this state unless coverage is demonstrably complete.

### `unknown`

Atlas cannot determine reachability because required evidence is absent, incompatible, stale, or unsupported.

Unknown is preferable to false certainty.

---

## 6.2 State ordering

Reachability states are not a simple severity scale.

For presentation and aggregation, the following grouping should be used:

### Confirmed live

* `reachable`
* `reachable_test_only`
* `externally_reachable`
* `framework_managed`
* `reflection_discovered`
* `service_loader_discovered`
* `generated_or_annotation_managed`
* `conditionally_reachable`

### Needs review

* `unused`
* `unknown`

### Dead-code candidates

* `likely_dead`
* `unreachable`

Only `likely_dead` and `unreachable` may appear in the default dead-code candidate list.

---

# 7. Analysis Subjects

PR131 should support findings for:

* project;
* package;
* type;
* method;
* constructor;
* field;
* statement or basic block where existing CFG evidence permits it.

The first implementation may prioritize:

1. methods and constructors;
2. types;
3. fields;
4. statement-level unreachable code when authoritative CFG evidence already exists.

PR131 must not delay the entire feature solely because one subject kind lacks complete support.

Unsupported subject kinds must be declared unavailable.

---

# 8. Reachability Roots

## 8.1 Required root categories

PR131 must derive roots from structured repository evidence.

Potential roots include:

* executable application entry points;
* test entry points;
* build-tool entry points;
* framework-managed entry points;
* public API surfaces;
* exported package members;
* Service Loader providers;
* plugin registrations;
* reflection-resolved targets;
* annotation-generated entry points;
* native or external integration declarations where supported.

Each root must include:

* canonical subject ID;
* root category;
* project scope;
* evidence IDs;
* producer version;
* limitations;
* confidence.

---

## 8.2 Public API roots

Public visibility alone must not automatically make every symbol reachable.

Atlas should distinguish:

* public symbol in an internal implementation package;
* public symbol in an exported or published API module;
* public symbol that implements a public extension contract;
* public symbol in test code;
* public symbol in generated code.

Public API analysis should reuse build, module, publication, dependency, and package metadata where available.

When external API exposure cannot be determined, public and protected symbols should normally be classified as `unused` or `unknown`, not `likely_dead`.

---

## 8.3 Test roots

Test roots must be analyzed separately from production roots.

The report should preserve:

* production reachability;
* test reachability;
* combined reachability.

A symbol used only from tests should receive `reachable_test_only`.

This distinction will later support risk and technical-debt analysis without mislabeling test utilities as dead.

---

# 9. Reachability Relationships

PR131 may traverse only relationships supported by reliable evidence.

Potential relationships include:

* direct calls;
* constructor calls;
* inheritance;
* overrides;
* interface implementation;
* ownership;
* module dependencies;
* framework registration;
* annotation-managed usage;
* Service Loader registration;
* reflective target resolution;
* generated-code linkage;
* field or parameter typed usage where relevant;
* control-flow successor edges.

Traversal rules must be relationship-specific.

For example:

* inheritance alone does not prove that an implementation is instantiated;
* typed usage alone does not prove runtime invocation;
* ownership does not prove reachability;
* a framework annotation may establish a managed root only when supported by a recognized framework contract;
* an unresolved reflective call must not create a synthetic call edge.

---

# 10. Call-Evidence Boundary

The canonical PR129 graph supports call relationships in its model, but production `calls` edges may not be populated.

PR131 must distinguish:

1. canonical call relationships that are actually present;
2. call relationships supplied by an authoritative specialized call graph;
3. scopes where no reliable call evidence exists.

The report must expose call-evidence coverage per:

* repository;
* project;
* language;
* subject kind;
* production or test scope.

When reliable call evidence is unavailable:

* call-dependent conclusions receive reduced confidence;
* missing calls are never interpreted as proof of dead code;
* private closed-scope analysis may still proceed when other authoritative evidence is sufficient;
* the report must state that dead-code coverage is partial.

---

# 11. Framework-Managed Code

Framework evidence must be structural and producer-backed.

A framework-managed conclusion may use:

* recognized annotations;
* framework configuration metadata;
* lifecycle interface implementation;
* registration APIs;
* module descriptors;
* dependency-injection bindings;
* framework-specific semantic analyzers.

Names such as `Controller`, `Service`, `Repository`, `Handler`, `Listener`, or `Component` are not evidence by themselves.

Each supported framework integration must declare:

* framework identifier;
* supported discovery mechanisms;
* required evidence;
* confidence contribution;
* known unsupported behaviors.

Unrecognized frameworks must reduce confidence and coverage rather than silently producing dead-code findings.

---

# 12. Reflection

## 12.1 Resolved reflection

Reflection may establish reachability when Atlas can resolve a target deterministically.

Examples:

* literal fully qualified class name;
* class literal;
* constant string propagated to a known reflective API;
* structured configuration naming a canonical symbol;
* supported framework metadata.

The evidence must preserve the reflective mechanism and source reference.

## 12.2 Unresolved reflection

Dynamic or unresolved reflection should produce a limitation such as:

> Dynamic reflection is present in this scope, but its targets could not be resolved.

Depending on scope, unresolved reflection may:

* reduce confidence;
* prevent `likely_dead`;
* produce `unknown`;
* preserve `unused` as a review state.

PR131 must not mark the entire repository reachable merely because some unresolved reflection exists. The uncertainty should be scoped as narrowly as evidence permits.

---

# 13. Service Loader and Plugin Discovery

PR131 should recognize supported provider registration mechanisms.

For Java Service Loader, evidence may include:

* `module-info.java` `uses`;
* `module-info.java` `provides ... with`;
* `META-INF/services`;
* known build-generated provider metadata.

The analysis should connect:

* service contract;
* provider implementation;
* registration source;
* consuming module where known.

Registered providers should be `service_loader_discovered` or `conditionally_reachable`, depending on available consumer evidence.

A missing internal call must not make a registered provider dead.

---

# 14. Generated and Annotation-Managed Code

Generated code must be identified using existing repository summary and source classification metadata.

PR131 should distinguish:

* generated symbol;
* source symbol consumed by generated code;
* annotation-processing contract;
* unknown generated linkage.

Generated code may be excluded from default dead-code candidate lists while remaining present in the full report.

The report must preserve whether a finding concerns:

* production source;
* test source;
* generated source;
* vendored or external source;
* unsupported source.

---

# 15. Confidence Model

PR131 reuses the shared confidence calculator introduced in PR130.

It may extend the calculator only when a concrete PR131 requirement cannot be represented by the existing contract.

Confidence must remain:

* deterministic;
* bounded between `0.0` and `1.0`;
* evidence-based;
* source-free;
* reproducible;
* independent of LLM inference.

---

## 15.1 Confidence inputs

Potential confidence dimensions include:

### Root coverage

How completely roots are known for the relevant scope.

### Call coverage

How complete and reliable call relationships are.

### Framework coverage

Whether detected frameworks have supported lifecycle and registration models.

### Reflection coverage

Whether reflective targets are resolved or unresolved.

### Visibility and API exposure

Whether the symbol is private, package-local, protected, public, exported, or published.

### Scope closure

Whether Atlas can treat the analyzed project or module as a closed world.

### Evidence agreement

Whether multiple independent evidence sources support the same conclusion.

### Contradiction

Whether evidence suggests both unused and externally or framework reachable behavior.

### Generated-code uncertainty

Whether generated or annotation-managed relationships may exist outside the static graph.

### Language support

Whether the language analyzer provides the required semantic evidence.

---

## 15.2 Suggested confidence tiers

PR131 should reuse the shared tier thresholds unless the shared model specifies otherwise:

* `high`: score greater than or equal to `0.8`;
* `medium`: score greater than or equal to `0.6`;
* `low`: score greater than or equal to `0.4`;
* `insufficient`: missing required evidence or score below `0.4`.

A symbol must not become `likely_dead` when confidence is insufficient.

---

## 15.3 Dead-code threshold

The initial default should be conservative.

A `likely_dead` finding should require:

* no path from accepted production roots;
* no path from accepted test roots, unless test-only dead code is explicitly requested;
* no public API or external exposure protection;
* no supported framework-managed evidence;
* no resolved reflection evidence;
* no Service Loader evidence;
* no generated or annotation-managed protection;
* sufficient call or closed-scope evidence;
* confidence at least `0.8`.

A medium-confidence candidate should normally remain `unused`.

---

# 16. Evidence Model

PR131 reuses the PR130 semantic evidence model.

Every finding must reference deterministic evidence IDs.

Potential evidence kinds include:

* root declaration;
* call edge;
* constructor call;
* control-flow edge;
* inheritance edge;
* override edge;
* public API exposure;
* module export;
* framework registration;
* framework lifecycle contract;
* reflection target;
* unresolved reflection limitation;
* Service Loader registration;
* annotation-processing contract;
* generated-source classification;
* test-source classification;
* visibility;
* ownership;
* project dependency;
* unsupported scope.

Evidence records must remain source-free.

They may include:

* canonical subject IDs;
* relationship kinds;
* producer versions;
* scopes;
* reliability;
* specificity;
* source references;
* snapshot lineage;
* limitations.

They must not include raw source code.

---

# 17. Data Model

## 17.1 `ReachabilityRoot`

Suggested fields:

* `subject_id`
* `category`
* `scope`
* `confidence`
* `confidence_tier`
* `evidence_ids`
* `limitations`

## 17.2 `ReachabilityPath`

Suggested fields:

* `root_subject_id`
* `target_subject_id`
* `relationship_sequence`
* `evidence_ids`
* `scope`
* `truncated`
* `limitations`

Paths should be bounded to prevent report explosion.

The default report may store one shortest deterministic path per root category or target.

## 17.3 `ReachabilityFinding`

Suggested fields:

* `subject_id`
* `qualified_name`
* `symbol_kind`
* `language`
* `project`
* `source_classification`
* `state`
* `confidence`
* `confidence_tier`
* `evidence_ids`
* `root_categories`
* `production_reachable`
* `test_reachable`
* `limitations`
* `producer_version`

## 17.4 `ReachabilityCoverage`

Suggested fields:

* `repository_scope`
* `projects_analyzed`
* `projects_partial`
* `projects_unsupported`
* `languages_supported`
* `languages_partial`
* `call_evidence_available`
* `call_evidence_coverage`
* `framework_coverage`
* `reflection_coverage`
* `subject_counts`
* `limitations`

## 17.5 `DeadCodeReport`

Suggested fields:

* `schema_version`
* `producer_version`
* `snapshot_id`
* `roots`
* `findings`
* `coverage`
* `evidence_index`
* `limitations`
* `statistics`

---

# 18. Determinism

PR131 must guarantee:

* stable symbol ordering;
* stable root ordering;
* stable traversal ordering;
* stable path selection;
* stable evidence IDs;
* stable confidence scores;
* stable serialization;
* stable report fingerprints.

Traversal should sort:

* projects;
* roots;
* nodes;
* outgoing relations;
* evidence references.

Equivalent inputs must produce byte-equivalent structured output after normalized serialization.

---

# 19. Serialization and Compatibility

The report must include:

* `schema_version`;
* `producer_version`;
* input snapshot lineage;
* canonical graph digest;
* configuration fingerprint.

Required property:

```text
DeadCodeReport.from_dict(report.to_dict()).to_dict() == report.to_dict()
```

Unknown schema versions must be rejected explicitly.

Publication is additive:

```text
semantic_context["reachability"]
```

or another final key chosen consistently with existing Atlas naming conventions.

Older snapshots without PR131 data must remain valid.

Downstream consumers must treat missing PR131 results as unavailable, not as an empty dead-code report.

---

# 20. Caching and Invalidation

PR131 should use a feature-local bounded cache.

Cache identity should include:

* snapshot lineage;
* canonical graph digest;
* specialized call-graph digest;
* framework-analysis producer versions;
* generated-source metadata digest;
* supported-language set;
* configuration fingerprint;
* PR131 schema and producer version.

The cache must invalidate when any reachability-relevant input changes.

Missing upstream results remain unavailable. PR131 must not recompute missing call or framework evidence with a duplicate analyzer.

---

# 21. Performance

The primary graph operation is reverse or forward reachability from a bounded root set.

Target complexity:

```text
O(V + E)
```

per analyzed relationship set, excluding optional bounded path materialization.

Requirements:

* no all-pairs reachability;
* no unbounded path enumeration;
* no exponential reflection expansion;
* no repository-wide name matching;
* no repeated traversal per symbol when one multi-source traversal suffices;
* deterministic bounded memory use.

Suggested implementation:

1. build canonical subject and relationship indexes;
2. identify roots;
3. perform multi-source production traversal;
4. perform multi-source test traversal;
5. apply external/framework/reflection/generated protections;
6. classify remaining subjects;
7. calculate confidence and coverage;
8. persist only referenced evidence.

---

# 22. Analysis Flow

```text
Canonical graph
    +
Specialized semantic evidence
    +
Entrypoints and repository metadata
    |
    v
Normalize canonical subjects
    |
    v
Discover reachability roots
    |
    v
Build authoritative relation indexes
    |
    v
Traverse production roots
    |
    v
Traverse test roots
    |
    v
Apply framework, reflection, Service Loader,
generated-code, and external API protections
    |
    v
Classify symbols
    |
    v
Calculate confidence and coverage
    |
    v
Publish source-free reachability report
```

---

# 23. AI Integration

PR131 should publish a compact source-free projection for AI-facing commands.

Default repository explanations should include:

* number of analyzed symbols;
* number of reachable symbols;
* number of test-only symbols;
* number of externally or framework reachable symbols;
* number of unused symbols;
* number of likely dead candidates;
* coverage status;
* top limitations;
* a bounded number of representative findings.

The default context should not include every symbol or full reachability path.

Detailed findings should remain queryable by later commands such as:

```text
atlas ai ask "Which methods are likely dead?"
atlas ai ask "Why is this class marked unused?"
atlas ai ask "Which symbols are reachable only from tests?"
atlas ai ask "Which projects have incomplete call coverage?"
```

PR131 itself should provide structured data that later PR134 Explain Anything and PR135 Semantic Search can consume.

---

# 24. CLI Expectations

PR131 does not require a new top-level command.

Existing commands may be enriched:

## `atlas ai context`

Include compact reachability statistics and coverage.

## `atlas ai explain`

Include repository-level dead-code summary and limitations.

## `atlas ai review`

Include likely dead-code candidates only when confidence and coverage are sufficient.

## `atlas ai ask`

Support deterministic reachability questions through the existing query path where feasible.

A dedicated future command may be considered only if the existing interface becomes insufficient.

---

# 25. Required Tests

## 25.1 Determinism

* identical inputs produce identical findings;
* evidence IDs remain stable;
* traversal order does not affect output;
* serialization round-trip is idempotent;
* reordered graph data produces equivalent output.

## 25.2 Basic reachability

* direct root-to-method call is reachable;
* transitive call chain is reachable;
* constructor call makes constructor and instantiated type reachable;
* unreachable private method in a closed complete scope becomes a candidate;
* ownership alone does not establish reachability.

## 25.3 Test-only reachability

* symbol reachable only from tests is `reachable_test_only`;
* test-only symbol is not included in production dead-code candidates;
* production and test roots remain distinguishable.

## 25.4 Missing call evidence

* no call graph does not cause repository symbols to become dead;
* missing call coverage reduces confidence;
* unsupported project receives `unknown` or partial coverage;
* missing canonical `calls` edges are not interpreted as no callers.

## 25.5 Public and external API

* exported public API with no internal caller is `externally_reachable`;
* private unused method may become `likely_dead` when scope is complete;
* public symbol with unknown export status remains `unused` or `unknown`;
* external API protection requires structural publication evidence, not visibility alone.

## 25.6 Framework-managed code

* recognized framework annotation creates a managed root;
* name-only `Controller` or `Service` class does not;
* unsupported framework lowers coverage;
* framework lifecycle interface is handled only through supported structural rules.

## 25.7 Reflection

* literal resolvable reflection marks target `reflection_discovered`;
* unresolved dynamic reflection creates a limitation;
* unresolved reflection does not mark every symbol reachable;
* unresolved reflection prevents overconfident dead-code classification in affected scope.

## 25.8 Service Loader

* declared provider is `service_loader_discovered`;
* provider identity is canonical and traceable;
* provider without direct calls is not dead;
* malformed or unresolved registration lowers confidence.

## 25.9 Generated and annotation-managed code

* generated symbols are classified correctly;
* generated symbols are excluded from default dead-code candidates;
* annotation-managed symbol receives appropriate protection;
* unknown generated linkage produces a limitation.

## 25.10 Confidence

* missing required evidence produces `insufficient`;
* contradictions reduce confidence;
* strong closed-scope evidence can produce high confidence;
* no LLM participates in scoring;
* scores remain bounded and deterministic.

## 25.11 Source-free publication

Serialized reports and AI projections must not contain source code.

Tests should reject representative raw code fragments such as:

```text
public class
return this
if (
new SomeType(
```

Evidence may contain canonical IDs and structured relationship metadata only.

## 25.12 Backward compatibility

* old snapshots without reachability data remain valid;
* PR129 graph serialization remains untouched;
* PR130 pattern findings remain unchanged;
* architecture detection output remains unchanged;
* collection succeeds when optional PR131 inputs are absent.

---

# 26. Acceptance Fixtures

PR131 should include focused synthetic fixtures for:

1. simple fully reachable application;
2. private unused method;
3. public external API;
4. test-only helper;
5. framework-managed component;
6. name-only fake framework component;
7. Service Loader provider;
8. resolved reflection target;
9. unresolved reflection;
10. generated source;
11. annotation-managed source;
12. incomplete call graph;
13. mixed Java and unsupported-language project;
14. multi-project repository with partial failures;
15. closed module with high-confidence dead code.

A real-world repository acceptance test should also be run against JUnit.

JUnit is especially useful because it includes:

* many extension interfaces;
* Service Loader-style mechanisms;
* test infrastructure;
* public APIs;
* framework-managed execution behavior;
* multiple projects;
* generated and tooling-related code;
* interface-heavy architecture.

The JUnit acceptance test should be used to validate conservative behavior, not to assume that every uncalled implementation is dead.

---

# 27. Expected JUnit Acceptance Questions

The JUnit report should answer:

* How many projects have reliable call evidence?
* Which symbols are reachable only from tests?
* Which public extension interfaces are externally reachable?
* Which Service Loader or plugin implementations are protected?
* Which dead-code candidates have high confidence?
* Which projects have insufficient reachability coverage?
* Why was each likely dead candidate classified that way?
* Which limitations prevent stronger conclusions?

A large number of `unknown` or `unused` findings is acceptable when call or framework evidence is incomplete.

A large number of high-confidence dead findings without complete evidence should be treated as a defect.

---

# 28. Failure and Recovery

PR131 must preserve Atlas workspace resilience.

If reachability analysis fails for one project:

* other projects continue;
* the failed project is marked unavailable;
* the report records the failure scope;
* no synthetic empty result is produced;
* downstream consumers see partial coverage.

If an optional call graph or framework analyzer fails:

* canonical graph analysis may continue;
* confidence and coverage are reduced;
* the failure is recorded as a limitation.

---

# 29. Security and Safety of Conclusions

Dead-code findings can lead users to delete code.

PR131 must therefore be conservative.

Every `likely_dead` or `unreachable` finding must provide:

* confidence;
* evidence references;
* analyzed scope;
* call-evidence coverage;
* framework/reflection limitations;
* source classification;
* whether external API exposure was evaluated.

The user-facing wording should prefer:

* “likely dead”;
* “unused in the analyzed scope”;
* “no known production path”;
* “insufficient evidence”;
* “coverage is partial”.

It should avoid absolute wording such as:

* “safe to delete”;
* “definitely unused”;
* “never called”;

unless a bounded complete analysis genuinely proves that statement.

---

# 30. Documentation Deliverables

PR131 should include:

* `docs/PR131_DEAD_CODE_REACHABILITY.md`
* `docs/PR131_EXISTING_CAPABILITIES.md`
* updated semantic-context schema documentation;
* updated CLI explanation examples;
* acceptance report for JUnit;
* independent review record.

The existing-capabilities document must state:

* what already existed;
* what was reused;
* what was missing;
* what PR131 extended;
* regression risks.

---

# 31. Implementation Scope

Suggested implementation packages:

```text
moughorai/reachability/
    __init__.py
    models.py
    roots.py
    relationships.py
    classifier.py
    coverage.py
    service.py
```

Potential framework-specific adapters should remain outside the core classifier where existing architecture permits:

```text
moughorai/reachability/frameworks/
```

The exact package structure may follow established Atlas conventions.

The implementation should avoid one oversized service file if responsibilities can be separated cleanly from the start.

---

# 32. Acceptance Criteria

PR131 is complete when:

1. It consumes the PR129 canonical graph without modifying or duplicating it.
2. It reuses existing entry-point, CFG, framework, generated-source, and call-graph evidence.
3. It distinguishes reachable, test-only, externally reachable, framework-managed, reflection-discovered, Service Loader, generated, unused, likely dead, unreachable, and unknown states.
4. Missing call evidence reduces confidence and coverage instead of producing dead-code claims.
5. Public or protected symbols are not marked dead solely because no internal caller exists.
6. Framework and pattern names alone never establish reachability.
7. Every finding includes deterministic confidence, evidence IDs, scope, and limitations.
8. The report is source-free.
9. Serialization is deterministic and idempotent.
10. Older semantic snapshots remain compatible.
11. Partial project failures do not stop repository analysis.
12. Default AI context remains compact and bounded.
13. High-confidence dead-code candidates are conservative and reviewable.
14. JUnit repository acceptance testing completes with explicit coverage information.
15. Automated tests verify false-positive resistance for reflection, frameworks, generated code, public APIs, and missing calls.

---

# 33. Review Checklist

The independent reviewer should verify:

## Architecture

* Does PR131 consume rather than replace PR129?
* Does it reuse specialized graphs?
* Does it avoid a duplicate call graph?
* Are roots, traversal, classification, confidence, and publication separated cleanly?

## Precision

* Does missing call evidence avoid false dead-code findings?
* Are public APIs protected appropriately?
* Are framework-managed symbols structurally detected?
* Are reflection and Service Loader handled conservatively?
* Are generated symbols treated correctly?

## Confidence and evidence

* Is every conclusion evidence-backed?
* Are missing inputs represented as insufficient?
* Are scores deterministic?
* Are evidence IDs stable?
* Is snapshot lineage preserved?

## Performance

* Is traversal bounded to `O(V + E)`?
* Is path materialization bounded?
* Are caches correctly invalidated?
* Is report growth controlled?

## Compatibility

* Are PR127–PR130 outputs unchanged?
* Do old snapshots still load?
* Does analysis continue when optional evidence is missing?
* Is the semantic-context addition additive?

## AI integration

* Is the default projection compact?
* Does it avoid raw source?
* Does it clearly expose coverage and limitations?
* Does it avoid wording that implies deletion is safe?

The reviewer must return exactly one verdict:

* `APPROVE`
* `APPROVE WITH MINOR CHANGES`
* `REQUEST CHANGES`
* `REJECT`

Every issue must include:

* severity;
* evidence;
* consequence;
* recommendation;
* blocking or non-blocking status.

---

# 34. Final Design Rule

PR131 must prefer:

```text
Unknown
```

over:

```text
False certainty
```

The feature succeeds when it can explain not only which code appears unused, but also why Atlas believes that conclusion, how complete the analysis was, and what evidence could invalidate it.
