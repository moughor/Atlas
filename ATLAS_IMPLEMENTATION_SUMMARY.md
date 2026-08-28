# Atlas 2.1 Correction Batch 2 — Implementation Summary

**Date:** 2026-08-28
**Atlas base:** `a3c5952e3ba55e81edde0c38d526cb3f352a0b6d` on `main`
**Atlas changes committed:** NO — uncommitted working-tree modifications
**Sygma inspected:** `aeb04bfd43711bd80a8db221910e45a09e1d74c4` on `develop/23.12`
**Sygma patch:** `SYGMA_ada0285_to_aeb04bf.patch` (51 commits, generated with `git format-patch`, apply with `git am`)

## Test Results

| Suite | Passed | Failed | Duration |
|---|---|---|---|
| Focused (P0 + evaluation pack) | 204 | 0 | 58s |
| Evaluation pack only | 62 | 0 | 34s |
| Full regression | 5,203 | 0 | 196s |

## Capability Status

| Capability | Advertised | Status | Notes |
|---|---|---|---|
| exact_git_revision | true | **Implemented** | Snapshot provenance SHA checked; envelope reports 'unverified' without --expected-revision |
| story_trust_boundary | true | **Implemented** | Untrusted markers, policy-first rendering, 10 adversarial tests |
| database_graph | true | **Implemented** | `atlas database build`, `atlas database context`, wired into agent context |
| sql_validation | true | **Implemented** | `atlas database validate-sql`, FK column-pair validation, backup/MV rejection |
| structured_progress | true | **Implemented** | RequestContext with JSONL progress, deadline, cancellation |
| request_cancellation | true | **Implemented** | Generation-scoped temps, previous artifacts preserved |
| local_service | **false** | **Deferred** | WarmRuntimeSession exists but no IPC transport; honestly unavailable |

## Corrections Applied (from Acceptance Review P0 Findings)

### P0-1: Capability truthfulness
- Set `database_graph`, `sql_validation`, `local_service` to false initially
- Re-enabled `database_graph` and `sql_validation` after wiring CLI commands
- `local_service` remains false — no real transport exists

### P0-2: Revision provenance binding
- Envelope reports `unverified` without `--expected-revision` (was falsely `exact`)
- `--require-exact-revision` without `--expected-revision` verifies snapshot SHA against live HEAD
- `--expected-revision` checks both live HEAD and snapshot's `history_reference` SHA
- Added `snapshot_provenance_sha` to repository_identity

### P0-3: FK edge metadata
- Added `source_table`, `source_column`, `target_table`, `target_column` to FOREIGN_KEY_TO edges
- Parse join conditions like `A.GROUP_PF_ID=B.ID` to extract column pairs
- Added `get_property()` method to DatabaseGraphEdge

### P0-4: Join validation with column pairs
- Parses ON clause column pairs with alias resolution
- Checks (source_table, source_col, target_table, target_col) against FK evidence
- `invalid_join_columns` when tables related but columns don't match
- `unsupported_join` only when no relationship exists at all

### P0-5: Context selection relevance
- Weighted scoring: exact=100, entity=90, maps_to=85, FK_neighbor=70, domain=50, fuzzy=20
- Pinning: exact matches + essential neighborhood (columns, FK edges) survive any cap
- Graph-aware stop words: never filter terms that match actual graph identifiers
- 5-tier ranking; cap applied only to non-pinned tiers

### P0-6: Coverage honesty
- `incomplete_evidence` = true when: unresolved JPA constants, FK edges unconsumed, migrations not scanned, synonyms not scanned, or missing major sources
- Added `incomplete_reasons` list for transparent reporting
- Added `foreign_keys_resolved/unresolved`, `migrations_scanned`, `views_scanned`, `synonyms_scanned` to DatabaseGraphCoverage

### P0-7: SQL validation semantics
- Backup/historical objects = `structurally_invalid` (was warning)
- Materialized view mutations = `structurally_invalid` (was missed)
- Schema-qualified names resolved via fallback to short name
- FK index stores column pairs, not just table pairs
- Alias-qualified column validation

### P0-8: Deadline/cancellation propagation
- `cancellation_check` callback threaded into `AgentContextService.export()`
- Three cancellation checkpoints inside export (before generate, after generate, before write)
- Generation-scoped temp directory; atomic rename on success
- Previous valid artifacts never deleted on cancellation

### P0-9: Output limits (partial)
- Code-context artifacts bounded (4 MiB MD/MMD, 16 MiB JSON)
- Database graph outputs not yet bounded (52 MB full graph is legitimate but exceeds handshake limit)
- Public JSON Schemas not yet provided

## Public CLI Commands

### New Commands
```text
atlas database build <repository> --output <dir> [--json]
atlas database context <repository> --story-file <file> --graph <file> --output <dir> [--json]
atlas database validate-sql <repository> --sql-file <file> --graph <file> [--json]
```

### Modified Commands
```text
atlas agent context <repository> --story-file <file> --output <dir>
  [--include-database]       # NEW: include database context artifacts
  [--expected-revision <sha>]
  [--require-exact-revision]
  [--deadline-seconds <float>]
  [--request-id <string>]
  [--json]
```

## Known Limitations

1. **Migration parsing** — Not implemented. 1,286 Flyway SQL files are not parsed for CREATE/ALTER/DROP lineage. Coverage honestly reports `migrations_scanned: false` and `incomplete_evidence: true`.

2. **View/MV SQL parsing** — Views classified from Jailer data and name patterns; view SQL bodies not parsed for dependency edges.

3. **Synonym resolution** — Dynamic synonym targets not resolved. Coverage reports `synonyms_scanned: false`.

4. **PL/SQL body parsing** — Package/procedure/function bodies not parsed for dependency edges.

5. **Mapped superclass inheritance** — JPA extractor resolves constants within a single file but does not walk multi-file type hierarchies.

6. **SQL grammar coverage** — Regex-based parser handles common Oracle DML. Subqueries, PL/SQL blocks, DDL, analytic functions, CONNECT BY are reported as `unsupported_sql`.

7. **Database graph size** — Full graph is ~52 MB JSON; exceeds the advertised `graph_bytes: 16777216` limit in capabilities. Bounded context selection produces appropriately sized artifacts.

8. **Local service** — `WarmRuntimeSession` exists as an in-process cache but no IPC transport. Honestly advertised as `local_service: false`.

9. **Public JSON Schemas** — Not yet published for capabilities, envelopes, database graphs, or validation results. `from_dict()` validators exist in code.

10. **Atlas changes uncommitted** — All implementation is in working-tree modifications against base `a3c5952`. A reviewable patch or committed branch is needed before merge.

## Delivery Artifacts

| File | SHA-256 |
|---|---|
| Atlas_2.1_corrected_candidate.zip | `abfa6c7a1155d89d481670de3eaa9e739662e3de8c2c0bfe23736a738eb8aa7c` |
| SYGMA_ada0285_to_aeb04bf.patch | `a112fd7b00c7763bfece22c2670ff1c212f0a6c25c2e93050bd2836d87f8046a` |
