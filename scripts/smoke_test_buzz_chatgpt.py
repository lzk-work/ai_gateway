"""Smoke test BUZZ OpenAI-compatible Chat Completions.

This script does not read business Excel data. It sends a minimal stateless
request to verify base URL, API key, model name, and response parsing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_gateway.config.loader import load_app_config  # noqa: E402


DEFAULT_IMAGE_URL = "https://www.gstatic.com/webp/gallery/1.jpg"


def main() -> int:
    parser = argparse.ArgumentParser(description="Test BUZZ ChatGPT-compatible API.")
    parser.add_argument("--with-image", action="store_true", help="Also send one image URL.")
    parser.add_argument("--image-url", default=DEFAULT_IMAGE_URL, help="Image URL for vision test.")
    args = parser.parse_args()

    config = load_app_config(
        PROJECT_ROOT / "configs" / "gateways.yaml",
        PROJECT_ROOT / "configs" / "models.yaml",
    )
    model_name = config.default_model
    if not model_name:
        print("ERROR: default_model is missing.")
        return 2

    model_config = config.models.get(model_name, {})
    gateway_name = model_config.get("gateway") or config.default_gateway
    gateway = config.gateways[gateway_name]

    payload = build_payload(
        model_name=model_name,
        with_image=args.with_image,
        image_url=args.image_url,
        max_tokens=min(int(model_config.get("max_tokens_default", 256)), 128),
    )
    url = gateway.base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {gateway.api_key()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
    }

    print(f"gateway={gateway_name}")
    print(f"model={model_name}")
    print(f"endpoint={url}")
    print(f"with_image={args.with_image}")

    try:
        response_payload = post_json(url, headers, payload, timeout_seconds=gateway.timeout_seconds)
    except Exception as exc:
        print(f"ERROR: {exc.__class__.__name__}: {exc}")
        return 1

    text = extract_text(response_payload)
    request_id = response_payload.get("id")
    print(f"request_id={request_id}")
    print(f"response_text={text[:500]}")
    return 0


def build_payload(
    model_name: str,
    with_image: bool,
    image_url: str,
    max_tokens: int,
) -> dict[str, Any]:
    if with_image:
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "请用中文回答：这张图片里主要是什么？只回答一句话。",
            },
            {
                "type": "image_url",
                "image_url": {"url": image_url, "detail": "low"},
            },
        ]
    else:
        content = [
            {
                "type": "text",
                "text": "请用中文回答：接口测试成功。只返回这句话，不要解释。",
            }
        ]
    return {
        "model": model_name,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }


def post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    response = requests.post(
        url,
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


def extract_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
