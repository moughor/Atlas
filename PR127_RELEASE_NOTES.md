# PR127 Release Notes

PR127 adds a deterministic Repository Summary Engine. It composes existing
Atlas inventory, framework, workspace, and dependency components into a
source-free machine-readable model published in semantic snapshots.

Nested projects are counted once, entry points and generated sources are
identified conservatively, and no LLM or build tool is executed.
