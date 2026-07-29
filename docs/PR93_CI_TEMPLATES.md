# PR93 — CI Templates

Atlas can install a deterministic CI configuration for GitHub Actions, GitLab
CI, or Azure Pipelines:

```text
atlas ci github
atlas ci gitlab
atlas ci azure
```

The canonical destinations are `.github/workflows/atlas.yml`,
`.gitlab-ci.yml`, and `azure-pipelines.yml`. Use `--output` to choose another
path, `--python-version` to select the runtime, and `--force` to replace an
existing file.

Generated jobs install the current project, run `atlas check` with SARIF
output, and retain or upload that report. Files are written atomically with
stable UTF-8 and LF encoding. Existing files are never replaced unless
`--force` is supplied.
