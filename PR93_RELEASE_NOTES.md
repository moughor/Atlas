# PR93 Release Notes

PR93 adds deterministic CI templates for GitHub Actions, GitLab CI, and Azure
Pipelines. The new `atlas ci` command writes the provider's canonical file,
supports a selected Python version and alternate output path, and refuses to
replace existing configuration unless `--force` is supplied.

Generated jobs install Atlas, enforce `atlas check`, and preserve SARIF output.
All existing command-line APIs remain compatible.
