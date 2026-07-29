# PR72 — Workspace Event Bus

PR72 adds a synchronous, thread-safe event bus for workspace lifecycle telemetry.

## Capabilities

- Typed workspace event kinds and structured payloads.
- Deterministic subscriber ordering by priority then registration order.
- Filtering by event kind, project, and custom predicates.
- One-shot subscriptions and explicit unsubscribe support.
- Bounded event history and structured callback failure reports.
- Batch publication and optional fail-fast delivery.

The bus is framework-independent and can be shared by the watcher, planner,
orchestrator, persistence layer, CLI, LSP, and future dashboard integrations.
