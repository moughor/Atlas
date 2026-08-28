# Recovery Provenance

## Clean base
- SHA: a3c5952e3ba55e81edde0c38d526cb3f352a0b6d
- Branch: recovery/atlas-2.1-abfa6c7a (fresh from clean base)

## Recovery source
- File: Atlas_2.1_corrected_candidate.zip
- Size: 2,687,520 bytes
- SHA-256: abfa6c7a1155d89d481670de3eaa9e739662e3de8c2c0bfe23736a738eb8aa7c
- Extraction dir: /home/meskeda/Documents/myAI/atlas-zip-extract-216403

## Extraction safety
- Traversal paths: none
- Symlinks: none
- .git dirs: none
- Virtual envs: none
- Cache dirs: none
- Compiled Python: none

## Known omissions
- RECOVERY_PROVENANCE.md and CHECKPOINT_MANIFEST.json are new (not from ZIP)
- tests/test_batch2ba_view_ingest.py is NOT in this ZIP (it was from the CTE
  fix session, committed separately to run3-handoff at cc5f057)
- The CTE/WITH word-boundary fix in view_sql_ingest.py is NOT in this ZIP
  (it will be reapplied as a separate commit)
- Generated outputs (database-graph.json, sql-validation-*.json, etc.) were
  NOT imported from the ZIP

## Restored file inventory
See: git diff --stat HEAD (in the commit message)
