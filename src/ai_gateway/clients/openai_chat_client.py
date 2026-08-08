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
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
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
