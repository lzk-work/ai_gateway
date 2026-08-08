"""BUZZ adapter skeleton for Anthropic-compatible Messages API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from ai_gateway.adapters.base import GatewayAdapter
from ai_gateway.adapters.registry import register_adapter
from ai_gateway.models import AiResult, AiTask, ImageInput
from ai_gateway.retry_policy import is_retryable_error


class BuzzAdapter(GatewayAdapter):
    messages_endpoint = "/v1/messages"
    anthropic_version = "2023-06-01"

    def build_request(self, task: AiTask) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for image in task.images:
            content.append(self._build_image_block(image))
        content.append({"type": "text", "text": task.prompt})

        payload: dict[str, Any] = {
            "model": task.model,
            "max_tokens": task.max_tokens or 1024,
            "messages": [{"role": "user", "content": content if task.images else task.prompt}],
        }
        if task.temperature is not None:
            payload["temperature"] = task.temperature
        return payload

    def send(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + self.messages_endpoint
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
        }
        api_key = self.config.api_key()
        if self.config.auth_header.lower() == "authorization":
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            headers[self.config.auth_header] = api_key

        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"BUZZ HTTP {exc.code}: {error_body[:500]}") from exc

    def parse_response(self, task: AiTask, response_payload: dict[str, Any]) -> AiResult:
        text_parts: list[str] = []
        for block in response_payload.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        return AiResult(
            task_id=task.task_id,
            status="success",
            batch_id=task.batch_id,
            text="\n".join(part for part in text_parts if part),
            gateway=self.name,
            model=task.model,
            request_id=response_payload.get("id"),
            attempt=task.attempt,
            retry_count=max(task.attempt - 1, 0),
            retryable=False,
            raw_response=response_payload,
            metadata=task.metadata,
        )

    def call(self, task: AiTask) -> AiResult:
        started = time.perf_counter()
        try:
            result = super().call(task)
            result.latency_ms = int((time.perf_counter() - started) * 1000)
            return result
        except Exception as exc:
            error_code = exc.__class__.__name__
            error_message = str(exc)
            return AiResult(
                task_id=task.task_id,
                status="failed",
                batch_id=task.batch_id,
                gateway=self.name,
                model=task.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                attempt=task.attempt,
                retry_count=max(task.attempt - 1, 0),
                retryable=is_retryable_error(error_code, error_message)
                and task.attempt <= task.max_retries,
                error_code=error_code,
                error_message=error_message,
                metadata=task.metadata,
            )

    @staticmethod
    def _build_image_block(image: ImageInput) -> dict[str, Any]:
        if image.type == "url":
            return {"type": "image", "source": {"type": "url", "url": image.value}}
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": image.media_type or "image/jpeg",
                "data": image.value,
            },
        }


register_adapter("anthropic_compatible", BuzzAdapter)
register_adapter("buzz", BuzzAdapter)
