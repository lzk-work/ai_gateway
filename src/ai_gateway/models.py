"""Shared data models used across gateway adapters and batch jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

ImageKind = Literal["url", "base64"]
TaskStatus = Literal["pending", "success", "failed"]
RunMode = Literal["batch", "retry"]


@dataclass(slots=True)
class ImageInput:
    """A normalized image input for multimodal calls."""

    type: ImageKind
    value: str
    media_type: str | None = None


@dataclass(slots=True)
class AiTask:
    """Provider-neutral AI call task."""

    task_id: str
    prompt: str
    batch_id: str | None = None
    gateway: str | None = None
    model: str | None = None
    images: list[ImageInput] = field(default_factory=list)
    max_tokens: int | None = None
    temperature: float | None = None
    attempt: int = 1
    max_retries: int = 3
    response_template: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def input_type(self) -> str:
        return "image_text" if self.images else "text"


@dataclass(slots=True)
class AiResult:
    """Provider-neutral AI call result."""

    task_id: str
    status: TaskStatus
    batch_id: str | None = None
    text: str = ""
    gateway: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    request_id: str | None = None
    attempt: int = 1
    retry_count: int = 0
    retryable: bool = False
    validation_status: Literal["not_checked", "passed", "failed"] = "not_checked"
    validation_errors: list[str] = field(default_factory=list)
    parsed_json: dict[str, Any] | list[Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BatchSummary:
    """Summary for one batch run or retry run."""

    batch_id: str
    mode: RunMode
    total_count: int
    success_count: int
    failed_count: int
    retryable_failed_count: int
    started_at: datetime
    finished_at: datetime

    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count
