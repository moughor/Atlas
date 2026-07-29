# PR76 Test Report

Baseline: PR75 commit `236d2fd`

Focused PR75–PR76 CLI suite:

```text
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr76_cli_output_formats.py -p no:cacheprovider --basetemp=.pytest_pr76_focused -q
```

Result: **50 passed in 0.40s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr76_full -q
```

Result: **3,011 passed in 4.05s**.

Clean replay:

- Baseline: `236d2fd1396634570913e7ee5fd5f66d1bd0c06d`
- Patch apply check: passed
- Full replayed suite: **3,011 passed in 5.87s**
