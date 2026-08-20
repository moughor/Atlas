# Atlas Improvement Roadmap — Session 2

## Context

We have 184 stories from the SyGMa Jira export (`/home/meskeda/Downloads/ALM RTD Jira 2026-08-20T23_14_53+0200.csv`) and a working Atlas 2.1 installation scanning the full SyGMa codebase (991 MB snapshot, 21,000+ source files).

Session 1 delivered 4 improvements to story discovery. The commit is on `main`: `2c3f6ce`.

## Priority 1: Fix snapshot validation error

**Problem**: SYGMA-60972 (a rich technical story) crashes the pipeline with:
`"method references cannot be ambiguous execution groups"`

This is a data validation issue in the snapshot's Java code graph — a method reference was stored with an invalid ambiguous-call-group state. It blocks the full pipeline for stories where auto-subject-selection hits that specific graph path.

**Options**:
- A) Add defensive handling in `code_intelligence/models.py` to skip malformed edges instead of crashing
- B) Re-scan SyGMa to produce a clean snapshot (`atlas analyze /home/meskeda/git/sygma/sygma`)
- C) Both (defensive code + rescan)

**Recommendation**: Option A first (quick, unblocks testing), then B when convenient.

## Priority 2: Bracket-label module targeting

**Problem**: Story titles like `[RISK]`, `[REPA]`, `[Payment]`, `[UI]` contain module hints that Atlas currently ignores (short uppercase = penalty 80, or common words).

**Solution**: Extract bracketed labels from the story title, map them to Maven module name fragments (e.g., `[RISK]` → `sygma-exercise-risk-*`), and use them as a project-scope preference signal during candidate scoring.

**Expected impact**: For vague stories like SYGMA-61077, this would narrow 21,000 files to ~200 files in the right module.

**Implementation plan**:
1. Add `_extract_module_labels(story)` → returns labels like `RISK`, `REPA`, `Payment`
2. Build a label→project mapping from the snapshot's project list (fuzzy match)
3. Apply a score bonus (+200) when a candidate's project matches the label
4. Add the labels to diagnostic output for traceability

## Priority 3: Batch-test against CSV stories

**Goal**: Run Atlas discovery on 10-15 diverse stories from the CSV and measure:
- How many code identifiers are correctly extracted
- How many semantic searches are relevant vs. wasted
- Which stories still fail (vague, no code terms, new microservices)

**Good test set** (from Session 1 analysis):
- SYGMA-60972 — REST service, rich technical detail
- SYGMA-63225 — CL2 model, JPA entities, multi-phase
- SYGMA-61852 — Bean splitting, integration tests
- SYGMA-63464 — Payment REST, specific class references
- SYGMA-63462 — JAGate accessor, payment module
- SYGMA-64572 — Shared UI component
- SYGMA-64586 — Exercise state transitions (new service)
- SYGMA-64482 — ERL batch composition (ported from SyGMa)

## Priority 4: Attempt a full Atlas→Kiro implementation workflow

**Goal**: Pick one story (ideally one you haven't implemented yet or are about to start), run Atlas, give me the context+graph, and I implement it. This tests the end-to-end value.

**Best candidate**: A story with clear technical requirements, touching existing SyGMa modules, where you can validate my output.

## Stretch goals (if time permits)

- **REST endpoint discovery**: Atlas finds REST services but doesn't expose them as a discovery category. Stories that say "create REST" or "call REST" should find existing REST patterns in the same module.
- **`eGrants` metadata token list expansion**: Build the filter list from the actual Jira CSV headers rather than hardcoding.
- **Rescan SyGMa** after recent commits to get a fresh snapshot.

## Files to reference

- Atlas source: `/home/meskeda/Documents/myAI/Atlas-main/`
- SyGMa repo: `/home/meskeda/git/sygma/sygma/`
- Story outputs: `/home/meskeda/Documents/AtlasContexts/`
- Jira export: `/home/meskeda/Downloads/ALM RTD Jira 2026-08-20T23_14_53+0200.csv`
- Changed file: `moughorai/agent_context/discovery.py`
