# PR99 — Governance

Atlas governance is opt-in. `GovernanceEngine` evaluates viewer, analyst, and
administrator permissions plus allowed-project, maximum-worker, and
force-analysis constraints. `GovernancePolicy.from_options` reads
`governance.allowed_projects`, `governance.maximum_workers`, and
`governance.allow_force_analysis` from PR71-style resolved options.

`GovernanceAuditLog` persists decisions as append-only JSONL. Every record
contains the previous record hash and its own SHA-256 checksum, so truncation,
reordering, and modification are detectable. Run `atlas governance
<workspace>` to validate `.atlas/governance-audit.jsonl`.
