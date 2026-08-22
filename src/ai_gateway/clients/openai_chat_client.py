"""OpenAI-compatible Chat Completions client."""

from __future__ import annotations

import time
from typing import Any

import requests

from ai_gateway.config.loader import GatewayConfig


class OpenAIChatClient:
    """Small client for OpenAI-compatible `/v1/chat/completions` endpoints."""

    def __init__(self, gateway: GatewayConfig) -> None:
        self.gateway = gateway

    def auth_headers(self) -> dict[str, str]:
        header_name = self.gateway.auth_header or "Authorization"
        api_key = self.gateway.api_key()
        if header_name.lower() == "authorization":
            return {header_name: f"Bearer {api_key}"}
        return {header_name: api_key}

    def chat_completions(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        url = self.gateway.base_url.rstrip("/") + "/v1/chat/completions"
        headers = {
            **self.auth_headers(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        started = time.perf_counter()
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.gateway.timeout_seconds,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.encoding = "utf-8"
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json(), latency_ms

    def responses_completions(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], int]:
        url = self.gateway.base_url.rstrip("/") + "/v1/responses"
        headers = {
            **self.auth_headers(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        started = time.perf_counter()
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=self.gateway.timeout_seconds,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.encoding = "utf-8"
        _raise_for_status(response)
        return response.json(), latency_ms


def extract_chat_text(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return ""


class UnsupportedUpstreamError(RuntimeError):
    """Raised when chat/completions rejects an OpenAI/Codex model and the
    caller should retry against the /v1/responses endpoint instead."""


def is_unsupported_upstream_error(message: str) -> bool:
    return "unsupported_upstream" in message or "/v1/responses" in message


def _raise_for_status(response: "requests.Response") -> None:
    if response.status_code >= 400:
        body = response.text[:1000]
        if is_unsupported_upstream_error(body):
            raise UnsupportedUpstreamError(f"HTTP {response.status_code}: {body}")
        raise RuntimeError(f"HTTP {response.status_code}: {body}")


def build_responses_payload(chat_payload: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI chat/completions payload into a Responses API payload.

    chat/completions (Gemini/Claude upstreams) -> /v1/chat/completions
    OpenAI/Codex upstreams are rejected there and must use /v1/responses, whose
    schema differs: messages/input_text/image_url become input/input_text/input_image,
    and max_tokens becomes max_output_tokens.
    """
    model = chat_payload.get("model")
    messages = chat_payload.get("messages") or []
    instructions: str | None = None
    input_items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            instructions = content if isinstance(content, str) else _text_of(content)
            continue
        input_items.append({"role": role, "content": _convert_parts(content)})

    resp: dict[str, Any] = {"model": model, "input": input_items}
    if instructions:
        resp["instructions"] = instructions
    if chat_payload.get("temperature") is not None:
        resp["temperature"] = chat_payload["temperature"]
    max_tokens = chat_payload.get("max_tokens")
    if max_tokens:
        resp["max_output_tokens"] = max_tokens
    return resp


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [str(block.get("text", "")) for block in content if isinstance(block, dict)]
        return "\n".join(p for p in parts if p)
    return ""


def _convert_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    parts: list[dict[str, Any]] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append({"type": "input_text", "text": block.get("text", "")})
        elif block_type == "image_url":
            image_url = (block.get("image_url") or {}).get("url")
            if not image_url:
                continue
            image: dict[str, Any] = {"type": "input_image", "image_url": image_url}
            detail = (block.get("image_url") or {}).get("detail")
            if detail:
                image["detail"] = detail
            parts.append(image)
    return parts


def extract_responses_text(response_payload: dict[str, Any]) -> str:
    """Pull final-answer text out of a Responses API payload.

    Deliberately skips `reasoning` items so a model's thinking trace never
    pollutes the JSON we hand to the validator.
    """
    texts: list[str] = []
    for item in response_payload.get("output", []) or []:
        item_type = item.get("type")
        if item_type == "reasoning":
            continue
        if item_type == "message":
            for block in item.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "output_text":
                    text = block.get("text")
                    if text:
                        texts.append(text)
    if not texts and response_payload.get("output_text"):
        texts.append(response_payload["output_text"])
    return "\n".join(texts)
