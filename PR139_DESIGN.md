# PR139 Design — Interactive Engineering Chat

PR139 composes existing conversation memory, semantic snapshots, PR129 graph,
PR133 reports, PR134 explain, PR135 search, PR136 impact, PR137 advice, and PR138
security. It adds orchestration, not another analyzer.

`ConversationMemoryStore` remains durable authority. Each turn records workspace
fingerprint, snapshot ID, intent, resolved subjects, context digest, evidence IDs,
truncation, provider/model, and status. Repository facts reload from snapshots rather
than being copied into memory. On snapshot change, old evidence is marked stale until
resolved. Memory is workspace-isolated, ordered, size-limited, and redacted.

Pipeline: normalize/classify; resolve subjects or request disambiguation; select
compatible snapshot results; retrieve bounded recent history with stale-lineage
labels; expand a bounded
relation-filtered neighborhood; rank/reduce evidence; build source-free prompt;
validate citations; persist response envelope.

Priority is current subject evidence, requested analysis, limitations/conflicts,
repository/module context, then bounded recent memory with lineage labels. Stable
top-k, quotas, diversity,
adjacency indexes, cached summaries, and lazy expansion bound large repositories.
Omitted counts and coverage are exposed.

Prompts state snapshot, intent, evidence, confidence, stale-memory labels, and permitted
claims; repository metadata and prior messages are untrusted. They require citations
and uncertainty and exclude source/secrets. Post-validation flags unknown citations.

For identical snapshot/configuration/question/history, resolution, retrieval, context,
digest, and prompt are deterministic; provider prose is not. Existing explain/memory
APIs remain compatible and provider failure leaves recoverable turn state.

Tests cover follow-ups, subject switching, ambiguity, stale snapshots, isolation,
limits, concurrency, citation/grounding, failure/retry, prompt injection, source and
secret exclusion, truncation, old snapshots, JUnit, and compact million-item count
metadata. Autonomous
execution, code changes, shared multi-user chat, and cross-repository memory are
deferred.
