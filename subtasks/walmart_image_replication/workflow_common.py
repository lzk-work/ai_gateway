from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_ROOT.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

TASK_CONFIG = TASK_ROOT / "config.json"
GENERATE_CONFIG = TASK_ROOT / "stages" / "generate_images" / "config.json"
UPLOAD_CONFIG = TASK_ROOT / "stages" / "upload_oss" / "config.json"
BATCHES_ROOT = TASK_ROOT / "batches"


def load_task_config() -> dict[str, Any]:
    return json.loads(TASK_CONFIG.read_text(encoding="utf-8-sig"))


def safe_batch_name(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value.strip()).strip("._-")
    return value or "unnamed_batch"


def batch_name() -> str:
    source = load_task_config()["input"]["excel_path"]
    return safe_batch_name(Path(source).stem)


def batch_root() -> Path:
    return BATCHES_ROOT / batch_name()


def paths() -> dict[str, Path]:
    root = batch_root()
    return {
        "root": root,
        "image_input": root / "01_build_replication_input" / "walmart_replication_input.xlsx",
        "image_results": root / "02_generate_images" / "image_generation_results.jsonl",
        "image_checkpoint": root / "02_generate_images" / "image_generation_checkpoint.jsonl",
        "image_excel": root / "02_generate_images" / "walmart_replication_generation_result.xlsx",
        "download_dir": root / "02_generate_images" / "downloaded_images",
        "raw_responses": root / "02_generate_images" / "raw_responses",
        "oss_results": root / "03_upload_oss" / "oss_upload_results.jsonl",
        "oss_checkpoint": root / "03_upload_oss" / "oss_upload_checkpoint.jsonl",
        "oss_excel": root / "03_upload_oss" / "walmart_replication_oss_result.xlsx",
        "final_excel": root / "04_build_final_result" / "最终图片结果_由复刻生成.xlsx",
        "review_excel": root / "05_review" / "复刻图片审核预览.xlsx",
    }


def image_provider() -> str:
    provider = str(load_task_config().get("image_provider", "tuzi"))
    if provider not in {"tuzi", "mxapi"}:
        raise ValueError(f"Unsupported image_provider: {provider}")
    return provider


def image_contract() -> dict[str, str]:
    provider = image_provider()
    submit, query = {
        "tuzi": ("/v1/videos", "/v1/videos"),
        "mxapi": ("/api/v2/gpt-image-2", "/api/v2/gpt-image/task"),
    }[provider]
    return {"name": provider, "endpoint_submit": submit, "endpoint_query": query}


def generation_config_data() -> dict[str, Any]:
    data = json.loads(GENERATE_CONFIG.read_text(encoding="utf-8-sig"))
    p = paths()
    data["execution"]["gateway"] = image_contract()
    data["input"].update(excel_path=str(p["image_input"]), model_results_path=str(p["root"] / "unused.jsonl"))
    data["output"] = {
        "excel_path": str(p["image_excel"]),
        "results_path": str(p["image_results"]),
        "checkpoint_path": str(p["image_checkpoint"]),
        "download_dir": str(p["download_dir"]),
        "raw_responses_dir": str(p["raw_responses"]),
    }
    return data


def upload_config_data() -> dict[str, Any]:
    data = json.loads(UPLOAD_CONFIG.read_text(encoding="utf-8-sig"))
    cfg = load_task_config()
    p = paths()
    data["input"].update(
        image_result_excel_path=str(p["image_excel"]),
        image_results_path=str(p["image_results"]),
        download_dir=str(p["download_dir"]),
    )
    data["output"] = {
        "excel_path": str(p["oss_excel"]),
        "results_path": str(p["oss_results"]),
        "checkpoint_path": str(p["oss_checkpoint"]),
    }
    data["oss"].update(cfg.get("oss", {}))
    data["limits"]["max_workers"] = int(cfg.get("execution", {}).get("oss_concurrency", 1))
    return data


def print_batch_info() -> None:
    print(f"批次名: {batch_name()}")
    print(f"批次目录: {batch_root()}")
