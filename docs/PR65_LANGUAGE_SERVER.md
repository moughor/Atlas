# PR65 — Language Server Diagnostics Bridge

PR65 adds a dependency-free JSON-RPC/LSP bridge for editor diagnostics.

## Capabilities

- LSP positions, ranges, diagnostics, and publish payloads.
- Conversion from Atlas-style finding objects or mappings.
- Offset and line/column source mapping.
- Deterministic diagnostic ordering and serialization.
- Document version protection against stale analysis.
- `initialize`, `shutdown`, `exit`, `didOpen`, `didChange`, and `didClose` handling.
- Full-document synchronization suitable for an initial VS Code or IntelliJ adapter.
