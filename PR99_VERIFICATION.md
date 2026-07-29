# PR99 Verification

1. Check out PR98 commit `998998e`.
2. Check and apply `PR99.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr99_replay -q`.
4. Expect 3280 passing tests.
5. Append two decisions with `GovernanceAuditLog`, verify the chain, then
   modify one serialized decision and verify that checksum validation fails.
