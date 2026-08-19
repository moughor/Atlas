# Atlas 2.1 Operations Guide

Atlas 2.1 is the deterministic repository-intelligence backend used beside
SyGMa and an external coding agent. **Kiro/Codex write; Atlas maps, grounds,
and verifies.**

```text
Jira story
-> Atlas validated snapshot and internal graph
-> context.md + context.json + graph.json + graph.mmd
-> Kiro / Codex
-> implementation and repository validation
```

Atlas Agent Context is agent-neutral. It does not implement an autonomous
coding loop and does not require Ollama, a provider, a GPU, Maven, or Java.

## Installation and first start

Atlas requires Python 3.12 or newer and uses `pyproject.toml`.

```powershell
git clone https://github.com/moughor/Atlas.git C:\Atlas
Set-Location C:\Atlas
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -B -m moughorai.atlas_cli --version
```

The expected release output is `Atlas 2.1.0`. For development and release
validation, install `python -m pip install -e ".[dev]"`.

The module command makes the selected Python environment explicit. The
installed `atlas` command is equivalent when the virtual environment is active.

## Recommended workstation layout

```text
C:\Atlas\
C:\sygma\sygma\
C:\AtlasData\
C:\AtlasContexts\
```

- `C:\Atlas\` contains Atlas and its Python environment.
- `C:\sygma\sygma\` is the checkout Kiro/Codex will edit.
- `C:\sygma\sygma\.atlas\` is Atlas workspace state.
- `C:\AtlasData\` may hold approved workstation operational artifacts.
- `C:\AtlasContexts\` holds story packages outside SyGMa.

These paths are recommendations, not hard-coded Atlas configuration.

## Snapshot operations

Agent Context consumes an existing checksum-verified semantic snapshot:

```powershell
python -B -m moughorai.atlas_cli snapshot status `
  --root C:\sygma\sygma `
  --json
```

The JSON identifies the exact path, snapshot ID, resolution method, workspace,
and validation state. When no usable snapshot exists, run:

```powershell
python -B -m moughorai.atlas_cli analyze C:\sygma\sygma
```

A fully successful analysis publishes an immutable historical `.ass` file and
atomically updates `C:\sygma\sygma\.atlas\ass\latest.ass`. A failed analysis
does not publish a new `latest.ass`.

An approved snapshot stored elsewhere can be validated and registered:

```powershell
python -B -m moughorai.atlas_cli snapshot activate `
  C:\AtlasData\approved-sygma.ass `
  --root C:\sygma\sygma `
  --json
```

An active registration precedes workspace `latest.ass`. An explicit
`--snapshot` precedes both and fails closed if that exact file is unavailable.

`snapshot status` validates selection, checksum, schema, and registered
identity. It does not compare every current source byte with the stored
workspace fingerprint. After a SyGMa branch switch, HEAD advance, or significant
source change, run `analyze` and then `snapshot status` again.

Do not blindly copy an old `.atlas` directory or snapshot to another checkout.
The snapshot must represent the repository Kiro/Codex is modifying.

## Basic Atlas operations

```powershell
python -B -m moughorai.atlas_cli --version

python -B -m moughorai.atlas_cli snapshot status `
  --root C:\sygma\sygma `
  --json

python -B -m moughorai.atlas_cli search "CacheService" `
  C:\sygma\sygma `
  --limit 10
```

Snapshot-backed search is deterministic and provider-free.

Start the interactive runtime with:

```powershell
python -B -m moughorai.atlas_cli ai session C:\sygma\sygma
```

Current session commands include:

- `/search <text> [limit]`, `/use <result-number>`, `/subject`, and `/project`;
- `/answer [summary|detail|full]`, `/impact`, `/stats`, and `/exit`; and
- `/story`, `/story-file <path>`, `/ask-file <path>`, and `/plan [detail]`.

Experimental engineering-agent commands are documented separately below.

## Story input policies

The primary `agent context --story-file` path accepts UTF-8 only, reads the
whole file, and enforces:

- at most 50,000 characters after deterministic normalization; and
- at most 256 KiB (262,144 bytes) in the UTF-8 file.

Oversized and invalid UTF-8 files fail explicitly. Atlas never silently
truncates a story. Graph and context outputs remain independently bounded.

Interactive `/ask-file` and `/story-file` retain their provider-facing maximum
of 3,000 characters and 12,000 bytes. Multiline `/story` uses the same
3,000-character limit:

```text
/story
Paste the story here.
/end
```

Use `/cancel` to discard multiline entry. These interactive limits are
independent of Agent Context.

## Primary Atlas and Kiro/Codex workflow

Save the complete Jira story as UTF-8 text. The normal command requires neither
a subject nor a project:

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\Stories\SYGMA-12345.txt `
  --output C:\AtlasContexts\SYGMA-12345 `
  --depth story
```

Atlas performs initial deterministic repository discovery. It may return one
authoritative root, multiple high-value roots, candidate roots, or a bounded
package that explicitly says no sufficiently authoritative root was found.
Candidate relevance never becomes resolved dependency authority.

The output directory contains exactly:

- `context.md` — concise human/LLM story intelligence;
- `context.json` — the structured deterministic `AgentContextPackage`;
- `graph.json` — canonical nodes and typed story-specific edges; and
- `graph.mmd` — deterministic Mermaid text for human inspection.

Normally give the story, `context.md`, and `graph.json` to Kiro/Codex.
`context.json` supports richer integrations; `graph.mmd` is a visual aid.

The output directory must be outside SyGMa. Atlas fails rather than deleting
unrelated entries from an existing output directory.

### Post-change review

After Kiro/Codex edits SyGMa, compare the working tree with an explicit
pre-change Git reference:

```powershell
python -B -m moughorai.atlas_cli agent review C:\sygma\sygma `
  --context C:\AtlasContexts\SYGMA-63059\context.json `
  --base <pre-change-ref>
```

`--base` is required and is resolved with Git; Atlas never infers it. The
command reads the `graph.json` referenced by `context.json`. Use `--graph`
only to select an explicitly stored matching graph and `--json` for canonical
machine-readable output.

Agent review is read-only. It reads tracked Git diff metadata, non-ignored
untracked paths, the existing context/graph package, and the verified snapshot.
It does not read untracked contents, edit source, rescan, publish a snapshot,
invoke a provider, or run Java/Maven.

The result classifies scope relative to the precomputed Atlas map:

- `WITHIN_EXPECTED_SURFACE` means an expected path, canonical subject, or
  context root matched;
- `PLAUSIBLE_SCOPE_EXPANSION` means bounded project, graph, test, or
  requirement evidence explains an additional file;
- `UNEXPECTED_SCOPE` means a represented local change lacks that explanation;
  and
- `UNREPRESENTED_CHANGE` means pre-change Atlas authority cannot sufficiently
  represent the change, commonly for a new untracked file.

These are scope classifications, not correctness verdicts. Call edges, TEST
reachability, declaration identity, and requirement status come from the
pre-change snapshot and may be stale after edits. Represented tests are the
first tests to inspect/run, not proof of runtime coverage. Requirement status
is never changed merely because a file was edited.

Atlas 2.1 context packages do not record the Git commit that generated them.
The review therefore reports `UNKNOWN_BASE_PROVENANCE` even when the supplied
base resolves successfully. Confirm the intended pre-change ref operationally.

### Advanced/manual targeting

Use `--subject` when the exact canonical target is already known or an expert
intentionally overrides discovery:

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\Stories\SYGMA-12345.txt `
  --output C:\AtlasContexts\SYGMA-12345-targeted `
  --subject method:0123456789abcdef01234567 `
  --depth story
```

Use `--project` to constrain discovery to an authoritative project/module:

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\Stories\SYGMA-12345.txt `
  --output C:\AtlasContexts\SYGMA-12345-project `
  --project sygma-example-ejb `
  --depth story
```

An unknown project, or a project constraint yielding no represented discovery
root, fails closed. These are advanced hints, not daily requirements.

## Kiro/Codex starter prompt

```text
Implement this Jira story in SyGMa.

Before exploring the repository, read:

<AtlasContext>\context.md
<AtlasContext>\graph.json

Use Atlas canonical identities, authoritative project ownership, resolved call
relationships, source locations, and represented test identities as
authoritative repository guidance.

Start with Atlas ranked roots. Investigate candidate roots from source before
treating them as implementation targets. Investigate PARTIAL and NOT_PROVEN
requirements directly from source before deciding whether they require changes.

Candidate/possible edges are not resolved dependencies. Use Atlas-selected
represented tests as the initial validation set.

If you modify files outside the Atlas-identified implementation surface,
explain why. Do not make unrelated changes.

At completion report:
- files inspected
- files changed
- why each file changed
- tests executed
- remaining uncertainty
- where Atlas context was insufficient
```

## Graph modes

`--depth story` is the default. It targets roughly 20–100 high-information
nodes and is capped at 100 nodes and 600 edges.

`--depth expanded` merges a wider dependency/impact neighborhood and is capped
at 500 nodes and 4,000 edges:

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\Stories\SYGMA-12345.txt `
  --output C:\AtlasContexts\SYGMA-12345-expanded `
  --depth expanded
```

The complete Atlas graph remains internal. Do not dump it into routine LLM
context.

## Reading graph information

- `canonical subject ID` is Atlas's stable represented repository identity.
- `project_ownership` is authoritative project/module identity.
- `resolved_direct_call` is a represented resolved Java call.
- `possible_call_target` is candidate/unproven; candidate is not resolved.
- `reverse_upstream` is bounded impact toward represented consumers.
- `represented_test` and `forward_test_reachability` are represented TEST
  intelligence, not runtime coverage.
- `story_requirement_relation` connects a requirement to evidence; it is not a
  Java call edge.
- `IMPLEMENTED` means bounded represented evidence supports reconciliation.
- `PARTIAL` is not missing; only part is represented.
- `MISSING` means required evidence was absent from the bounded selected surface.
- `NOT_PROVEN` is not false; deterministic evidence is insufficient.

`context.md` separates authoritative/resolved roots from candidate/uncertain
roots and reports rank, project, source, and rationale.

## When Kiro/Codex needs more context

1. Start with `--depth story`.
2. Let the agent inspect ranked roots and referenced source.
3. If insufficient, regenerate with `--depth expanded` into a separate output.
4. Give the expanded `context.md` and `graph.json` to the agent.

Live graph queries, MCP integration, and automated post-change graph review are
future capabilities, not Atlas 2.1 commands.

## Experimental engineering-agent runtime

`atlas ai session` is the **experimental engineering-agent runtime**, not the
primary production workflow. Current experimental commands include:

- `/plan [detail]` — deterministic story reconciliation;
- `/implement` — provider-backed preview-only patch proposal;
- `/apply` — apply only in an isolated linked Git worktree;
- `/verify` — show validation commands without executing them; and
- `/diff` — compare current changes with the proposal.

`/verify run` is intentionally unavailable. PR174 executable verification is
excluded and remains future/experimental work. Provider-backed experiments may
require Ollama or another provider; `agent context` does not.

## Updating Atlas

Do not pull over local source changes:

```powershell
Set-Location C:\Atlas
git status --short --branch
git fetch origin
git pull --ff-only
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -B -m moughorai.atlas_cli --version
```

Stop on unexpected local modifications. A release deployment may check out an
organization-approved tag or commit before reinstalling.

## Updating SyGMa

After a branch switch, pull, or other significant checkout change:

```powershell
Set-Location C:\sygma\sygma
git status --short --branch
git rev-parse HEAD
python -B -m moughorai.atlas_cli snapshot status `
  --root C:\sygma\sygma `
  --json
```

Status validates selection, not byte freshness against the checkout. Run
`analyze` after the repository changes, verify the new snapshot, and generate
new story context. Existing context fingerprints remain tied to their original
snapshot and story.

## Troubleshooting

### Atlas command or module not found

```powershell
Set-Location C:\Atlas
.\.venv\Scripts\Activate.ps1
python --version
python -B -m moughorai.atlas_cli --version
```

Python must be 3.12 or newer. Re-run `python -m pip install -e .` if needed.

### No active snapshot

Run `snapshot status`. If neither an active registration nor
`.atlas\ass\latest.ass` exists, run `analyze` or activate an approved `.ass`.

### Invalid or stale snapshot

Checksum, schema, registration, and registered-ID errors fail closed. Re-run
`analyze` for the current checkout or activate the intended verified snapshot.
Do not manually edit snapshots or `active-snapshot.json`.

### Subject not found or roots uncertain

Read **Discovered roots** in `context.md`. Inspect candidate source and use
`--depth expanded` if necessary. Use `--subject` only when the exact identity is
known.

### Wrong project

Project names are exact Atlas identities. Remove `--project` for normal
autonomous discovery, or copy the exact project from Atlas output.

### Story path, encoding, or size error

Use an existing regular UTF-8 file. Agent Context accepts at most 50,000
normalized characters and 256 KiB and never truncates. Interactive story files
have the separate 3,000-character/12,000-byte policy.

### Context output directory error

Choose a writable directory outside SyGMa and keep unrelated files elsewhere.
Atlas writes only the four documented artifacts.

### Context generation fails

Run `snapshot status --json`, verify the story file, and remove unnecessary
advanced constraints. Missing Java graph artifacts require a valid snapshot
regenerated by `analyze`; context export itself never rescans.

### Kiro/Codex needs more context

Regenerate with `--depth expanded`. Do not export the full internal graph.

### Provider, GPU, Maven, or Java unavailable

`agent context` still works: it constructs no provider and needs no Ollama,
GPU, Maven, or Java runtime. External build/test work and experimental
provider-backed commands may have separate requirements.

## One-minute health check

```powershell
Set-Location C:\Atlas
git status --short --branch
python -B -m moughorai.atlas_cli --version

Set-Location C:\sygma\sygma
git status --short --branch
git rev-parse HEAD

python -B -m moughorai.atlas_cli snapshot status `
  --root C:\sygma\sygma `
  --json

python -B -m moughorai.atlas_cli search "CacheService" `
  C:\sygma\sygma `
  --limit 1
```

The final search is a small provider-free readiness check.

## Daily cheat sheet

### Start of day

1. Verify Atlas version and Git status.
2. Verify SyGMa branch, HEAD, and tracked work.
3. Check or regenerate the SyGMa snapshot.
4. Save the complete Jira story as UTF-8 text.
5. Generate story context without `--subject` or `--project`.
6. Give the story, `context.md`, and `graph.json` to Kiro/Codex.
7. Let the agent implement and run project validation/tests.
8. Run Atlas post-change scope review, then inspect the Git diff and remaining
   uncertainty.

### Generate context

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\Stories\SYGMA-12345.txt `
  --output C:\AtlasContexts\SYGMA-12345 `
  --depth story
```

### Expand context

```powershell
python -B -m moughorai.atlas_cli agent context C:\sygma\sygma `
  --story-file C:\Stories\SYGMA-12345.txt `
  --output C:\AtlasContexts\SYGMA-12345-expanded `
  --depth expanded
```

### Snapshot status

```powershell
python -B -m moughorai.atlas_cli snapshot status `
  --root C:\sygma\sygma `
  --json
```

### Review changes

```powershell
python -B -m moughorai.atlas_cli agent review C:\sygma\sygma `
  --context C:\AtlasContexts\SYGMA-12345\context.json `
  --base <pre-change-ref>
```

### Atlas version

```powershell
python -B -m moughorai.atlas_cli --version
```
