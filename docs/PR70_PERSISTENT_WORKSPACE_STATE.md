# PR70 — Persistent Workspace State

PR70 persists reusable workspace analysis state between Atlas processes.

## Capabilities

- Versioned JSON state with integrity checksum.
- Atomic replacement through a temporary file and `os.replace`.
- Project-level content fingerprints.
- Selective restoration of unchanged project results.
- Automatic invalidation of stale or removed projects.
- Custom result encoders and decoders.
- Orchestrator `save_state()` and `restore_state()` integration.
- Deterministic reports and serialization.

The default state file is `.atlas/workspace-state.json` beneath the workspace root.
