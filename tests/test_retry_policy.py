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


def test_intermediary_capacity_errors_are_retryable():
    messages = (
        'HTTP 402: {"code":"service_capacity_unavailable"}',
        'HTTP 404: {"type":"service_error","message":"服务暂时不可用，请稍后重试"}',
        'HTTP 503: {"message":"资源不足,稍后再试"}',
    )
    assert all(is_retryable_error("RuntimeError", message) for message in messages)


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
