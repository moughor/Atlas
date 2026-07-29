# PR105 Verification

1. Check out PR104 commit `ab0929a`.
2. Check and apply `PR105.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr105_replay -q`.
4. Import supported objects from `moughorai.public_api`.
5. Confirm `public_api_compatibility_issues()` returns an empty tuple.
6. Confirm legacy imports resolve to the same object identities.
