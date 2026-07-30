# PR127 Verification

From a clean checkout of `ce36dbc`:

```powershell
git apply --check PR127.patch
git apply PR127.patch
python -m pytest -q
```

Analyze a repository with nested projects:

```powershell
atlas analyze . --no-recover
```

Inspect `.atlas/ass/latest.ass` and verify
`semantic_context.repository_summary` contains stable project, language, build
system, framework, entry-point, hierarchy, source-role, generated-source, and
dependency data without raw source content or duplicate nested files.
