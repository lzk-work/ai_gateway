"""Test full one-shot Walmart output with stream=true."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_gateway.config.loader import load_app_config  # noqa: E402
from ai_gateway.subtasks.walmart_get_pic_prompt import (  # noqa: E402
    load_config as load_prompt_config,
)
from ai_gateway.subtasks.walmart_get_pic_prompt import run as run_get_prompt  # noqa: E402
from ai_gateway.validators.result_validator import extract_json  # noqa: E402


@dataclass(slots=True)
class StreamTestResult:
    model: str
    status: str
    json_parseable: bool
    has_product_analysis: bool
    image_plan_count: int
    has_six_image_plan: bool
    result_text_length: int
    chunk_count: int
    error_message: str | None
    result_text_preview: str
    full_output_path: str | None
    debug_events_preview: list[str]
    created_at: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Test full one-shot output with stream=true.")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    app_config = load_app_config(
        PROJECT_ROOT / "configs" / "gateways.yaml",
        PROJECT_ROOT / "configs" / "models.yaml",
    )
    gateway = app_config.gateways[app_config.default_gateway]
    prompt_records = run_get_prompt(
        load_prompt_config(PROJECT_ROOT / "subtasks" / "walmart_image_prompt" / "stages" / "get_pic_prompt" / "config.json")
    )
    if not prompt_records:
        raise RuntimeError("No prompt records generated.")
    source = asdict(prompt_records[0])

    full_output_path = (
        PROJECT_ROOT
        / "data"
        / "model_full_output_tests"
        / "full_outputs"
        / f"{args.model}.json"
    )
    result = test_stream_model(
        base_url=gateway.base_url,
        api_key=gateway.api_key(),
        timeout_seconds=gateway.timeout_seconds,
        model=args.model,
        prompt=source["prompt_text"],
        image_url=source["image_urls"][0],
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        full_output_path=full_output_path,
    )

    output_path = PROJECT_ROOT / "data" / "model_full_output_tests" / "stream_results.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")

    print(f"model={result.model}")
    print(f"status={result.status}")
    print(f"json_parseable={result.json_parseable}")
    print(f"image_plan_count={result.image_plan_count}")
    print(f"chunk_count={result.chunk_count}")
    print(f"result_text_length={result.result_text_length}")
    if result.error_message:
        print(f"error={result.error_message[:500]}")
    print(f"output={output_path}")
    return 0


def test_stream_model(
    base_url: str,
    api_key: str,
    timeout_seconds: int,
    model: str,
    prompt: str,
    image_url: str,
    max_tokens: int,
    temperature: float,
    full_output_path: Path,
) -> StreamTestResult:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }
    url = base_url.rstrip("/") + "/v1/chat/completions"
    text_parts: list[str] = []
    debug_events: list[str] = []
    chunk_count = 0

    try:
        with requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "Mozilla/5.0",
            },
            json=payload,
            stream=True,
            timeout=timeout_seconds,
        ) as response:
            if response.status_code >= 400:
                return build_error(
                    model,
                    response.text[:1000],
                    chunk_count,
                    text_parts,
                    full_output_path=None,
                    debug_events=debug_events,
                )
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                chunk_count += 1
                if len(debug_events) < 5:
                    debug_events.append(data[:500])
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                text = extract_stream_delta(event)
                if text:
                    text_parts.append(text)
    except Exception as exc:
        return build_error(
            model,
            str(exc),
            chunk_count,
            text_parts,
            full_output_path=None,
            debug_events=debug_events,
        )

    full_text = "".join(text_parts)
    saved_output_path: str | None = None
    if full_text:
        full_output_path.parent.mkdir(parents=True, exist_ok=True)
        full_output_path.write_text(full_text, encoding="utf-8")
        saved_output_path = str(full_output_path)
    parsed, parse_error = extract_json(full_text)
    image_plan = parsed.get("image_plan") if isinstance(parsed, dict) else None
    image_plan_count = len(image_plan) if isinstance(image_plan, list) else 0
    has_product_analysis = isinstance(parsed, dict) and isinstance(parsed.get("product_analysis"), dict)
    success = parse_error is None and has_product_analysis and image_plan_count == 6
    return StreamTestResult(
        model=model,
        status="success" if success else "validation_failed",
        json_parseable=parse_error is None,
        has_product_analysis=has_product_analysis,
        image_plan_count=image_plan_count,
        has_six_image_plan=image_plan_count == 6,
        result_text_length=len(full_text),
        chunk_count=chunk_count,
        error_message=parse_error,
        result_text_preview=full_text[:1000],
        full_output_path=saved_output_path,
        debug_events_preview=debug_events,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


def extract_stream_delta(event: dict[str, Any]) -> str:
    choices = event.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def build_error(
    model: str,
    error_message: str,
    chunk_count: int,
    text_parts: list[str],
    full_output_path: str | None,
    debug_events: list[str] | None = None,
) -> StreamTestResult:
    full_text = "".join(text_parts)
    return StreamTestResult(
        model=model,
        status="failed",
        json_parseable=False,
        has_product_analysis=False,
        image_plan_count=0,
        has_six_image_plan=False,
        result_text_length=len(full_text),
        chunk_count=chunk_count,
        error_message=error_message,
        result_text_preview=full_text[:1000],
        full_output_path=full_output_path,
        debug_events_preview=debug_events or [],
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


if __name__ == "__main__":
    raise SystemExit(main())

