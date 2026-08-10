# PR151 — Deterministic impact aggregates and fail-safe AI grounding

## Decision

Impact aggregates belong to deterministic Impact Intelligence. They are computed
from every deduplicated impact plan before representative selection. Atlas AI only
projects the aggregate and bounded representative findings into provider context.

The frozen PR136 `ImpactPredictionResponse` schema, constructor, producer, and
serialization remain unchanged. `ImpactPredictionService.predict()` keeps returning
that response. The additive `ImpactPredictionService.analyze()` path returns an
`ImpactPredictionAnalysis` containing the legacy response and an `ImpactAggregate`.
No ASS snapshot field or public API v1 signature changes.

## Aggregate contract

The aggregate records total classifications, unique affected projects, direct and
transitive affected-project partitions, category counts, depth distribution,
configured and observed depths, visited nodes and edges, traversal completeness,
representative display counts, capability availability, and limitations.

Traversal completeness and representative completeness are independent. A bounded
representative list never changes complete aggregate counts. If traversal reaches a
hard analysis bound, the aggregate states that its counts are exact only within the
represented traversal.

## Provenance

One deterministic `ANALYSIS_RESULT` evidence record binds the aggregate to the
snapshot lineage, graph digest, impact-request fingerprint, complete counts,
category/depth digests, traversal metadata, representative metadata, and a digest of
the supporting canonical relationship references. Its reliability and specificity
do not exceed the weakest contributing relationship policy.

The compact derived record permits aggregate facts to be cited without serializing
every contributing relationship into an LLM prompt. It does not invent an edge or
claim runtime behavior.

## Ask context

Impact intent produces two separate sections:

- `impact_aggregate` is compact, authoritative, evidence-backed, and mandatory;
- `impact_prediction` contains optional bounded representative findings.

Token selection may omit representatives or semantic-search detail, but it cannot
remove the aggregate and continue with an impact answer. Every representative
collection carries total, included, omitted, and completeness metadata.

For an explicitly supplied canonical subject, semantic search is not independently
required for grounding. Impact grounding requires a retained aggregate and an exact
citation to its selected aggregate evidence.

## Provider and fallback contract

Providers must treat aggregates as authoritative, respect representative omission
metadata, avoid exhaustive language for incomplete lists, distinguish static or
declared dependencies from runtime use, and cite exact `evidence:<sha256>` IDs.
Bare SHA values and unknown evidence IDs remain invalid.

When an impact provider response is not grounded, Atlas discards that prose and
renders a deterministic fallback from the retained aggregate, representatives,
capabilities, limitations, and evidence IDs. The fallback explicitly reports that
provider grounding failed. Text CLI output therefore leads with the deterministic
Atlas answer; ungrounded provider prose cannot masquerade as evidence.

PR151 deliberately omits citation-repair retries. The deterministic fallback is the
smaller and safer correctness mechanism.

## Limitations

- Aggregate relationships are repository-local static evidence, not proof of
  runtime communication.
- Project counts cover canonical project subjects represented by impact plans.
- Architecture evidence remains a separate capability and is not inferred from
  impact topology.
- Existing conversation records do not persist every original token-budget option;
  historic context selection may therefore be auditable by digest without being
  fully replayable from the conversation database alone.
