# Atlas 2.1 — Agent Intelligence Release Notes

Version 2.1.0 establishes Atlas as the deterministic enterprise
repository-intelligence backend for external coding agents.

## Supported primary workflow

`atlas agent context` turns an existing validated repository snapshot and Jira
story into exactly four bounded artifacts: `context.md`, `context.json`,
`graph.json`, and `graph.mmd`. The story, Markdown context, and machine-readable
graph are the supported handoff to Kiro, Codex, or another coding agent.

The normal command is subject-free and project-free. Atlas performs the initial
repository discovery, ranks authoritative and candidate roots, and merges
their represented neighborhoods. Exact `--subject` and `--project` controls
remain available for advanced targeting.

Kiro/Codex write; Atlas maps, grounds, and verifies.

The release brings together the production intelligence path developed across
the Atlas platform:

- deterministic SyGMa repository intelligence and reusable repository runtime;
- canonical repository, project, type, callable, source, and evidence identity;
- Java call graph with resolved and candidate relationships kept distinct;
- impact intelligence and represented TEST reachability;
- deterministic engineering-answer authority and interactive subject discovery;
- multiline and file-backed story input;
- deterministic story planning and requirement reconciliation;
- full UTF-8 Agent Context story files up to 50,000 normalized characters and
  256 KiB, with explicit rejection and no truncation;
- conservative subject-free and multi-root discovery with ranked rationale;
- candidate-only supplementary discovery for natural story phrases when exact
  represented code anchors are absent;
- bounded agent context and graph projection for external coding agents; and
- retained controlled engineering-agent runtime, explicitly experimental.

## Context package guarantees

The default `story` projection targets 20–100 high-value nodes and is capped at
100 nodes/600 edges. The explicit `expanded` projection is capped at 500
nodes/4,000 edges. The complete Atlas graph remains internal. Stable root/node/
edge ordering, canonical deduplication, reported omission counts, versioned
context and graph fingerprints, source paths/spans instead of source dumps, and
strict output-path confinement make repeated identical exports byte-identical
and reviewable.

Context export requires no provider, Ollama, GPU, Maven, or Java runtime. It
loads the existing checksum-verified snapshot without rescanning or modifying
the repository. Public API v1 and the semantic snapshot schema remain unchanged.

## Experimental and deferred work

`atlas ai session` and its `/implement`, `/apply`, and `/verify` commands remain
the experimental engineering-agent runtime. They are not the supported primary
external-agent workflow. PR174 executable verification is excluded from
canonical main and remains future/experimental work.

Live graph query commands, MCP integration, complete post-change diff review,
dynamic test coverage, and executable verification are not part of Atlas 2.1.

## Upgrade identity

The canonical package, Python runtime, `atlas --version`, packaging metadata,
SARIF tool identity, and release documentation report version 2.1.0. Existing
public API v1 compatibility contracts remain intact.

See the [Atlas 2.1 Operations Guide](ATLAS_2_1_OPERATIONS_GUIDE.md) for the
PowerShell-first workstation workflow.
