# PR139 Interactive Engineering Chat

## Scope

PR139 provides repository-aware architectural conversation grounded in persisted
Atlas semantic data. It extends the existing PR116 `AskEngine`; that engine remains
the unique conversation orchestrator. PR139 composes authoritative services and does
not add another analyzer, repository model, graph, search engine, subject resolver,
evidence system, confidence model, ranking engine, or conversation store.

The required foundation is:

- verified semantic snapshots;
- PR129 canonical graph identity;
- PR130 evidence and confidence contracts;
- PR134 canonical resolution and scoped explanation;
- PR135 structured semantic search;
- PR113 workspace-local conversation memory.

PR133 repository reports and PR136--PR138 impact, refactoring, and security results
are optional enrichment. A conversation remains valid when those optional sections
are absent, but Atlas must name the missing capability when the question requires it.

PR139 begins Interactive Engineering Chat even though the first PR138 Security
Intelligence slice remains intentionally partial. It consumes compatible PR138 facts;
it does not implement deferred security producers.

## Architecture

The grounded turn pipeline is:

```text
verified semantic snapshot + workspace-local conversation
  -> normalize question and turn state
  -> validate workspace and snapshot lineage
  -> resolve subject or return deterministic disambiguation
  -> retrieve PR135 structured facts
  -> select compatible optional findings
  -> select bounded recent history and graph context
  -> close, rank, and reduce evidence deterministically
  -> build source-free context, digest, and prompt
  -> invoke the existing provider
  -> validate citations against selected evidence
  -> persist redacted response envelope and status
```

`AskEngine` owns this orchestration only. Specialized services remain authoritative
for explanation, search, impact, refactoring, and security semantics. Ask does not
scan source, rediscover findings, traverse a competing graph, rescore confidence or
severity, infer exploitability or reachability, or generate code changes.

## Conversation-memory authority

`ConversationMemoryStore` remains the durable authority for conversation state.
Conversation order is the stored deterministic message position, not timestamps or
database return order. Every conversation is bound to one workspace fingerprint.
A caller cannot reuse a conversation ID from another workspace.

Each new turn retains bounded lineage and diagnostic references sufficient to audit
the response:

- workspace fingerprint and semantic snapshot ID;
- normalized intent;
- resolved canonical subject IDs or ambiguity state;
- deterministic context digest;
- selected evidence IDs;
- truncation and omitted counts;
- provider and model identity when available;
- turn status.

The completed assistant message stores the derived grounding status in its bounded
references. Full citation validation remains part of the returned `AskResult`; it is
not duplicated as a separate `conversation_turns` column.

Repository summaries, graph nodes, search results, findings, and other repository
facts are not copied into memory. They are reloaded from the referenced verified
snapshot. This prevents conversation storage from becoming a second repository
database.

Older messages without PR139 references remain readable. Their missing lineage is
reported as unavailable rather than synthesized. A snapshot change marks prior
evidence references stale until the subjects and evidence are resolved against the
current snapshot. Historical prose may remain visible as conversation history, but
it is not current repository evidence.

## Subject resolution and follow-ups

PR134 remains the only canonical subject resolver. Explicit subjects are normalized
and resolved through that service. Ambiguous candidates produce a deterministic
disambiguation response; Ask does not select the first graph or search match.

A follow-up may reuse the most recent compatible resolved subject only when its
workspace and snapshot lineage remain valid. Explicit subject switching replaces
that conversational focus deterministically. An unresolved or stale prior subject
does not become valid because a provider refers to it by name.

## Retrieval and context selection

PR135 supplies required structured retrieval. Repository-report prose is not a
search index and prior provider answers are not semantic facts. PR134 scoped
explanation supplies subject evidence, while the PR129 graph supplies only bounded,
traceable relationships supported by existing evidence.

Context selection prioritizes:

1. current resolved-subject evidence;
2. the structured analysis requested by the question;
3. limitations, incompatibilities, and conflicting evidence;
4. repository, project, module, and bounded graph context;
5. bounded recent conversation history, with stale lineage labelled explicitly.

PR139 does not add a history relevance or embedding engine. The existing durable
message order remains authoritative, and selection takes the configured recent tail
up to the hard limit.

Stable ranking, per-source quotas, canonical tie-breaking, and explicit limits bound
selection. Omitted counts and capability coverage remain visible. A graph relation
that is modeled but not populated is unavailable evidence, not permission to infer
the relation.

## Optional capability semantics

Optional sections enrich only compatible turns:

- PR133 may provide a deterministic repository report;
- PR136 may provide impact paths and limitations;
- PR137 may provide evidence-backed refactoring advice;
- PR138 may provide security findings, coverage, and limitations.

If an optional section is absent, malformed, stale, or incompatible, Atlas states
that the structured capability is unavailable. It does not ask the LLM to recreate
the missing result.

Security integration preserves PR138 wording and contracts. Zero findings are not
proof of security; rule execution is not complete coverage; confidence is not
exploitability; impact is not reachability; severity is not priority; and unresolved
subjects are not valid resolved findings. Chat may say that rules executed, findings
were observed, evidence is incomplete, exploitability was not assessed, or a
capability is unavailable. It must not strengthen those statements.

## Evidence and citation validation

Every factual repository statement admitted to the prompt is backed by evidence from
the verified snapshot or by an explicit capability/limitation record. Evidence IDs
are selected and ordered before provider execution. The provider cannot add evidence,
change confidence, or make an unavailable capability available.

Provider citations are checked against the evidence IDs admitted to the turn.
Unknown, stale, or omitted citations are flagged and cannot be presented as verified
Atlas conclusions. Citation validation does not turn provider prose into semantic
evidence; it verifies only that a reference belongs to the bounded context.

Conflicting evidence is retained with its limitations. It is not silently resolved
by provider preference.

## Source-free and prompt-injection boundary

The conversation context may contain canonical IDs, fixed semantic labels, bounded
repository metadata, structured findings, evidence IDs, confidence, capability
state, limitations, omitted counts, and prior redacted messages.

It must not contain:

- raw source, comments, or arbitrary source literals;
- discovered secrets or credentials;
- complete semantic snapshots;
- absolute machine paths, usernames, private endpoints, or private remotes;
- unbounded symbol, graph, finding, or history lists;
- provider prose represented as Atlas evidence.

Repository metadata and previous messages are untrusted prompt input. The prompt
labels them as data, requires evidence citations and explicit uncertainty, and does
not permit embedded repository text or earlier messages to redefine system rules.
Sensitive material is rejected or redacted before context identity is calculated.
If a provider response requires material redaction, its submitted citation IDs are
discarded and the result remains ungrounded; redaction cannot launder unsafe prose
into a verified Atlas conclusion. Provider and model metadata are sanitized before
persistence.
Private IP addresses, localhost references, and values explicitly labelled as a
host, server, endpoint, or connection target are redacted. Dotted canonical semantic
identifiers such as Java package or type names remain available because syntax alone
cannot distinguish them safely from host names; producers that own structured network
metadata must label private endpoints before projection.

## Determinism

For the same verified snapshot, configuration, normalized question, and compatible
history, Atlas deterministically produces the same:

- intent and subject-resolution result;
- capability-availability state;
- search and graph selection;
- evidence set and order;
- truncation and omitted counts;
- context object and digest;
- prompt request;
- citation-validation result for the same provider response;
- persisted structural response envelope.

Canonical tie-breaking must not depend on dictionary or set order, filesystem order,
analyzer discovery, graph traversal accidents, timing, thread scheduling, or database
row order.

Provider prose is explicitly outside the deterministic semantic contract. Atlas can
reproduce the context and prompt sent to a provider, but it does not claim that an
LLM will return byte-identical wording. Provider text never participates in snapshot,
graph, evidence, confidence, or repository-report identity.

## Availability and failure behavior

An unavailable required snapshot, PR134 resolver, or PR135 search input prevents a
grounded answer and produces an explicit unavailable or insufficient result. Missing
optional providers degrade only the capability they own.

Provider failure or empty output does not publish a successful assistant answer. The
turn retains recoverable failure state and enough deterministic context identity for
a retry. A retry must not silently duplicate a successful turn or reinterpret a
failed provider response as evidence.

Invalid citations, stale lineage, cross-workspace conversation access, incompatible
feature schemas, and malformed persisted references are surfaced explicitly. They
are not converted into empty successful context.

## Compatibility

PR139 is an additive consolidation:

- existing Ask request/result and CLI use remains valid;
- PR113 conversations remain readable and workspace-isolated;
- PR134 explanation and PR135 search contracts remain authoritative;
- PR136 impact, PR137 refactoring, and PR138 security APIs retain their behavior;
- snapshots that predate an optional capability remain usable with explicit
  availability;
- normal semantic snapshots are read-only during conversation;
- provider-free deterministic repository explanations remain separate from
  provider-generated chat prose.

Public additions are limited to concrete PR139 behavior. No hypothetical autonomous,
multi-user, cross-repository, tool-execution, or code-modification fields are added.

### Exact additive contracts

The original first three positional fields remain unchanged:

- `AskRequest(question, conversation_id=None, history_limit=12)`;
- `AskResult(answer, snapshot_id, conversation_id)`.

`AskRequest` adds optional `subject`, `kind`, `project`, `language`, `capabilities`,
`maximum_input_tokens`, and `result_limit`. Conversation IDs are positive integers;
history is non-negative and capped to 100 selected messages; input-token budgets are
at least 1,024; and result limits are from 1 through 20. Deserialization rejects
boolean, floating-point, numeric-string, or mixed-type substitutes rather than
coercing them.

`AskResult` adds the immutable `ChatContext`, citation validation, provider/model,
limitations, and a derived `grounded` flag. Grounding requires an exact citation in
the delivered redacted answer, membership in the selected evidence closure, and a
retained semantic-search section. A resolved subject also requires retained canonical
explanation. Every explicitly requested optional capability must be available or
partial, retained in context, and cited through evidence owned by its retained
section. The serialized `grounded` value is checked on reload. Context-free legacy
results remain valid but are always ungrounded.

`ChatEngine`, `ChatRequest`, and `ChatResult` are aliases of the existing Ask types;
they do not introduce another engine. Chat context uses schema version 1, producer
`atlas-pr139/1`, exact `from_dict()` round trips, deep immutable JSON content, and a
SHA-256 context digest. The selector retains at most six search hits, eight
explanation facts, three optional provider sections with at most one compact item
from each selected provider, and 64 evidence records per section. Requested and
intent-relevant providers rank first; total, included, and omitted capability counts
remain explicit. Every retained capability item keeps its own evidence IDs. Whole
sections are selected deterministically; partial JSON objects are not cut to meet a
budget.

Conversation schema version 1 is extended additively with `conversation_turns`.
States are `running`, `completed`, and `failed`. Each turn stores workspace/snapshot
lineage, intent, subjects, context digest, evidence IDs, truncation, provider/model,
limitations, and timestamps. Assistant-message insertion and successful transition
occur in one SQLite transaction. Concurrent writers receive unique stored positions;
the persisted order is authoritative.

`atlas ai ask` and `atlas ai chat` invoke the same function and support
`--conversation`, `--subject`, `--kind`, `--project`, `--language`, repeatable
`--capability`, `--history-limit`, `--limit`, `--max-input-tokens`, and `--json`.
Plain output warns whenever the derived result is not grounded. JSON output includes
the full bounded validation envelope.

The stable `moughorai.public_api` fixture is deliberately unchanged: PR139 extends
the existing AI facade rather than promoting experimental chat DTOs into that
cross-package compatibility surface. `AtlasAiCapabilities.engineering_chat` is
appended after all legacy positional fields, so prior positional construction keeps
its meaning.

## Bounds and performance

History, search hits, graph expansion, findings, evidence, citations, and prompt
tokens are bounded before provider invocation. Selection uses stable top-k behavior
and reports omitted counts. Existing indexes and feature-local caches may be reused;
a new shared cache is not introduced without a second real consumer and matching
identity and invalidation semantics.

Performance measurements distinguish deterministic Atlas context construction from
provider latency. Repeated-request measurements use identical snapshot,
configuration, question, and history inputs. Provider timing and prose are reported
separately and are not treated as deterministic repository artifacts.

The implementation records three separate M2 measurement phases:
`engineering_chat.context`, `engineering_chat.prompt`, and
`engineering_chat.provider`. This instrumentation is available through the API-level
`MeasurementSession`; PR139 does not add a second profiling or CLI sidecar system.

## Deferred work

PR139 deliberately defers:

- autonomous command or tool execution;
- source or configuration changes;
- automatic patches and fixes;
- shared multi-user conversations;
- cross-repository conversation memory;
- PR140 Git-aware change review;
- new analyzers or missing PR136--PR138 producers;
- LLM-created findings, evidence, confidence, severity, priority, impact, security
  conclusions, or refactoring advice;
- speculative shared caches, distributed chat state, and server protocols.

Interactive Engineering Chat remains an evidence-grounded conversation layer over
persisted Atlas intelligence, not an autonomous coding agent or a replacement for
deterministic static analysis.
