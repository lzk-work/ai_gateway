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

# Some intermediary gateways return client-looking HTTP codes when their own
# model pool or routing capacity is temporarily unavailable.  These must take
# precedence over generic model_not_found classification, otherwise a batch
# records a recoverable routing incident as a permanent input/model error.
INTERMEDIARY_RETRYABLE_ERROR_KEYWORDS = (
    "HTTP 429:",
    "not supported by any configured account in this group",
    "service_capacity_unavailable",
    "service_error",
    "upstream_rate_limit",
    "上游负载已饱和",
    "服务暂时不可用",
    "资源不足",
    "稍后重试",
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


def gateway_max_attempts(gateway) -> int:
    """Single contract: max_retries is additional retries, excluding the first call."""
    retries = gateway.max_retries
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 0:
        raise ValueError(f"{gateway.name}.max_retries must be a non-negative integer")
    return retries + 1


def is_retryable_error(error_code: str | None, error_message: str | None) -> bool:
    text = f"{error_code or ''} {error_message or ''}"
    if any(keyword in text for keyword in INTERMEDIARY_RETRYABLE_ERROR_KEYWORDS):
        return True
    if any(keyword in text for keyword in NON_RETRYABLE_ERROR_KEYWORDS):
        return False
    return any(keyword in text for keyword in RETRYABLE_ERROR_KEYWORDS)
