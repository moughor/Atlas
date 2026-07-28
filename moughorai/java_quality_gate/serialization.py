"""Stable JSON output for CI systems."""
from __future__ import annotations

import json
from pathlib import Path

from .models import QualityGateReport


class JavaQualityGateJson:
    def dumps(self, report: QualityGateReport) -> str:
        payload = {
            "status": report.status.value,
            "score": report.score,
            "checked_symbols": list(report.checked_symbols),
            "findings": [
                {
                    "severity": item.severity.value,
                    "category": item.category,
                    "message": item.message,
                    "evidence": list(item.evidence),
                    "score": item.score,
                }
                for item in report.findings
            ],
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def write(self, path: str | Path, report: QualityGateReport) -> None:
        Path(path).write_text(self.dumps(report), encoding="utf-8")
