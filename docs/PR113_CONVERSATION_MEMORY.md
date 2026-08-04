# PR113 — Conversation Memory

`ConversationMemoryStore` persists workspace-scoped Atlas AI conversations in
`.atlas/conversation.sqlite3`. Conversations are keyed by ASS workspace
fingerprint; messages retain deterministic positions, roles, timestamps, and
string references to snapshots, diagnostics, explanations, reviews, or
questions.

The versioned SQLite schema uses foreign keys and transactions. PR113 provides
storage only; prompt integration belongs to the later reasoning engines.

PR139 extends the same schema additively with `conversation_turns`. A turn stores
only workspace/snapshot lineage, intent, canonical subject IDs, the selected context
digest and evidence IDs, truncation, provider/model identity, limitations, and a
`running`, `completed`, or `failed` status. Repository facts remain authoritative in
semantic snapshots and are not copied into conversation memory. Existing PR113
conversations and messages remain readable.
