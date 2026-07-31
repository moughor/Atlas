# PR133 Design — AI Repository Report

PR133 builds a deterministic repository report from PR127 summary, PR128 architecture,
PR129 graph, and available PR130–PR132 results. An LLM renders the model but cannot
introduce findings.

Sections:

1. Executive summary: identity, projects, languages/build systems, coverage.
2. Architecture: modules, dependencies, patterns, confidence/conflicts.
3. Repository health: analysis completion, tests, reachability, limitations.
4. Risks: ranked hotspots and impact.
5. Technical debt: evidence-backed dead/structural findings.
6. Quality: metrics/trends with units/cohorts.
7. Recommendations: deterministic actions linked to findings and prerequisites.

Every statement has evidence IDs, confidence, scope, and
`observed/unknown/not_analyzed`. “No issues” requires an executed covered negative
analysis. The prompt prioritizes identity/coverage, critical evidence, architecture,
risks, limitations, then detail. It is source-free, token-bounded, deterministically
truncated, and preserves citations. Large repositories use top-k and module rollups.

Existing `atlas ai explain` falls back to accepted PR127/PR128 context for old
snapshots. Tests cover missing/conflicting analyses, unsupported negatives,
recommendations, exact round-trip, prompt source exclusion, truncation, old snapshots,
recording providers, JUnit, and large-repository latency. PDF, autonomous remediation,
portfolio reports, and unsupported trend claims are deferred.
