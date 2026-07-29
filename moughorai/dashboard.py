"""Self-contained historical dashboard generation."""

from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path

from .history import HistoricalRun, HistoryDatabase


class DashboardRenderer:
    """Render historical runs as deterministic, accessible HTML."""

    def render(self, runs: tuple[HistoricalRun, ...]) -> str:
        total = len(runs)
        passed = sum(run.succeeded for run in runs)
        failed = total - passed
        projects = Counter(item.project for run in runs for item in run.runs)
        rows = "\n".join(self._row(run) for run in runs) or (
            '<tr><td colspan="5" class="empty">No analysis history is available.</td></tr>'
        )
        project_items = "\n".join(
            f"<li><span>{escape(name)}</span><strong>{count}</strong></li>"
            for name, count in sorted(projects.items())
        ) or "<li><span>No projects</span><strong>0</strong></li>"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atlas Analysis Dashboard</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; }}
    body {{ margin: 0; background: #0b1020; color: #e8eefc; }}
    main {{ max-width: 1080px; margin: auto; padding: 40px 24px; }}
    h1 {{ margin: 0 0 8px; }} .subtitle {{ color: #9fb0d0; margin-bottom: 28px; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
    .card, .panel {{ background: #141c31; border: 1px solid #263553; border-radius: 12px; padding: 20px; }}
    .metric {{ display: block; font-size: 2rem; font-weight: 700; margin-top: 6px; }}
    .panels {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; margin-top: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }} th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #263553; }}
    th {{ color: #9fb0d0; }} .ok {{ color: #65d69e; }} .bad {{ color: #ff7c8b; }}
    ul {{ list-style: none; padding: 0; }} li {{ display: flex; justify-content: space-between; padding: 8px 0; }}
    .empty {{ text-align: center; color: #9fb0d0; }}
    @media (max-width: 760px) {{ .cards, .panels {{ grid-template-columns: 1fr; }} .table-wrap {{ overflow-x: auto; }} }}
  </style>
</head>
<body>
<main>
  <h1>Atlas Analysis Dashboard</h1>
  <p class="subtitle">Historical workspace analysis overview</p>
  <section class="cards" aria-label="Summary">
    <article class="card">Runs<span class="metric">{total}</span></article>
    <article class="card">Succeeded<span class="metric ok">{passed}</span></article>
    <article class="card">Failed<span class="metric bad">{failed}</span></article>
  </section>
  <section class="panels">
    <article class="panel table-wrap">
      <h2>Recent runs</h2>
      <table><thead><tr><th>ID</th><th>Timestamp</th><th>Status</th><th>Projects</th><th>Findings</th></tr></thead>
      <tbody>
{rows}
      </tbody></table>
    </article>
    <aside class="panel"><h2>Project activity</h2><ul>
{project_items}
    </ul></aside>
  </section>
</main>
</body>
</html>
"""

    def _row(self, run: HistoricalRun) -> str:
        findings = sum(self._finding_count(item.value) for item in run.runs)
        status = "Succeeded" if run.succeeded else "Failed"
        css = "ok" if run.succeeded else "bad"
        return (
            f'<tr><td>{run.run_id}</td><td>{escape(run.created_at)}</td>'
            f'<td class="{css}">{status}</td><td>{len(run.runs)}</td><td>{findings}</td></tr>'
        )

    @staticmethod
    def _finding_count(value: object) -> int:
        if not isinstance(value, dict):
            return 0
        findings = value.get("findings")
        return len(findings) if isinstance(findings, list) else 0


class DashboardService:
    def __init__(self, database: HistoryDatabase, renderer: DashboardRenderer | None = None) -> None:
        self.database = database
        self.renderer = renderer or DashboardRenderer()

    def generate(self, output: Path, *, limit: int = 100) -> Path:
        if limit < 0:
            raise ValueError("dashboard limit must be non-negative")
        target = output.expanduser()
        if not target.is_absolute():
            target = self.database.root / target
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.renderer.render(self.database.list(limit=limit)), encoding="utf-8", newline="\n")
        return target
