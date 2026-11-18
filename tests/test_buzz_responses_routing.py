import unittest
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_gateway.clients.openai_chat_client import (
    OpenAIChatClient,
    ReferenceImageNotFoundError,
    _decode_json_response,
    _raise_for_status,
)
from ai_gateway.subtasks.walmart_call_prompt_model import _call_model, read_jsonl


class FakeResponse:
    def __init__(self, lines, status_code=200, text=""):
        self.lines = lines
        self.status_code = status_code
        self.text = text
        self.encoding = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_lines(self, decode_unicode=False):
        return iter(self.lines)


class BuzzResponsesRoutingTests(unittest.TestCase):
    def test_jsonl_reader_ignores_nul_only_interrupted_tail(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            path = Path(temp_dir) / "results.jsonl"
            path.write_bytes(b'{"status":"success"}\n' + b"\x00" * 64)

            self.assertEqual(read_jsonl(path), [{"status": "success"}])

    def test_jsonl_reader_reports_file_and_line_for_real_corruption(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            path = Path(temp_dir) / "results.jsonl"
            path.write_text('{"status":"success"}\nnot-json\n', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, r"results\.jsonl.*第 2 行"):
                read_jsonl(path)

    def test_successful_empty_body_reports_provider_and_endpoint(self):
        response = Mock(status_code=200, text="", headers={"Content-Type": "application/json"})

        with self.assertRaisesRegex(
            RuntimeError,
            r"BUZZ /v1/chat/completions returned an empty response body",
        ):
            _decode_json_response(response, "buzz", "/v1/chat/completions")

    def test_successful_html_body_reports_non_json_instead_of_jsondecodeerror(self):
        response = Mock(
            status_code=200,
            text="<html><title>gateway timeout</title></html>",
            headers={"Content-Type": "text/html"},
        )
        response.json.side_effect = ValueError("not json")

        with self.assertRaisesRegex(
            RuntimeError,
            r"BUZZ /v1/chat/completions returned non-JSON content",
        ):
            _decode_json_response(response, "buzz", "/v1/chat/completions")

    def test_wrapped_http_500_image_404_is_permanent_reference_error(self):
        response = SimpleNamespace(
            status_code=500,
            text='{"error":{"message":"error getting file type: failed to download file, status code: 404"}}',
        )

        with self.assertRaisesRegex(ReferenceImageNotFoundError, "参考图片失效"):
            _raise_for_status(response)

    def test_explicit_responses_mode_uses_responses_directly(self):
        client = Mock()
        client.responses_completions.return_value = (
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "result"}]}]},
            123,
        )
        config = SimpleNamespace(stream=False, api_mode="responses")

        response, latency_ms, text = _call_model(
            client,
            {"model": "gpt-5.6-luna", "messages": []},
            config,
        )

        client.chat_completions.assert_not_called()
        client.responses_completions.assert_called_once()
        self.assertEqual(latency_ms, 123)
        self.assertEqual(text, "result")
        self.assertIn("output", response)

    def test_streaming_explicit_responses_mode_uses_responses_streaming_directly(self):
        client = Mock()
        client.responses_streaming.return_value = ({"id": "resp_1"}, 456, "streamed")
        config = SimpleNamespace(stream=True, api_mode="responses")

        response, latency_ms, text = _call_model(
            client,
            {"model": "gpt-5.6-terra", "messages": []},
            config,
        )

        client.responses_streaming.assert_called_once()
        client.responses_completions.assert_not_called()
        client.chat_completions.assert_not_called()
        self.assertEqual((response["id"], latency_ms, text), ("resp_1", 456, "streamed"))

    def test_explicit_chat_completions_mode_keeps_gpt_on_chat_endpoint(self):
        client = Mock()
        client.chat_completions.return_value = (
            {"choices": [{"message": {"content": "result"}}]},
            321,
        )
        config = SimpleNamespace(stream=False, api_mode="chat_completions")

        response, latency_ms, text = _call_model(
            client,
            {"model": "gpt-6-luna", "messages": []},
            config,
        )

        client.chat_completions.assert_called_once()
        client.responses_completions.assert_not_called()
        self.assertEqual(latency_ms, 321)
        self.assertEqual(text, "result")
        self.assertIn("choices", response)

    def test_explicit_chat_mode_does_not_fallback_to_responses(self):
        client = Mock()
        client.chat_completions.side_effect = RuntimeError(
            "The /v1/chat/completions endpoint only supports Gemini upstreams; use /v1/responses"
        )
        config = SimpleNamespace(stream=False, api_mode="chat_completions")

        with self.assertRaisesRegex(RuntimeError, "use /v1/responses"):
            _call_model(client, {"model": "gpt-6-luna", "messages": []}, config)

        client.responses_completions.assert_not_called()

    def test_responses_sse_parser_collects_text_and_requires_completion(self):
        gateway = SimpleNamespace(
            name="buzz",
            base_url="https://buzz.invalid",
            auth_header="Authorization",
            timeout_seconds=30,
            api_key=lambda: "test-key",
        )
        client = OpenAIChatClient(gateway)
        fake = FakeResponse([
            'event: response.created',
            'data: {"type":"response.created","response":{"id":"resp_1","model":"gpt-5.6-terra","output":[]}}',
            'event: response.output_text.delta',
            "data: " + json.dumps({"type": "response.output_text.delta", "delta": '{"ok":'}),
            'event: response.output_text.delta',
            'data: {"type":"response.output_text.delta","delta":"true}"}',
            'event: response.completed',
            'data: {"type":"response.completed","response":{"id":"resp_1","model":"gpt-5.6-terra","output":[]}}',
        ])

        with patch("ai_gateway.clients.openai_chat_client.requests.post", return_value=fake):
            response, _latency_ms, text = client.responses_streaming({"model": "gpt-5.6-terra"})

        self.assertEqual(response["id"], "resp_1")
        self.assertEqual(text, '{"ok":true}')

    def test_responses_sse_parser_rejects_incomplete_stream(self):
        gateway = SimpleNamespace(
            name="buzz",
            base_url="https://buzz.invalid",
            auth_header="Authorization",
            timeout_seconds=30,
            api_key=lambda: "test-key",
        )
        client = OpenAIChatClient(gateway)
        fake = FakeResponse([
            'event: response.output_text.delta',
            'data: {"type":"response.output_text.delta","delta":"partial"}',
        ])

        with patch("ai_gateway.clients.openai_chat_client.requests.post", return_value=fake):
            with self.assertRaisesRegex(RuntimeError, "before response.completed"):
                client.responses_streaming({"model": "gpt-5.6-terra"})


if __name__ == "__main__":
    unittest.main()
