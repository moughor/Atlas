# PR113 — Conversation Memory

`ConversationMemoryStore` persists workspace-scoped Atlas AI conversations in
`.atlas/conversation.sqlite3`. Conversations are keyed by ASS workspace
fingerprint; messages retain deterministic positions, roles, timestamps, and
string references to snapshots, diagnostics, explanations, reviews, or
questions.

The versioned SQLite schema uses foreign keys and transactions. PR113 provides
storage only; prompt integration belongs to the later reasoning engines.
