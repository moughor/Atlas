# PR139 Existing Capabilities

Status: completed pre-implementation audit retained as the architectural baseline.

Implementation note: PR139 subsequently implemented the selected orchestration
boundary below without changing its ownership analysis. One design refinement is
explicit: history is a bounded recent tail with stale-lineage labels, not a
subject-relevance ranking engine. The resulting contracts and measured validation
are recorded in `PR139_INTERACTIVE_ENGINEERING_CHAT.md`, `PR139_VERIFICATION.md`,
and `PR139_PERFORMANCE.md`.

## Authoritative roadmap interpretation

The official Atlas 2.x roadmap assigns **Interactive Engineering Chat** to PR139.
PR139 therefore begins that roadmap item; it is not a second PR138 Security
Intelligence implementation. PR138 deliberately remains a partial security slice,
and its deferred analyzers stay deferred unless a later authoritative roadmap item
supplies the required evidence.

The dependency matrix makes PR134 Explain Anything and PR135 Semantic Search the
minimum required predecessors. PR133 repository reports and PR136--PR138 impact,
refactoring, and security results are optional capability providers. Chat must work
without those optional results and must state when a requested structured capability
is unavailable or incompatible.

## Existing components

| Responsibility | Existing owner | PR139 reuse |
| --- | --- | --- |
| Natural-language question orchestration | PR116 `AskEngine` | Remains the single Ask/chat orchestrator and is extended rather than wrapped by a competing chat engine |
| Durable conversation storage | PR113 `ConversationMemoryStore` | Remains the workspace-local authority for ordered conversation turns |
| Verified persisted repository facts | Atlas Semantic Snapshot and snapshot store | Repository facts are loaded from a verified snapshot for every turn and are never copied into conversation memory |
| Canonical graph identity | PR129 `KnowledgeGraph` | Supplies bounded, relation-filtered repository context without a second graph |
| Evidence and confidence | PR130 evidence index and confidence contracts | Supply traceable citations and deterministic confidence; chat cannot create either |
| Token-bounded repository context | PR133 report projection | Optional repository-level enrichment when compatible |
| Canonical resolution and explanations | PR134 resolver and explanation services | Required subject resolution, disambiguation, evidence closure, and scoped explanation input |
| Structured retrieval | PR135 semantic search | Required intent-oriented retrieval over canonical facts and findings |
| Impact context | PR136 impact prediction | Optional; unavailable impact must not be inferred from graph proximity |
| Refactoring context | PR137 advisor | Optional; chat must not synthesize absent advice or code changes |
| Security context | PR138 security intelligence | Optional; existing coverage, confidence, severity, priority, and limitation meanings remain unchanged |
| Prompt construction and provider access | Existing semantic prompt and LLM abstractions | Build a bounded source-free request and invoke the configured provider without granting it factual authority |

The current `AskEngine` already validates a non-empty question, reads a bounded tail
of conversation history, records user and assistant messages, constructs an Atlas
semantic prompt, and invokes the configured provider. The existing memory store uses
a versioned transactional SQLite database, workspace fingerprints, deterministic
message positions, sorted string references, and a process-local synchronization
boundary.

These are the correct foundations for PR139. A new `ChatEngine`, graph, retriever,
resolver, evidence index, confidence calculator, or conversation database would
duplicate an existing responsibility.

## Gaps before PR139

The existing Ask path predates PR129--PR138 and does not yet provide the complete
roadmap conversation contract:

- a supplied conversation ID is not sufficient on its own to prove that the
  conversation belongs to the current workspace;
- history is ordered and bounded, but it is not selected by current subject,
  compatibility, or evidence relevance;
- snapshot changes are recorded only as string references and are not interpreted as
  stale evidence lineage;
- the current prompt path does not compose PR134 canonical resolution with PR135
  structured retrieval;
- ambiguity does not yet produce a deterministic disambiguation result;
- optional PR133 and PR136--PR138 capability availability is not represented as one
  coherent conversation context;
- the prompt does not yet expose evidence closure, omitted counts, capability
  conflicts, or citation constraints as a typed turn envelope;
- provider citations are not post-validated against the evidence selected for the
  turn;
- a provider failure does not yet have a complete recoverable turn status contract;
- deterministic context identity is not separated explicitly from nondeterministic
  provider prose.

None of these gaps requires another semantic analyzer. They require bounded
orchestration over already authoritative components.

## Selected PR139 boundary

The smallest independently useful PR139 slice extends `AskEngine` as the unique
orchestrator for a grounded repository conversation:

1. normalize the question and current conversation state;
2. verify workspace and snapshot lineage;
3. resolve an explicit or inferred subject through PR134, preserving ambiguity;
4. retrieve structured facts through PR135 and compatible snapshot sections;
5. include bounded recent workspace-local history with stale-lineage labels;
6. select and order a source-free evidence context deterministically;
7. expose unavailable, stale, incompatible, conflicting, and truncated capability
   state explicitly;
8. build a deterministic prompt and context digest;
9. invoke the existing provider boundary;
10. validate returned citation identifiers against the selected evidence set;
11. persist a redacted response envelope and recoverable status through the existing
    conversation-memory authority.

Repository facts remain in semantic snapshots. Conversation memory retains only the
conversation content and bounded references needed to reproduce or diagnose the
turn, such as workspace fingerprint, snapshot ID, intent, resolved subject IDs,
context digest, evidence IDs, truncation state, provider/model identity, and status.

## Capability degradation

PR134 explanation and PR135 search are mandatory. If either required capability is
missing or incompatible, the turn cannot claim to be a grounded PR139 response and
must return a deterministic unavailable or insufficient state.

PR133, PR136, PR137, and PR138 are optional. Their absence must not prevent a valid
conversation about evidence that is available from the required inputs. When a
question specifically requires one of them, chat states that the relevant structured
analysis is unavailable. It must not replace:

- missing impact with dependency proximity;
- missing refactoring advice with LLM suggestions;
- missing security coverage with an absence-of-findings claim;
- a missing repository report with fabricated executive conclusions.

## Compatibility and regression risks

- Existing `AskEngine`, request/result, CLI, provider, and conversation-memory uses
  must remain valid.
- Existing conversations and the version-1 memory schema must remain readable; any
  additional metadata must be additive and safely absent on older messages.
- Conversation IDs must not permit cross-workspace history access.
- A stale snapshot reference must not replay old evidence as current fact.
- Ambiguous subjects must not be resolved by first-match, traversal, or provider
  preference.
- Provider prose, prior messages, repository metadata, and retrieved names are
  untrusted input and cannot establish facts or confidence.
- Raw source, secrets, arbitrary literals, absolute paths, and complete snapshots
  must not cross the prompt or memory boundary.
- Optional provider absence must remain explicit rather than collapsing to an empty
  successful result.
- Context selection must not depend on database row accidents, dictionary/set order,
  filesystem traversal, worker completion, timing, or provider output.
- Provider failure must leave deterministic recoverable state without presenting a
  partial answer as successful.

## Rejected alternatives

- Continuing PR138 under the PR139 number conflicts with the official roadmap.
- A new chat or Ask engine duplicates PR116 orchestration.
- A chat-specific repository graph, search index, resolver, evidence model, or
  confidence model duplicates PR129, PR135, PR134, or PR130.
- Copying repository facts into conversation SQLite creates stale competing
  persistence and breaks snapshot authority.
- Requiring PR133 or PR136--PR138 would contradict the dependency matrix's explicit
  optional-capability semantics.
- Letting an LLM resolve identity, infer missing analysis, validate its own citations,
  or change confidence violates evidence-before-inference.
- Adding source scanning, taint analysis, impact traversal, or refactoring logic to
  `AskEngine` would duplicate specialized analyzers.
- Mutating normal semantic snapshots for a conversation would mix repository facts
  with transient user interaction.
- Autonomous execution, code modification, shared multi-user chat, and
  cross-repository memory are later work, not part of PR139.

## Validation focus

PR139 validation must distinguish deterministic Atlas artifacts from provider prose.
For identical verified snapshot, configuration, question, and history, subject
resolution, capability selection, evidence order, truncation, context digest, and
prompt must be identical. Provider-generated wording is not deterministic and must
not participate in repository fact identity.

Focused validation should cover follow-ups, subject switching, ambiguity,
cross-workspace isolation, stale snapshots, missing optional capabilities, citation
validation, provider failure and retry, prompt injection, source/secret exclusion,
bounds, legacy conversations, and preservation of PR136--PR138 behavior when their
optional results are consumed.
