# PR81 Test Report

Baseline: PR80 commit `491c400`

Focused PR65 and PR81 LSP suite:

```text
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py -p no:cacheprovider --basetemp=.pytest_pr81_focused -q
```

Result: **40 passed in 0.13s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr81_full -q
```

Result: **3,063 passed in 4.31s**.

Clean replay:

```text
git apply --check PR81.patch
git apply PR81.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr81_replay -q
```

Result: patch validation and application succeeded against `491c400`;
**3,063 passed in 5.73s**.
