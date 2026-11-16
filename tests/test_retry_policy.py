from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_gateway.retry_policy import is_retryable_error


def test_intermediary_model_pool_404_is_retryable():
    message = (
        'HTTP 404: {"error":{"message":"Model gpt-6-luna is not supported '
        'by any configured account in this group","type":"model_not_found"}}'
    )
    assert is_retryable_error("RuntimeError", message)


def test_intermediary_model_pool_400_is_retryable():
    message = (
        'HTTP 400: {"error":{"message":"Model \"gpt-6-luna\" is not supported '
        'by any configured account in this group","type":"invalid_request_error"}}'
    )
    assert is_retryable_error("RuntimeError", message)


def test_intermediary_capacity_errors_are_retryable():
    messages = (
        'HTTP 402: {"code":"service_capacity_unavailable"}',
        'HTTP 404: {"type":"service_error","message":"服务暂时不可用，请稍后重试"}',
        'HTTP 503: {"message":"资源不足,稍后再试"}',
    )
    assert all(is_retryable_error("RuntimeError", message) for message in messages)


def test_model_temporarily_not_available_is_retryable_despite_http_400():
    message = (
        'HTTP 400: {"error":{"message":"Model gpt-6-luna is not available '
        '(request id: 202611160233076684226288268d9d6mpmwd9aH)",'
        '"type":"invalid_request_error"}}'
    )
    assert is_retryable_error("RuntimeError", message)


def test_503_is_retryable_when_request_id_contains_403():
    message = (
        'HTTP 503: {"error":{"message":"The service is temporarily unavailable. '
        'Please try again later. (request id: 202611160234013335534038268d9d6lmn3rZXD)",'
        '"type":"server_error","code":"service_unavailable"}}'
    )
    assert is_retryable_error("RuntimeError", message)


def test_status_code_gateway_errors_are_classified_from_the_status_field():
    retryable = (
        'status_code=503, 资源不足,稍后再试',
        'status_code=429, OpenAI OAuth admission: account_queue_timeout',
        'status_code=429, Upstream rate limit reached; retry later',
    )
    assert all(is_retryable_error("RuntimeError", message) for message in retryable)


def test_upstream_429_stays_retryable_when_request_id_contains_400():
    message = (
        'HTTP 429: {"message":"当前分组上游负载已饱和，请稍后再试 '
        '(request id: 00400abc)","code":"upstream_rate_limit"}'
    )
    assert is_retryable_error("RuntimeError", message)


def test_real_invalid_model_remains_non_retryable():
    message = 'HTTP 404: {"type":"model_not_found","message":"unknown model name"}'
    assert not is_retryable_error("RuntimeError", message)


def test_auth_and_invalid_request_remain_non_retryable():
    assert not is_retryable_error("RuntimeError", "HTTP 401 permission_error")
    assert not is_retryable_error("RuntimeError", "HTTP 400 invalid_request")


def test_request_id_digits_do_not_override_explicit_http_status():
    assert not is_retryable_error(
        "RuntimeError",
        "HTTP 400: invalid_request (request id: 503429400403)",
    )
    assert is_retryable_error(
        "RuntimeError",
        "HTTP 503: upstream failure (request id: 400401403)",
    )
