# PR53 — Versioned Policy Packs

PR53 adds strict YAML/JSON loading for declarative taint policies. Packs are schema-versioned, deterministic, serializable, and mergeable through a registry. Runtime overrides can enable or disable rules, change priority/severity/confidence, and add properties without modifying source files.

## Schema

A pack contains `schema_version`, `name`, `version`, optional metadata, and a list of PR52 policies. Unknown fields and invalid enum values fail fast. Empty packs load with a diagnostic warning.

## Compatibility

PR52 `TaintPolicy` and `TaintPolicyEngine` APIs are unchanged. A registry simply produces the same policy tuple or engine expected by PR52.
