# PR111 Verification

1. Apply `PR111.patch` to commit `afa8a8e`.
2. Run `python -m pytest -q --basetemp=.pytest_pr111_verify`.
3. Confirm snapshot determinism, integrity, immutability, context restoration,
   and the complete suite pass.
