# PR79 Quality Gates

`atlas check` can fail on findings at or above a selected severity:

```text
atlas check . --fail-on high --finding-exit-code 7
```

It also supports `--max-findings` and a separate `--analysis-exit-code`.
Codes must be between 1 and 255.

PR71 workspace options use these keys:

```yaml
options:
  quality_gate.minimum_severity: high
  quality_gate.max_findings: "0"
  quality_gate.finding_exit_code: "7"
  quality_gate.analysis_exit_code: "9"
```

CLI values override workspace values. PR77 baseline filtering occurs before
gate evaluation, so ignored existing findings do not fail the gate. With no
configured threshold or maximum, successful analysis retains the historical
zero exit code; analysis failures retain exit code 1 by default.
