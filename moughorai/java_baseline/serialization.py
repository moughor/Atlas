"""Stable JSON serialization for architecture baselines."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import ArchitectureBaseline, BaselineEdge, BaselineNode, BaselineViolation


class JavaArchitectureBaselineJson:
    @staticmethod
    def dumps(baseline: ArchitectureBaseline) -> str:
        return json.dumps(asdict(baseline), indent=2, sort_keys=True) + "\n"

    @staticmethod
    def loads(value: str) -> ArchitectureBaseline:
        payload = json.loads(value)
        return ArchitectureBaseline(
            nodes=tuple(BaselineNode(project=item["project"], key=item["key"], kind=item["kind"], facets=tuple(item.get("facets", ()))) for item in payload.get("nodes", ())),
            edges=tuple(BaselineEdge(**item) for item in payload.get("edges", ())),
            unresolved=tuple(payload.get("unresolved", ())),
            violations=tuple(BaselineViolation(**item) for item in payload.get("violations", ())),
        )

    def write(self, path: str | Path, baseline: ArchitectureBaseline) -> None:
        Path(path).write_text(self.dumps(baseline), encoding="utf-8")

    def read(self, path: str | Path) -> ArchitectureBaseline:
        return self.loads(Path(path).read_text(encoding="utf-8"))
