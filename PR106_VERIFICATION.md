# PR106 Verification

1. Check out PR105 commit `59ec42a`.
2. Check and apply `PR106.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr106_replay -q`.
4. Read `docs/PR106_PLUGIN_TRUST_MODEL.md` completely.
5. Confirm it describes opt-in enforcement, in-process execution, signer
   metadata, TOCTOU risk, missing sandbox controls, and deployment guidance.
6. Confirm the PR60 guide links to the PR106 threat model.
