"""Result output helpers."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from ai_gateway.models import AiResult


def write_results_csv(results: list[AiResult], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for result in results:
        row = asdict(result)
        row.pop("raw_response", None)
        for key in ("validation_errors", "parsed_json", "metadata"):
            row[key] = json.dumps(row[key], ensure_ascii=False)
        rows.append(row)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
