"""Retry classification helpers."""

from __future__ import annotations

import re


RETRYABLE_ERROR_KEYWORDS = (
    "timeout",
    "timed out",
    "connectionerror",
    "remotedisconnected",
    "temporary failure",
)

# Some intermediary gateways return client-looking HTTP codes when their own
# model pool or routing capacity is temporarily unavailable.  These must take
# precedence over generic model_not_found classification, otherwise a batch
# records a recoverable routing incident as a permanent input/model error.
INTERMEDIARY_RETRYABLE_ERROR_KEYWORDS = (
    "not supported by any configured account in this group",
    "is not available",
    "service_capacity_unavailable",
    "service_unavailable",
    "service_error",
    "upstream_rate_limit",
    "temporarily unavailable",
    "please try again later",
    "account_queue_timeout",
    "upstream rate limit reached",
    "retry later",
    "上游负载已饱和",
    "服务暂时不可用",
    "资源不足",
    "稍后重试",
)

NON_RETRYABLE_ERROR_KEYWORDS = (
    "model_not_found",
    "permission_error",
    "invalid_request",
    "missing api key",
)

HTTP_STATUS_PATTERN = re.compile(
    r"\b(?:http\s+|status_code\s*=\s*)([1-5]\d{2})\b",
    re.IGNORECASE,
)


def gateway_max_attempts(gateway) -> int:
    """Single contract: max_retries is additional retries, excluding the first call."""
    retries = gateway.max_retries
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        raise ValueError(f"{gateway.name}.max_retries must be a non-negative integer")
    return retries + 1


def is_retryable_error(error_code: str | None, error_message: str | None) -> bool:
    text = f"{error_code or ''} {error_message or ''}".casefold()
    if any(keyword in text for keyword in INTERMEDIARY_RETRYABLE_ERROR_KEYWORDS):
        return True

    # Parse only explicit status-code locations. Searching the entire response
    # for strings such as "400" or "403" also matches opaque request IDs and
    # can turn a retryable 5xx response into a permanent failure.
    status_match = HTTP_STATUS_PATTERN.search(text)
    status = int(status_match.group(1)) if status_match else None
    if status is None:
        code_text = str(error_code or "").strip()
        if code_text.isdigit() and len(code_text) == 3:
            status = int(code_text)
    if status is not None:
        if status in {408, 429} or 500 <= status <= 599:
            return True
        if 400 <= status <= 499:
            return False

    if any(keyword in text for keyword in NON_RETRYABLE_ERROR_KEYWORDS):
        return False
    return any(keyword in text for keyword in RETRYABLE_ERROR_KEYWORDS)
