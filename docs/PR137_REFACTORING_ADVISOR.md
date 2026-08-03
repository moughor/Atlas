# PR137 Deterministic Refactoring Advisor

## Scope

PR137 introduces advice, not code changes. The first safe slice reviews dependency-
cycle seams that are already reported by PR128 and can be revalidated completely
against authoritative PR129 canonical graph evidence. It does not parse source,
discover cycles, infer architecture from names, generate patches, or invoke an LLM.

The roadmap's broader Refactoring Advisor remains larger than the evidence currently
published by Atlas. PR137 v1 therefore reports the unsupported families explicitly:

- duplicate consolidation is unavailable without a structural duplicate producer;
- extract method/class is insufficient without complete complexity, cohesion, size,
  ownership, and dependency evidence;
- package restructuring is insufficient without dependency clusters and intended
  architecture boundaries;
- dependency cleanup is insufficient without complete build and usage evidence;
- layer-violation advice is unavailable without persisted intended direction rules.

Risk, search relevance, Git co-change, graph degree, missing callers, names, package
labels, and LLM output cannot create a refactoring candidate.

## Architecture

The request-local flow is:

```text
verified Atlas semantic snapshot
  -> PR134 CanonicalSubjectResolver and its PR129 KnowledgeGraph
  -> compatible PR128 dependency-cycle observations
  -> unique project resolution for every cycle member
  -> authoritative canonical evidence for every closing cycle step
  -> deterministic cycle-seam candidates
  -> optional bounded PR136 impact context
  -> PR130 evidence, confidence, estimates, ranking, and response
```

PR137 uses the resolver's existing graph and adjacency. When a compatible PR128
cycle is actually present, it builds one bounded, request-local lookup of
authoritative cross-project evidence so cycle steps can be checked without repeated
whole-graph scans. This is not a second graph, cycle detector, traversal engine,
confidence model, evidence model, persistent cache, or semantic pass. Snapshots with
no usable upstream cycle skip that lookup entirely. Advice is ephemeral and
reconstructible, so running it does not alter the input snapshot, snapshot ID,
normal analysis output, or accepted benchmark goldens.

## Cycle evidence boundary

A PR128 cycle is not trusted merely because it is present in a snapshot. PR137
requires all of the following:

1. architecture schema version 1;
2. `dependency_analysis.executed == true` and positive represented edge coverage;
3. a bounded cycle with at least two distinct members;
4. unique PR134 resolution of every member to a PR129 project;
5. every consecutive step, including the closing step, backed by an authoritative
   canonical cross-project import or exact project dependency edge;
6. portable, source-free producer references for every retained edge.

If any condition fails, that cycle creates no advice. The response records partial,
incompatible, or unavailable coverage rather than attempting to reconstruct the
missing relationship or claiming that no cycles exist.

PR137 does not enumerate cycles independently. Rotation and duplicate representations
of the same cycle are canonicalized only to match and deduplicate the already supplied
PR128 observation.

## Advice contract

Each retained advice item contains:

- a deterministic advice ID and operation;
- the canonical project subjects participating in the candidate seam;
- a rationale and explicit preconditions;
- expected-gain and effort estimates with their available components;
- optional compact PR136 impact counts and breaking-change state;
- shared deterministic confidence;
- exact evidence IDs and a closed evidence index;
- limitations and verification steps.

The operation is intentionally phrased as reviewing and decoupling a cycle seam. A
canonical dependency or import proves a represented relationship, not that deleting
it is behaviorally safe. Verification therefore requires build/dependency review,
replacement-boundary confirmation, targeted tests, and a fresh Atlas analysis.

The expected-gain contract records complete verified-cycle coverage but leaves the
gain level unknown: proving a cycle does not quantify the architectural or build
benefit of changing one seam. The first slice does not consume PR132 risk. Optional
PR136 impact may contextualize a proven candidate but cannot create one. Missing
impact, tests, external-consumer knowledge, or call coverage leaves effort unknown;
it never becomes a low-effort score by default.

Cycle-seam advice is language-neutral at project level: it relies on canonical
project dependencies or cross-project imports, not on a language-specific name
heuristic. It does not claim support for symbol-level extraction or movement in any
language.

## Determinism and bounds

Requests, candidates, evidence, capabilities, estimates, and limitations use
canonical ordering. IDs and fingerprints contain the snapshot lineage, graph digest,
configuration, canonical subjects, and accepted evidence. Exact model round trips
must satisfy:

```text
response.to_dict()
== RefactoringResponse.from_dict(response.to_dict()).to_dict()
```

Candidate generation scans the supplied bounded cycle observations and existing
canonical edges, retains at most 64 canonical edge records per project pair, then
uses deterministic top-k selection. It does not compute an all-pairs closure.
Request limits, cycle-member limits, edge-evidence limits, PR136 impact depth, and
output counts remain explicit when work or output is truncated.

## Source-free operation

Responses contain canonical semantic identities, fixed explanatory text, aggregate
counts, confidence values, and one-way evidence references. They do not contain raw
source, comments, arbitrary producer prose, absolute machine paths, private remotes,
usernames, or LLM output. Unsafe or malformed upstream values are ignored or make the
corresponding capability incompatible.

## Interfaces

The additive Python surface consists of:

- `RefactoringRequest`;
- `RefactoringResponse`;
- `RefactoringAdvisorService`.

The provider-free `atlas refactor` command reads an existing verified `.ass`
snapshot and renders deterministic human or JSON output. It supports bounded family,
subject, result-limit, impact-depth, and opt-in M2 profiling controls. There is no
`--apply`, patch-generation, source-scan, Git-scan, or LLM option.

Older snapshots remain readable. Missing or incompatible architecture, pattern,
reachability, risk, search, or impact inputs degrade only the affected capability.

## Remaining roadmap work

Later PR137 slices require real upstream producers, not placeholders:

- structural clone groups for duplicate consolidation;
- method/class complexity, cohesion, size, and ownership facts for extraction;
- resolved dependency clusters and intended architecture boundaries for moves;
- complete build/usage evidence for dependency removal;
- persisted intended layer-direction rules for violation repair.

Automatic patches, behavioral-equivalence proofs, unowned clone engines, speculative
modularization, and cross-repository moves remain intentionally deferred as required
by `PR137_DESIGN.md`.
