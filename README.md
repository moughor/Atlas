# Atlas

Atlas is a modular static-analysis platform for multi-project workspaces.
Atlas 2.0 provides deterministic analysis reports, incremental, concurrent,
adaptive, and distributed execution, crash recovery, baselines, Git-diff
analysis, watch mode, quality gates, plugin and rule SDKs, SARIF output, CI
templates, historical reporting, profiling, dashboards, and opt-in governance.

## Install

```text
python -m pip install moughorai
atlas --version
atlas analyze .
atlas check . --adaptive --workers 4
atlas dashboard .
```

Atlas requires Python 3.12 or newer. Workspace configuration is read from
`atlas.yaml`; detailed feature documentation is available in `docs/`.

## Development

```text
python -m pip install -e ".[dev]"
python -m pytest
```

Atlas is distributed under the MIT License.
