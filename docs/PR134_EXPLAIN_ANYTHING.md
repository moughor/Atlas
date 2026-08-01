# PR134 — Explain Anything

## Purpose

PR134 adds deterministic, subject-scoped explanations over semantic facts already
published by Atlas. It resolves one canonical repository subject, selects a bounded
set of facts and relationships, preserves their evidence and confidence, and reports
all relevant uncertainty. It does not rescan source code or introduce another graph,
report, analyzer, confidence model, or evidence model.

The PR129 `KnowledgeGraph` remains the canonical repository graph. Specialized
analyzers remain authoritative in their domains. PR127 through PR133 results are
optional structured enrichment; PR134 can explain a subject directly from a compatible
semantic snapshot and canonical graph without a PR133 report.

## Supported subjects

The canonical resolver supports:

- repository and workspace;
- project;
- package and module;
- class/type and method;
- dependency;
- framework;
- build system and real build target;
- generic canonical symbol;
- an explicit canonical graph relationship.

Architecture, design-pattern, reachability, risk, and repository-report findings may
enrich the resolved subject when their structured producer result is compatible and
traceable. They are not separate PR134 subject models.

`build_target` means a task or target emitted by an authoritative build-target
producer. Maven, Gradle, and npm inventory entries remain `build_system` subjects.
Normal snapshots currently do not publish real build-target nodes, so that capability
is reported as unavailable rather than inferred.

## Canonical subject resolution

`moughorai.subject_resolution.CanonicalSubjectResolver` builds immutable in-memory
indexes over PR129 identities and optional symbol metadata. Resolution follows this
fixed order:

1. exact canonical ID;
2. exact qualified name within supplied scope constraints;
3. one unique Unicode-normalized, case-folded name;
4. bounded deterministic candidates requiring disambiguation.

Optional kind, project, language, and workspace-relative path constraints narrow the
candidate set. The resolver does not use substring matching, fuzzy similarity,
name-based semantic claims, source inspection, an LLM, or the future PR135 search
engine. Duplicate qualified names, overloads, and project/module collisions remain
ambiguous instead of selecting the first match.

Repository and workspace graph IDs can encode the local workspace root. They remain
internal to PR129. Serialized explanations expose stable safe references and reject
raw Windows/POSIX absolute paths and repeatedly URL-encoded absolute paths.

Malformed or incompatible graphs degrade explicitly. Duplicate IDs invalidate the
resolver input; dangling relationships are omitted and disclosed as a limitation.
Missing relationship evidence is never interpreted as evidence that a relationship
does not exist.

## Structured explanation contract

`moughorai.structured_explanation.StructuredExplanationService` produces one immutable
`StructuredExplanation` for a structured `ExplanationRequest`. The result contains:

- request and availability state;
- one resolved subject or bounded disambiguation candidates;
- identity, metadata, relationship, finding, and limitation facts;
- capability availability and coverage;
- evidence IDs, producer IDs, references, confidence, and limitations;
- snapshot lineage, canonical graph digest, input fingerprint, and context digest;
- exact context-selection and truncation counts.

Availability is one of `available`, `partial`, `unavailable`, `ambiguous`,
`not_found`, or `unsupported`. Missing or incompatible analysis remains explicit and
cannot become a negative conclusion.

The current serialized contracts are:

```text
schema_version: 1
producer_version: atlas-pr134/1
selection_policy: structured-explanation-context.v1
```

Explanations are ephemeral. PR134 does not add another field to the ASS artifact, so
its expected semantic-snapshot growth is zero.

## Facts, evidence, and confidence

PR134 reuses PR130 `EvidenceRecord`, `EvidenceIndex`, `ConfidenceResult`, and the
shared deterministic confidence calculator. Every available or partial explanation
fact cites evidence. The retained evidence index is an exact closure: it contains all
and only records cited by retained facts.

Each explanation-owned evidence record binds the fact ID, PR134 producer version,
snapshot lineage, normalized source references, scope, language, detail, and
limitations. Upstream evidence is verified before it is cited. Incompatible,
untraceable, or absent producer data is disclosed rather than projected as fact.

PR130 findings are accepted only when every cited canonical source/target belongs to
the finding's participant set. A valid evidence record from the same snapshot cannot
be reassigned to unrelated participants.

PR131 root and relationship evidence is additionally bound to the persisted path for
the resolved subject and production/test scope. A valid record from another subject's
path cannot be attached to the explanation, and a non-trivial reachability path needs
its own relationship evidence.

PR130 v1 does not publish a standalone canonical graph digest. PR134 validates its
schema, producer, input lineage, canonical evidence IDs, and snapshot co-publication,
but reports that independent current-graph binding is unavailable instead of claiming
stronger lineage than the inherited contract provides.

Exact identities and measurements use a non-probabilistic confidence basis. Findings
preserve a compatible upstream `ConfidenceResult`; accepted legacy findings without a
complete shared confidence payload are labeled as legacy rather than receiving an
invented score. LLM output cannot create evidence or alter confidence.

## Bounded context selection

PR134 is the second real consumer of the PR133 token-budgeting convention. The
explanation selector uses the existing deterministic token estimator and a default
7,000-token input ceiling at the `ExplainEngine` boundary.

Selection:

- retains the request, resolved subject, capability states, and limitations;
- orders optional facts by explicit priority and stable fact ID;
- keeps whole facts and their complete evidence closure;
- selects the longest fitting deterministic prefix;
- records exact included and omitted fact/evidence counts;
- marks the result `partial` when otherwise available context is truncated;
- fails explicitly if the mandatory envelope cannot fit.

Traversal is direct, indexed, cycle-safe, and bounded. PR134 does not calculate an
unbounded graph neighborhood or store transitive paths.

## CLI and AI behavior

The existing `atlas ai explain` command remains the single explanation interface.

```powershell
# Accepted deterministic default repository report (PR133 behavior)
atlas ai explain C:\path\to\workspace

# Deterministic structured explanation without an LLM
atlas ai explain C:\path\to\workspace --subject MyType --kind type --json

# Disambiguate a symbol
atlas ai explain C:\path\to\workspace --subject run --kind method `
  --project app --language java --path src/main/java/example/Runner.java --json

# Explain one canonical relationship
atlas ai explain C:\path\to\workspace --subject project:app `
  --target dependency:maven:example --relation depends_on --json
```

`--json` is provider-free and prints canonical structured JSON. Without `--json`, a
targeted request may send only the bounded structured explanation to the configured
provider through prompt `atlas-explain-anything-v1`. The provider does not receive the
whole ASS or raw source.

The optional narrative must distinguish Atlas facts, interpretation, and suggestions,
cite supplied evidence IDs for factual statements, preserve confidence wording, and
state unavailable information. Provider prose is presentation only; the structured
result remains the authoritative response contract. Ambiguous, not-found,
unsupported, and unavailable requests are rendered deterministically without asking a
provider to guess.

The exact default `workspace`/`repository` request continues through the accepted
PR133 deterministic renderer, calls no provider, and preserves its existing output.
PR134 structured metadata is attached to the returned result for API consumers without
changing the rendered PR133 Markdown bytes.
Existing `ExplainRequest` and `ExplainResult` positional fields remain at the start of
their additive PR134 models, and conversation-memory ordering and snapshot references
remain compatible.

## Determinism and safety guarantees

For identical compatible inputs and request, PR134 guarantees:

- stable resolution and candidate ordering;
- byte-identical canonical JSON;
- exact `to_dict()` / `from_dict()` round trips;
- stable fact, evidence, input, lineage, graph, and context digests;
- stable whole-fact selection and omission counts;
- no timestamps, random identifiers, raw source, or machine-specific paths.

Repository inventory attributes are emitted only when the corresponding structured
field is present and well-typed. Missing or malformed counts remain unavailable and
are never converted into a factual zero. Relationship facts retain at most 16 safe
producer references and report the exact number excluded by safety, deduplication, or
that bound.

Optional provider prose is not deterministic and is excluded from these guarantees.
It cannot modify the structured explanation.

## Compatibility

- PR129 remains the sole canonical graph and its identifiers are unchanged.
- PR130 evidence, confidence, lineage, and serialization contracts are reused.
- PR131 through PR133 findings are consumed only when compatible and traceable.
- Snapshots predating PR134 remain readable because explanations are derived at query
  time and no new snapshot field is required.
- Missing PR130 through PR133 fields produce partial or unavailable capabilities.
- The accepted default PR133 repository explanation remains unchanged.
- Targeted requests no longer serialize the complete snapshot into the LLM prompt;
  they use the bounded subject-scoped projection instead.

## Limitations and deferred work

- Canonical `calls` and `composition` model support is not production evidence that
  those relations were populated. Missing authoritative edges reduce capability and
  confidence.
- Line-level source explanation is intentionally absent; source files and raw source
  are not prompt inputs.
- The resolver performs exact identity resolution, not natural-language or semantic
  search. Intent-based search belongs to PR135.
- Impact and blast-radius answers belong to PR136; refactoring, security, and chat
  capabilities belong to PR137 through PR139.
- PR134 does not persist indexes, explanations, prompts, provider answers, or caches.
- PR131 grouped findings remain compact. A targeted reachability explanation scans
  persisted paths to bind evidence to the requested target; a future measured need may
  justify an incremental compact path index, but PR134 adds no speculative cache.
- PR130 v1 current-graph lineage depends on checksum-validated snapshot co-publication
  because the report has no standalone graph digest.
- No new repository scan, Git query, call graph, CFG, architecture detector, risk
  analyzer, or other producer is introduced.
- The inherited accepted PR130 evidence implementation does not preserve arbitrary
  unknown fields through an `extensions` member, and its no-role confidence state is
  `insufficient`. PR134 preserves that existing contract rather than creating a
  competing model.
