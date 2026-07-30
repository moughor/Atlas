# PR123 Verification

From a clean checkout of `a36a03f`:

```powershell
git apply --check PR123.patch
git apply PR123.patch
python -m pytest -q
atlas analyze C:\path\to\junit-team --no-recover
```

Verify that analysis succeeds and that the snapshot contains both:

```text
jupiter-tests:DefaultPackageTestCase
platform-tests:DefaultPackageTestCase
```

Their `qualified_name` remains `DefaultPackageTestCase`; `project_id` and `id`
distinguish the two definitions.
