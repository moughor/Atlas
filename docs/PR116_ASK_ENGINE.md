# PR116 — Ask Engine

The Ask Engine answers natural-language questions from verified ASS context.
It can include a bounded, deterministically ordered PR113 conversation history,
records the new exchange, and instructs providers to report insufficient facts.

`atlas ai ask QUESTION ROOT` activates the engine.

PR139 keeps this engine as the single conversation orchestrator and adds the
`atlas ai chat` alias. The engine now composes bounded PR134 explanation and PR135
search context, optionally consumes compatible PR136--PR138 results, validates
provider citations, marks stale history, and persists recoverable turn lineage. The
original three positional `AskRequest` fields and three positional `AskResult` fields
remain compatible.
