"""Retry classification helpers."""

from __future__ import annotations


RETRYABLE_ERROR_KEYWORDS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "TimeoutError",
    "timeout",
    "timed out",
    "ConnectionError",
    "RemoteDisconnected",
    "Temporary failure",
)

NON_RETRYABLE_ERROR_KEYWORDS = (
    "400",
    "401",
    "403",
    "model_not_found",
    "permission_error",
    "invalid_request",
    "Missing API key",
)


def is_retryable_error(error_code: str | None, error_message: str | None) -> bool:
    text = f"{error_code or ''} {error_message or ''}"
    if any(keyword in text for keyword in NON_RETRYABLE_ERROR_KEYWORDS):
        return False
    return any(keyword in text for keyword in RETRYABLE_ERROR_KEYWORDS)
