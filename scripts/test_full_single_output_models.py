"""Test full one-shot Walmart output across candidate models."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_gateway.clients.openai_chat_client import OpenAIChatClient, extract_chat_text  # noqa: E402
from ai_gateway.config.loader import load_app_config  # noqa: E402
from ai_gateway.subtasks.walmart_get_pic_prompt import (  # noqa: E402
    load_config as load_prompt_config,
)
from ai_gateway.subtasks.walmart_get_pic_prompt import run as run_get_prompt  # noqa: E402
from ai_gateway.validators.result_validator import extract_json  # noqa: E402


@dataclass(slots=True)
class FullOutputTestResult:
    model: str
    status: str
    http_success: bool
    json_parseable: bool
    has_product_analysis: bool
    image_plan_count: int
    has_six_image_plan: bool
    request_id: str | None
    result_text_length: int
    error_message: str | None
    result_text_preview: str
    created_at: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Test full one-shot output models.")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"],
        help="Candidate models to test in order.",
    )
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--stop-on-success", action="store_true")
    args = parser.parse_args()

    app_config = load_app_config(
        PROJECT_ROOT / "configs" / "gateways.yaml",
        PROJECT_ROOT / "configs" / "models.yaml",
    )
    gateway = app_config.gateways[app_config.default_gateway]
    client = OpenAIChatClient(gateway)

    prompt_records = run_get_prompt(
        load_prompt_config(PROJECT_ROOT / "subtasks" / "walmart_image_prompt" / "stages" / "get_pic_prompt" / "config.json")
    )
    if not prompt_records:
        raise RuntimeError("No prompt records generated.")

    source = asdict(prompt_records[0])
    prompt = source["prompt_text"]
    image_url = source["image_urls"][0]
    results: list[FullOutputTestResult] = []

    for model in args.models:
        print(f"testing_model={model}")
        result = test_model(
            client=client,
            model=model,
            prompt=prompt,
            image_url=image_url,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
        )
        results.append(result)
        print(
            f"model={model} status={result.status} "
            f"json={result.json_parseable} image_plan_count={result.image_plan_count} "
            f"error={(result.error_message or '')[:120]}"
        )
        if args.stop_on_success and result.status == "success":
            break

    output_path = PROJECT_ROOT / "data" / "model_full_output_tests" / "results.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    print(f"output={output_path}")
    return 0


def test_model(
    client: OpenAIChatClient,
    model: str,
    prompt: str,
    image_url: str,
    max_tokens: int,
    temperature: float,
) -> FullOutputTestResult:
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
    }
    try:
        response, _latency = client.chat_completions(payload)
        text = extract_chat_text(response)
        parsed, parse_error = extract_json(text)
        image_plan = parsed.get("image_plan") if isinstance(parsed, dict) else None
        image_plan_count = len(image_plan) if isinstance(image_plan, list) else 0
        has_product_analysis = isinstance(parsed, dict) and isinstance(
            parsed.get("product_analysis"), dict
        )
        success = parse_error is None and has_product_analysis and image_plan_count == 6
        return FullOutputTestResult(
            model=model,
            status="success" if success else "validation_failed",
            http_success=True,
            json_parseable=parse_error is None,
            has_product_analysis=has_product_analysis,
            image_plan_count=image_plan_count,
            has_six_image_plan=image_plan_count == 6,
            request_id=response.get("id"),
            result_text_length=len(text),
            error_message=parse_error,
            result_text_preview=text[:1000],
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        return FullOutputTestResult(
            model=model,
            status="failed",
            http_success=False,
            json_parseable=False,
            has_product_analysis=False,
            image_plan_count=0,
            has_six_image_plan=False,
            request_id=None,
            result_text_length=0,
            error_message=str(exc),
            result_text_preview="",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )


if __name__ == "__main__":
    raise SystemExit(main())

