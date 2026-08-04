# PR142 Technical Debt Engine

## Scope

PR142 implements the smallest safe slice of the official **Technical Debt Engine**
roadmap item:

> Rank technical debt by engineering impact and reuse PR132 complexity and risk
> evidence.

The first slice is deliberately cycle-only. A technical-debt candidate exists only
when PR137 has revalidated a reported PR128 dependency cycle against authoritative
PR129 canonical relationships. PR142 does not discover cycles, infer architecture,
or promote risk indicators into debt findings.

PR142 follows PR141 Repository Evolution but does not consume two-snapshot evolution.
PR141 graph changes are observations, not proof that debt increased or decreased.
The exact next roadmap item is PR143 **Architectural Drift**, which remains excluded.

## Architecture

```text
checksum-verified semantic snapshot
                |
      PR134 canonical resolver
                |
       PR129 canonical graph
                |
 PR128 reported dependency cycles
                |
 PR137 authoritative cycle-step revalidation
                |
 bounded verified cycle-seam candidates
        |                       |
 PR136 represented impact   PR132 exact-subject risk/complexity
        |                       |
        +---- PR130 evidence and confidence ----+
                            |
       deterministic ranked and unranked debt response
```

The PR142 service is an orchestration and projection layer. It is not a graph,
resolver, cycle detector, traversal engine, impact predictor, risk analyzer,
complexity analyzer, evidence model, confidence model, persistence layer, cache, or
LLM feature.

## Candidate authority

PR137 verified cycle seams are the only candidate source in the first slice. A seam
is eligible only when:

- the snapshot and canonical graph are compatible;
- the PR128 dependency analysis executed and reported positive evidence coverage;
- every cycle member resolves uniquely to a canonical project subject;
- every consecutive cycle step has an authoritative represented PR129 relationship;
- every retained reference passes the established source-free evidence projection;
- PR137 emits canonical evidence under the active snapshot lineage.

A raw PR128 cycle record, architecture label, dependency name, project name, or
repository-report sentence cannot create a PR142 candidate. A missing cycle is not a
negative result unless the upstream capability explicitly establishes sufficient
coverage; the first slice does not claim complete negative coverage.

## Engineering-impact context

PR136 remains the single engineering-impact engine. PR142 consumes its bounded
represented-impact response for exact canonical cycle-seam subjects. It preserves:

- capability state;
- direct and transitive represented impact counts;
- total, omitted, and truncated counts;
- relationship and coverage limitations;
- evidence IDs and snapshot lineage.

PR136 impact describes represented repository-local exposure. It does not establish
runtime execution, external consumers, total blast radius, build failure, API
breakage, migration safety, or developer intent.

When impact is unavailable, incompatible, unsupported, insufficient, or not
comparable, the verified debt candidate is retained as **unranked**. No zero-impact
value is invented.

## PR132 risk and complexity context

PR142 accepts only a compatible `RiskAnalysisReport` with:

- producer `atlas-pr132/1`;
- schema version 1;
- a graph digest matching the active PR129 graph;
- canonical evidence identities;
- evidence records bound to the PR132 report lineage;
- an exact canonical subject match.

Risk score, confidence, factors, missing signals, and capability states remain PR132
values. PR142 does not change their weights or normalization. Risk context may
explain or deterministically break an otherwise equal impact ordering, but risk alone
cannot create a debt candidate. When both seam participants have compatible PR132
context, PR142 retains the participant with the highest existing PR132 score, then
breaks an exact tie by PR132 rank and canonical subject identity. The selected
subject ID remains explicit in JSON and human output. This tie-break is used only
for candidates with represented impact; unranked candidates remain ordered by item
identity alone.

Complexity is shown only when an exact-subject PR132 factor cites a structured
complexity producer. In ordinary snapshots, production complexity remains
`unavailable`. PR142 never substitutes fan-in, fan-out, size, churn, diagnostics,
names, or LLM reasoning for complexity. Complexity subject and evidence identities
are retained independently for every cycle participant with that structured signal;
they are not lost when another participant supplies the selected risk tie-break.

## Ranking contract

Ranking is ordinal and non-composite. PR142 does not publish a new “debt score” and
does not add unlike quantities. Comparable candidates are ordered using existing
facts in this sequence:

1. available or partial PR136 represented-impact evidence;
2. represented affected-candidate count, descending;
3. direct represented-impact count, descending;
4. compatible exact-subject PR132 risk score, descending, only as a tie-breaker;
5. canonical debt-candidate identity.

Truncated impact is marked partial and its counts are bounded represented
observations, not complete impact. If candidates cannot be compared under this
contract, they remain in a separately ordered unranked collection. Unranked
candidates are sorted only by canonical candidate identity.

The response reports why each item is ranked or unranked. Confidence expresses the
quality and coverage of evidence for the conclusion; it is not severity, priority,
or impact.

## Evidence, lineage, and identity

PR142 reuses the PR130 evidence and confidence contracts. Every conclusion cites:

- PR137 verified cycle and cycle-step evidence;
- PR136 impact evidence when ranking uses represented impact;
- PR132 factor evidence when risk or complexity context is displayed;
- a PR142 derived record binding the candidate, upstream roles, active graph digest,
  and snapshot lineage.

Evidence IDs, candidate IDs, request fingerprints, ordering, capability states, and
rendering are deterministic. The PR142 producer is versioned independently from the
upstream producers. The active ASS snapshot ID is the PR142 lineage; PR132 retains its
own internal analysis lineage and is accepted only after compatibility validation.

Item confidence remains the authoritative PR137 confidence in the existence and
revalidation of the cycle seam. Missing impact makes the item unranked and changes
the impact capability state; it does not rewrite upstream cycle-evidence confidence
or imply lower severity. If equivalent advice is grouped, the item retains the most
conservative existing PR137 confidence, with advice ID as the deterministic tie-break,
and exposes the exact confidence-producing advice ID. An LLM cannot add evidence, change confidence, resolve
identity, create a candidate, or alter rank.

## Capability states

The response exposes exactly these first-slice capability dimensions:

- verified dependency-cycle evidence;
- engineering-impact availability;
- PR132 risk availability;
- PR132 structured-complexity availability.

Snapshot and graph identity remain explicit response lineage fields. Upstream
incompatibility is preserved in the affected capability state. Ranking completeness
is represented by the observation, unique-candidate, equivalent, unevaluated,
output-omitted, ranked, unranked, and truncation counts rather than a fifth
capability.

Expected meanings are:

| State | Meaning |
| --- | --- |
| `available` | Required compatible evidence exists for the bounded capability |
| `partial` | Positive evidence exists, but coverage or bounds are incomplete |
| `insufficient` | A candidate is verified, but required comparable ranking evidence is missing |
| `unavailable` | The producer or observation is absent |
| `incompatible` | Producer, schema, graph digest, lineage, identity, or evidence validation failed |

An empty candidate set never means “no technical debt.” It means that no verified
cycle-only candidate was retained under the available evidence and bounds.

## Determinism and bounds

Candidate extraction, preselection, impact invocation, evidence materialization,
ranking, and rendering use fixed bounds and canonical ordering. Equivalent reordered
input must produce byte-identical DTOs, JSON, evidence IDs, confidence, rank, and
human output.

Equivalent PR137 observations sharing the same directed seam are grouped before
impact evaluation, merge their authoritative evidence, and produce one debt item.
They never increase rank. All evaluated upstream advice IDs remain explicit;
unevaluated upstream observations remain counted but cannot expose IDs that were not
returned by the bounded PR137 request. Evidence payload
is retained for at most six deterministically selected equivalent advice records per
item; additional evidence observations are counted and reported as omitted rather
than overflowing the bounded item contract. The complete and evidence-backed advice
ID sets are bound by a deterministic adapter digest. PR136 impact is represented by
one fingerprinted, bounded, non-reversible evidence-reference adapter rather than a
copy of every path record. Counts distinguish upstream observations, unique evaluated
candidates, collapsed equivalent observations, unevaluated observations, and output
omissions. Capability coverage uses all known upstream observations as a conservative
denominator, not only the bounded evaluated subset. Impact is invoked only after
grouping and deterministic bounded candidate selection. Tie-breaking never depends
on input order, hash
iteration, thread completion, timestamps, filesystem enumeration, or model output.

## Source-free trust boundary

PR142 consumes verified semantic metadata only. It does not read source files,
patches, raw Git diffs, prompts, provider responses, or LLM output.

The response excludes:

- raw source code and literals;
- absolute or private checkout paths;
- raw repository content;
- unvalidated diagnostic messages;
- contributor identities;
- raw model or provider output;
- unbounded symbol or relationship lists.

All display strings remain untrusted and are projected through existing source-free
and rendering boundaries before output.

## Persistence, cache, and public compatibility

The first-slice response is ephemeral and reconstructible. PR142 adds no persisted
semantic-context key, snapshot duplication, durable history record, recovery field,
conversation state, persistent index, or feature cache. Ordinary semantic snapshot
size is unchanged: controlled Maven and Spring analyses produced snapshots
byte-identical to their PR141 artifacts (`0 bytes / 0.0%` growth).

No frozen public v1 facade change is part of this slice. Existing PR127-PR141
snapshots, services, reports, commands, and deterministic outputs remain compatible.

## Intentionally deferred

- PR131 dead-code and test-only reachability debt ranking;
- unused dependency debt without an authoritative producer;
- duplicate-code and clone debt;
- production cyclomatic or cognitive complexity generation;
- resolved test-density and test-coverage debt;
- symbol-size, cohesion, coupling-policy, and layer-violation debt;
- security debt classification;
- debt evolution across two or more snapshots;
- debt persistence, baselines, suppression, policy gates, or shared caches;
- automated remediation or refactoring execution;
- architectural drift, owned by PR143.
