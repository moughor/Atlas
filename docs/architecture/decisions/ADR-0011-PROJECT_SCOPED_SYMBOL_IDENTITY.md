# ADR-0011 Project-Scoped Symbol Identity

Status

Implemented

Date

2026-07-30

---

## Context

Independent Java modules may legally define identical qualified names. A global
qualified-name key incorrectly treated those definitions as duplicates.

## Decision

Global semantic identity is `(project_id, qualified_name, kind)`. Lookup indexes
use `(project_id, qualified_name)`. Unscoped legacy symbols retain their former
identity and public lookup behavior.

## Alternatives Considered

- Prefixing `qualified_name` with a project was rejected because it would no
  longer represent the source-language name.
- Silently dropping later symbols was rejected because it loses valid facts.
- Allowing duplicates inside one project was rejected because it hides genuine
  Java declaration errors.

## Consequences

Independent modules coexist without ambiguity. Consumers can request one scoped
symbol or every definition of a qualified name. Snapshot records now expose
project identity for scoped symbols.

## Related PRs

PR121, PR122, PR123
