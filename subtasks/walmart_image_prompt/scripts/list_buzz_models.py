"""List BUZZ models available to the current BUZZ_API_KEY.

Run with the same Python/environment you use for this business task:

    D:\\Program\\Anaconda\\python.exe E:\\WorkSpace\\ai_gateway\\subtasks\\walmart_image_prompt\\scripts\\list_buzz_models.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TASK_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = TASK_ROOT / "scripts" / "output" / "available_buzz_models.json"
MODELS_URL = "https://buzzai.cc/v1/models"


def main() -> None:
    api_key = os.environ.get("BUZZ_API_KEY")
    if not api_key:
        raise SystemExit(
            "BUZZ_API_KEY is not set in this process. Set it in the same terminal "
            "or IDE run configuration used to start the task."
        )

    response = request_models(api_key)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

    models = response.get("data") or []
    if not isinstance(models, list):
        print(f"Saved raw response to: {OUTPUT_PATH}")
        raise SystemExit("Unexpected /v1/models response shape; inspect the saved JSON file.")

    print(f"available_model_count={len(models)}")
    print(f"saved_to={OUTPUT_PATH}")
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        endpoints = item.get("supported_endpoint_types")
        owned_by = item.get("owned_by")
        suffix = []
        if owned_by:
            suffix.append(f"owned_by={owned_by}")
        if endpoints:
            suffix.append("endpoints=" + ",".join(map(str, endpoints)))
        print(model_id if not suffix else f"{model_id} ({'; '.join(suffix)})")


def request_models(api_key: str) -> dict:
    request = Request(
        MODELS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "ai_gateway_model_probe/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {body[:1000]}") from exc
    except URLError as exc:
        raise SystemExit(f"Network error: {exc}") from exc
    return json.loads(body)


if __name__ == "__main__":
    main()


