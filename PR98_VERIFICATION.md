# PR98 Verification

1. Check out PR97 commit `6fd406f`.
2. Check and apply `PR98.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr98_replay -q`.
4. Expect 3266 passing tests.
5. Construct `DistributedWorkspaceCoordinator`, submit a dependent project,
   and execute with a capability-matched in-process worker.
6. Verify dependency results and deterministic assignments in the returned
   `DistributedWorkspaceRun`.
