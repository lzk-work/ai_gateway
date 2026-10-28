from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class InputRecord:
    record_key: str
    source_row: int
    fields: dict[str, Any]
    rendered_prompt: str
    input_hash: str
    action: str = "auto"
    image_urls: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CallResult:
    record_key: str
    source_row: int
    input_hash: str
    status: str
    raw_text: str = ""
    parsed: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    request_id: str | None = None
    latency_ms: int | None = None
    attempts: int = 0
    error_category: str | None = None
    error_message: str | None = None
    updated_at: str = ""


@dataclass(slots=True)
class BatchPaths:
    root: Path
    state: Path
    manifest: Path
    snapshots: Path
    result: Path
    failed: Path
    results_jsonl: Path
    raw_outputs: Path
