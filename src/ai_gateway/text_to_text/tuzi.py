from __future__ import annotations

from typing import Any

from ai_gateway.clients.openai_chat_client import OpenAIChatClient, extract_chat_text


class TuziTextGateway:
    def __init__(self, gateway_config) -> None:
        self.client = OpenAIChatClient(gateway_config)

    def call(
        self,
        *,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        image_urls: list[str] | None = None,
        image_detail: str = "auto",
    ) -> tuple[str, str | None, int, dict[str, Any]]:
        content: str | list[dict[str, Any]] = prompt
        if image_urls:
            content = [{"type": "text", "text": prompt}]
            content.extend(
                {
                    "type": "image_url",
                    "image_url": {"url": url, "detail": image_detail},
                }
                for url in image_urls
            )
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        response, latency_ms = self.client.chat_completions(payload)
        text = extract_chat_text(response)
        if not text.strip():
            raise RuntimeError("兔子 API 返回成功但没有文本")
        return text, response.get("id"), latency_ms, response
