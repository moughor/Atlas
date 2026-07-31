# PR138 Design — Security Intelligence

PR138 consolidates existing Java security, interprocedural taint, taint policy,
multi-module, incremental, security knowledge, explanations, CI, and LSP results.
Those engines remain authoritative; PR138 adds canonical identity, evidence
normalization, graph context, prioritization, and AI explanation—not a new scanner.

The taxonomy includes secrets, SQL injection, XSS, SSRF, path traversal, unsafe
deserialization, dangerous reflection, and general taint. A category is `analyzed`
only when its existing analyzer ran for that language/scope. Common envelopes retain
rule ID, severity, semantic locations, taint path, sanitizers, confidence, CWE/knowledge
references, and producer. Unsupported categories are `not_analyzed`; names do nothing.

Canonical calls, dependencies, ownership, entrypoints, and impact give context.
Specialized taint graphs own flow; only summaries/evidence references enter snapshots.
Missing calls reduce coverage, never prove safety. Existing multi-module scanning owns
cross-project propagation.

Priority combines authoritative severity, path completeness, exploit prerequisites,
exposure, scope, and PR136 blast radius; confidence stays separate. AI receives
structured redacted metadata and approved remediation knowledge, never raw source,
secrets, or literals.

Tests reuse security suites and add taxonomy/deduplication, all categories,
sanitization/unknown flow, redaction, unsupported languages, missing calls,
cross-module evidence, ranking, prompts, round-trip, incrementality, CI/LSP
compatibility, JUnit, and scale. New language engines, runtime penetration tests,
vulnerability feeds, exploit execution, and automatic fixes are deferred.
