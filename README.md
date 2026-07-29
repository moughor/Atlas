# Atlas

Atlas is a modular static-analysis platform for multi-project workspaces. Atlas
1.0 provides deterministic analysis reports, incremental and concurrent
execution, recovery, baselines, watch mode, quality gates, plugin discovery,
and text, JSON, JSONL, and SARIF output.

## Install

```text
python -m pip install moughorai
atlas --version
atlas analyze .
```

Atlas requires Python 3.12 or newer. Workspace configuration is read from
`atlas.yaml`; detailed feature documentation is available in `docs/`.

## Development

```text
python -m pip install -e ".[dev]"
python -m pytest
```

Atlas is distributed under the MIT License.
