"""Small JSONL logger for batch task traces."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ai_gateway.models import AiResult, BatchSummary


class JsonlLogger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_result(self, result: AiResult) -> None:
        row = asdict(result)
        row.pop("raw_response", None)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_summary(self, summary: BatchSummary) -> None:
        row = asdict(summary)
        row["started_at"] = summary.started_at.isoformat()
        row["finished_at"] = summary.finished_at.isoformat()
        row["success_rate"] = summary.success_rate
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
