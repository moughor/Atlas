# PR165 Enterprise Interactive Runtime

## Problem

Large validated snapshots already contain the required repository intelligence,
but interactive consumers previously reconstructed canonical semantic indexes and
the PR156/PR157/PR158 Java artifacts for every turn. On SyGMa, a second Ask
context over the same loaded snapshot still took about 161 seconds even though a
warm Java impact query took milliseconds.

## Ownership and lifecycle

`RepositoryRuntimeSession` owns at most one `RepositoryIntelligenceRuntime`.
The runtime composes existing authorities; it does not implement resolution,
impact, TEST, reachability, or semantic-search rules. Components are materialized
only when requested and are retained until the session closes or authoritative
lineage changes.

The runtime holds references to:

* the validated `AtlasSemanticSnapshot`;
* the existing `CanonicalSubjectResolver`;
* the existing `SemanticSearchService` and index;
* the existing `JavaCodeIntelligenceService`, including callable index, code
  graph, TEST evidence, reachability report, and query indexes;
* the existing `ImpactPredictionService`; and
* stateless `StructuredExplanationService` projections.

Ask and Explain build fresh request outputs. Conversation state remains owned by
the existing PR139 memory contract and is never stored in the repository runtime.

## Lineage and invalidation

The one-entry runtime key includes snapshot ID, schema, workspace fingerprint,
analyzer version, normalized workspace root, and persisted lineage fields for the
semantic graph, callable index, code graph, TEST evidence, and reachability.
Snapshot ID remains the cryptographic authority over the complete validated
snapshot. Artifact fingerprints make component ownership observable.

A different key closes and releases the prior runtime before constructing a new
one. A path, branch name, file modification time, or `latest.ass` name is never a
reuse authority. Failed lazy initialization is not cached and can be retried.

## Semantic and memory guarantees

Runtime telemetry is process-local and never enters semantic JSON, evidence,
snapshot content, IDs, ordering, or digests. PR156 identity, PR159 traversal,
PR161 grouping, PR162 bounds, and PR164 reconciliation remain unchanged.

The session retains one repository runtime only. It has no global registry,
persistent cache, pickle payload, daemon, background worker, or per-request graph
copy. `close()` releases component references deterministically.

## Measured behavior

The canonical pre-change profile loaded one snapshot once and then built two
identical Ask contexts with one builder. The second context still took 161.319
seconds. Profiling attributed the dominant cost to fresh typed code-graph
reconstruction, semantic-index construction, and three canonical resolver builds.

With the shared runtime and exact-subject reconciliation reusing the runtime-owned
validated PR156 index, the same SyGMa context remained byte-identical and had a
0.552-second warm median. Warm Explain had a 0.173-second median and direct Java
impact had a 0.017-second median. A warm cProfile observed zero callable-index,
code-graph, TEST-evidence, reachability, or canonical-resolver reconstruction
calls.

The measured session loaded the frozen snapshot in 9.854 seconds. Its first
Explain materialized required Java authorities in 82.756 seconds, and the first
Ask context then materialized semantic search in 42.017 seconds. This cold work
remains intentionally visible and is not hidden by unsafe trust or persistent
object serialization. Working set stabilized at approximately 4.886 GB from
request 5 through request 50; peak working set was approximately 5.047 GB.

## Limitations

* The first request still pays validated snapshot and required component
  construction costs.
* Warm requests still perform their actual bounded traversal, evidence selection,
  rendering, token estimation, and semantic search.
* Provider latency is separate from deterministic Atlas context construction.
* Exact constructor Ask/Explain support remains deferred by PR164.
* Reuse is in-process only; separate one-shot CLI invocations intentionally do not
  share Python object graphs.

## MONDAY SYGMA WORKFLOW

From the SyGMa workspace, verify the configured snapshot without rescanning:

```powershell
cd C:\sygma\sygma
python -B -m moughorai.atlas_cli snapshot status --json
```

Start one reusable local session. Replace the placeholders with an Atlas canonical
method ID and its authoritative PR156 Java project:

```powershell
python -B -m moughorai.atlas_cli ai session C:\sygma\sygma `
  --subject <canonical-method-id> `
  --project <authoritative-java-project> `
  --capability code_impact
```

Inside the session:

```text
/explain
/impact
If I modify this method, what can be affected and which represented tests reach it?
/subject method:<another-id>
/project <another-authoritative-project>
/stats
/exit
```

`/exit` closes the runtime and provider cleanly. No source scan or ASS publication
occurs in this workflow.
