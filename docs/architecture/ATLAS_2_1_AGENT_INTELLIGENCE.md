# Atlas 2.1 — Agent Intelligence

Atlas 2.1 is the deterministic enterprise repository-intelligence backend for
external coding agents. Kiro/Codex write; Atlas maps, grounds, and verifies.
Atlas does not attempt to replace the agent that interprets source, edits files,
runs tools, or iterates on an implementation.

## Supported architecture

```text
SyGMa
-> Atlas validated snapshot and full internal graph
-> bounded story-specific context and graph projection
-> Kiro / Codex
-> implementation
-> Atlas-guided validation and review
```

Atlas supplies canonical identities, authoritative project ownership, resolved
and candidate call relationships, impact intelligence, represented TEST
reachability, story planning, requirement reconciliation, source locations, and
explicit uncertainty. External agents retain responsibility for reading source
and making changes.

## Primary workflow

Create the package in an external artifact directory:

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\path\story.txt `
  --output C:\temp\atlas-context `
  --depth story
```

This normal path requires neither a subject nor a project. Atlas uses bounded
PR172 discovery, semantic search, the canonical callable index, and Java graph
authority to rank one or more represented roots. A PR172-selected exact root is
authoritative; additional exact, semantic, or ambiguous matches remain
candidates until source inspection. The merged graph includes every selected
root neighborhood within the tier cap.

`--subject` is an expert override when an exact canonical target is already
known. `--project` is an optional authoritative module constraint. Unknown or
unproductive project constraints fail closed.

The UTF-8 story file is read in full and accepts at most 50,000 normalized
characters and 256 KiB. Oversized input fails explicitly; it is never
truncated. This dedicated export policy does not increase the smaller
interactive/provider request limit.

The output directory contains exactly:

| Artifact | Purpose |
| --- | --- |
| `context.md` | Concise, agent-ready repository and story guidance |
| `context.json` | Versioned deterministic context package |
| `graph.json` | Versioned machine-readable graph projection |
| `graph.mmd` | Deterministic bounded Mermaid view for inspection |

Give the external agent the original story, `context.md`, and `graph.json`.
Source remains in the repository for the agent to inspect; Atlas exports paths
and spans instead of whole source files.

## Discovered roots

Subject-free packages explicitly separate authoritative/resolved roots from
candidate/uncertain roots. Each root records canonical ID, callable identity,
project, source span, rank, confidence, authority, matched story anchors,
rationale, and bounded evidence IDs. Atlas builds neighborhoods around selected
candidate roots because they are useful investigation starts, but never
relabels their call relationships or implementation relevance as resolved.
When exact code-shaped anchors are absent, a bounded supplementary pass
automates natural story searches such as `Topic search` or `retrieve Projects`.
Those lexical/semantic results are always candidates and carry explicit
omission/uncertainty reporting.

## Graph tiers

- `story` is the default Level 0 projection, targets 20–100 high-information
  nodes, and is capped at 100 nodes/600 edges.
- `expanded` is an explicit Level 1 projection capped at 500 nodes/4,000 edges.
- Level 2 is the full Atlas graph. It remains internal and is never exported as
  an LLM context package.

Stable ranking prioritizes authoritative roots, candidate roots, resolved
direct callees and callers, represented tests, requirement-relevant
collaborators, bounded impact, important candidates, and uncertainty.
Neighborhoods are merged by canonical identity and deduplicated before final
tier selection. Root and graph truncation are represented through omission
counts.

Resolved relationships and `possible_call_target` candidates remain distinct.
`story_requirement_relation` is requirement evidence, not a Java call edge.
Represented TEST reachability identifies graph-backed test relationships; it is
not proof of runtime coverage.

## Determinism and authority

`context.json` carries an `agent-context:v1:<sha256>` fingerprint and
`graph.json` carries an `agent-graph:v1:<sha256>` fingerprint. Snapshot identity,
normalized story input, selected constraints, deterministic plan identity,
projection configuration, and projection contents participate as appropriate.
Repeated runs with identical validated inputs produce byte-identical artifacts.

Canonical IDs, project ownership, resolved call edges, source locations, and
represented TEST identities are authoritative repository guidance. Candidate
edges and requirements with `PARTIAL`, `MISSING`, or `NOT_PROVEN` status require
source investigation before editing.

PR175 explicit-subject packages retain their accepted v1 serialized envelope.
Subject-free/multi-root packages use the internal v2 envelope because they add
ranked discovered-root classification, confidence, authority, story anchors,
source spans, rationale, and evidence IDs. Fingerprint prefixes remain the
versioned `agent-context:v1` and `agent-graph:v1` algorithms; projection format
version and fingerprint algorithm version are intentionally separate.

## Deployment beside SyGMa and coding agents

Atlas reads SyGMa's existing checksum-verified `.ass` snapshot. The context
output must be outside the SyGMa source tree. The supported export path performs
no source scan and no source mutation and does not require an engineering
provider, Ollama, GPU, Maven, or Java runtime.

A practical deployment keeps Atlas and the external coding agent beside the
same repository checkout. Atlas produces the bounded package; Kiro or Codex
consumes it and inspects the referenced source. Atlas-selected represented tests
are the first validation set. Broader validation and post-change comparison can
then be applied according to repository policy.

## Experimental internal workflow

`atlas ai session`, including `/implement`, `/apply`, and `/verify`, remains the
experimental engineering-agent runtime. It is retained for controlled internal
work and is not the primary Atlas 2.1 workflow. PR174 executable verification is
not included on canonical main and remains future/experimental work.

## Current limitations

- Atlas does not implement the external coding agent's editing loop.
- Full-graph live query commands and MCP integration are future work.
- Post-change package-versus-diff enforcement is not yet a complete workflow.
- Represented TEST reachability is not dynamic execution or coverage evidence.
- Candidate call targets are explicitly uncertain.
- Semantic or exact-name relevance does not by itself make a root an
  authoritative implementation target.
- Context export depends on a compatible validated snapshot already being
  present; snapshot creation is a separate operation.

Operational deployment, story limits, snapshot procedures, starter prompt, and
daily commands are documented in
[the Atlas 2.1 Operations Guide](../ATLAS_2_1_OPERATIONS_GUIDE.md).
