# PR100 — Atlas 2.0 Stabilization

Atlas 2.0 consolidates the workspace, editor, rule-authoring, CI, historical,
enterprise, and distributed capabilities delivered through PR99. The package
metadata, `moughorai.__version__`, `atlas --version`, and SARIF tool identity
all report `2.0.0`.

## Compatibility

- Existing `moughorai` and `atlas` entry points remain available.
- Existing analyze/check defaults and deterministic text reports are unchanged.
- Persistent state, recovery, baseline, history, and audit schemas retain
  their existing versions.
- Plugin and rule-pack API versions remain 1.x; the product major release does
  not force third-party extension migration.
- Adaptive scheduling, distributed workers, profiling, history, dashboards,
  CI templates, and governance remain opt-in or additive.

## Release verification

The final release gate includes every repository test, wheel construction and
inspection, CLI smoke coverage, deterministic structured-output checks, and a
full clean patch replay from PR99.
