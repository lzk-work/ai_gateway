"""Shared helpers for Walmart image-prompt workflow entry scripts."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_ROOT.parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

TASK_CONFIG = TASK_ROOT / "config.json"
GET_PROMPT_CONFIG = TASK_ROOT / "stages" / "get_pic_prompt" / "config.json"
CALL_MODEL_CONFIG = TASK_ROOT / "stages" / "call_prompt_model" / "config.json"
BUILD_IMAGE_INPUT_CONFIG = TASK_ROOT / "stages" / "build_sub_image_download_input" / "config.json"
GENERATE_IMAGES_CONFIG = TASK_ROOT / "stages" / "generate_sub_images" / "config.json"
UPLOAD_OSS_CONFIG = TASK_ROOT / "stages" / "upload_oss" / "config.json"
BUILD_MAIN_CONFIG = TASK_ROOT / "stages" / "build_main_image_input" / "config.json"
GENERATE_MAIN_CONFIG = TASK_ROOT / "stages" / "generate_main_image" / "config.json"
UPLOAD_MAIN_CONFIG = TASK_ROOT / "stages" / "upload_main_image" / "config.json"
PREFLIGHT_MODELS_OUTPUT = TASK_ROOT / "scripts" / "output" / "available_buzz_models.json"
BATCHES_ROOT = TASK_ROOT / "batches"


def load_task_config() -> dict[str, Any]:
    if not TASK_CONFIG.exists():
        return {}
    return json.loads(TASK_CONFIG.read_text(encoding="utf-8-sig"))


def task_execution() -> dict[str, Any]:
    return load_task_config().get("execution", {})


def task_input() -> dict[str, Any]:
    return load_task_config().get("input", {})


def workflow_switches() -> dict[str, bool]:
    workflow = load_task_config().get("workflow", {})
    return {
        "generate_prompt_tasks": bool(workflow.get("generate_prompt_tasks", True)),
        "call_buzz_model": bool(workflow.get("call_buzz_model", True)),
        "generate_and_download_images": bool(workflow.get("generate_and_download_images", False)),
        "upload_oss": bool(workflow.get("upload_oss", False)),
        "generate_main_image": bool(workflow.get("generate_main_image", False)),
        "upload_main_image": bool(workflow.get("upload_main_image", False)),
        "build_final_result": bool(workflow.get("build_final_result", True)),
    }


def safe_batch_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unnamed_batch"


def batch_name_from_input() -> str:
    input_config = task_input()
    excel_path = input_config.get("excel_path")
    if excel_path:
        return safe_batch_name(Path(excel_path).stem)
    from ai_gateway.subtasks.walmart_get_pic_prompt import load_config
    return safe_batch_name(Path(load_config(GET_PROMPT_CONFIG).input_excel).stem)


def batch_root(batch_name: str | None = None) -> Path:
    return BATCHES_ROOT / (safe_batch_name(batch_name) if batch_name else batch_name_from_input())


def batch_paths(batch_name: str | None = None) -> dict[str, Path]:
    root = batch_root(batch_name)
    return {
        "root": root,
        "prompt_tasks": root / "01_get_pic_prompt" / "generated_prompt_tasks.jsonl",
        "model_results": root / "02_call_buzz_model" / "model_results.jsonl",
        "full_outputs": root / "02_call_buzz_model" / "full_outputs",
        "model_excel": root / "02_call_buzz_model" / "walmart_results.xlsx",
        "image_input_excel": root / "03_build_image_input" / "walmart_sub_image_input_result.xlsx",
        "image_results": root / "04_generate_images" / "image_generation_results.jsonl",
        "image_checkpoint": root / "04_generate_images" / "image_generation_checkpoint.jsonl",
        "image_excel": root / "04_generate_images" / "walmart_sub_image_generation_result.xlsx",
        "download_dir": root / "04_generate_images" / "downloaded_images",
        "raw_responses": root / "04_generate_images" / "raw_responses",
        "oss_results": root / "05_upload_oss" / "oss_upload_results.jsonl",
        "oss_checkpoint": root / "05_upload_oss" / "oss_upload_checkpoint.jsonl",
        "oss_excel": root / "05_upload_oss" / "walmart_sub_image_oss_result.xlsx",
        "final_image_excel": root / "05_upload_oss" / "最终图片结果_由sub生成.xlsx",
        "main_image_input_excel": root / "03b_build_main_image_input" / "walmart_main_image_input_result.xlsx",
        "main_image_results": root / "04b_generate_main_images" / "image_generation_results.jsonl",
        "main_image_checkpoint": root / "04b_generate_main_images" / "image_generation_checkpoint.jsonl",
        "main_image_excel": root / "04b_generate_main_images" / "walmart_main_image_generation_result.xlsx",
        "main_download_dir": root / "04b_generate_main_images" / "downloaded_images",
        "main_raw_responses": root / "04b_generate_main_images" / "raw_responses",
        "main_oss_results": root / "05b_upload_main_oss" / "oss_upload_results.jsonl",
        "main_oss_checkpoint": root / "05b_upload_main_oss" / "oss_upload_checkpoint.jsonl",
        "main_oss_excel": root / "05b_upload_main_oss" / "walmart_main_image_oss_result.xlsx",
    }


def print_batch_info(batch_name: str | None = None) -> None:
    effective = safe_batch_name(batch_name) if batch_name else batch_name_from_input()
    print(f"批次名: {effective}")
    print(f"批次目录: {batch_root(batch_name)}")


def apply_batch_to_prompt_config(config):
    input_config = task_input()
    if input_config.get("excel_path"):
        config.input_excel = input_config["excel_path"]
    if input_config.get("sheet_name"):
        config.sheet_name = input_config["sheet_name"]
    paths = batch_paths()
    config.output_path = str(paths["prompt_tasks"])
    config.batch_id = batch_name_from_input()
    return config


def apply_batch_to_call_config(config):
    input_config = task_input()
    if input_config.get("excel_path"):
        config.source_excel_path = input_config["excel_path"]
    paths = batch_paths()
    config.input_path = str(paths["prompt_tasks"])
    config.output_path = str(paths["model_results"])
    config.full_outputs_dir = str(paths["full_outputs"])
    config.excel_result_path = str(paths["model_excel"])
    return config


def apply_batch_to_image_config(config):
    paths = batch_paths()
    config.input_excel_path = str(paths["image_input_excel"])
    config.model_results_path = str(paths["model_results"])
    config.output_excel_path = str(paths["image_excel"])
    config.output_results_path = str(paths["image_results"])
    config.checkpoint_path = str(paths["image_checkpoint"])
    config.download_dir = str(paths["download_dir"])
    config.raw_responses_dir = str(paths["raw_responses"])
    return config


def apply_batch_to_oss_config(config, batch_name: str | None = None):
    paths = batch_paths(batch_name)
    config.input_excel_path = str(paths["image_excel"])
    config.image_results_path = str(paths["image_results"])
    config.download_dir = str(paths["download_dir"])
    config.output_excel_path = str(paths["oss_excel"])
    config.output_results_path = str(paths["oss_results"])
    config.checkpoint_path = str(paths["oss_checkpoint"])
    # 业务总配置优先：config.json 的 oss 块覆盖阶段配置（stages/upload_oss/config.json）的默认值。
    task_oss = load_task_config().get("oss", {})
    if task_oss.get("prefix") is not None:
        config.oss_prefix = str(task_oss["prefix"]).strip("/")
    if task_oss.get("key_template") is not None:
        config.key_template = str(task_oss["key_template"])
    return config


def build_image_input_config_for_batch() -> dict[str, Any]:
    config = json.loads(BUILD_IMAGE_INPUT_CONFIG.read_text(encoding="utf-8-sig"))
    input_config = task_input()
    paths = batch_paths()
    if input_config.get("excel_path"):
        config["input"]["source_excel_path"] = input_config["excel_path"]
    if input_config.get("sheet_name"):
        config["input"]["source_sheet_name"] = input_config["sheet_name"]
    config["input"]["model_results_path"] = str(paths["model_results"])
    config["output"]["excel_path"] = str(paths["image_input_excel"])
    return config


def build_main_image_input_config_for_batch() -> dict[str, Any]:
    config = json.loads(BUILD_MAIN_CONFIG.read_text(encoding="utf-8-sig"))
    input_config = task_input()
    paths = batch_paths()
    if input_config.get("excel_path"):
        config["input"]["source_excel_path"] = input_config["excel_path"]
    if input_config.get("sheet_name"):
        config["input"]["source_sheet_name"] = input_config["sheet_name"]
    config["output"]["excel_path"] = str(paths["main_image_input_excel"])
    return config


def apply_batch_to_main_image_config(config):
    paths = batch_paths()
    config.input_excel_path = str(paths["main_image_input_excel"])
    config.model_results_path = str(paths["model_results"])
    config.output_excel_path = str(paths["main_image_excel"])
    config.output_results_path = str(paths["main_image_results"])
    config.checkpoint_path = str(paths["main_image_checkpoint"])
    config.download_dir = str(paths["main_download_dir"])
    config.raw_responses_dir = str(paths["main_raw_responses"])
    return config


def apply_batch_to_main_oss_config(config, batch_name: str | None = None):
    paths = batch_paths(batch_name)
    config.input_excel_path = str(paths["main_image_excel"])
    config.image_results_path = str(paths["main_image_results"])
    config.download_dir = str(paths["main_download_dir"])
    config.output_excel_path = str(paths["main_oss_excel"])
    config.output_results_path = str(paths["main_oss_results"])
    config.checkpoint_path = str(paths["main_oss_checkpoint"])
    # 业务总配置优先：config.json 的 oss 块覆盖阶段配置默认值。
    task_oss = load_task_config().get("oss", {})
    if task_oss.get("prefix") is not None:
        config.oss_prefix = str(task_oss["prefix"]).strip("/")
    if task_oss.get("key_template") is not None:
        config.key_template = str(task_oss["key_template"])
    return config


def key_fingerprint(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:12]


def preflight_buzz_model(call_config) -> None:
    from ai_gateway.config.loader import load_app_config
    from ai_gateway.subtasks.walmart_call_prompt_model import fetch_gateway_models

    app_config = load_app_config(call_config.gateways_path, call_config.models_path)
    model_name = call_config.model or app_config.default_model
    gateway_name = call_config.gateway or app_config.models.get(model_name, {}).get("gateway") or app_config.default_gateway
    gateway = app_config.gateways[gateway_name]
    api_key = gateway.api_key()
    print("\n=== 启动检查 ===")
    print(f"BUZZ Key: {gateway.api_key_env} ({key_fingerprint(api_key)})")

    available = fetch_gateway_models(gateway)
    payload = {"object": "list", "data": [{"id": item} for item in available]}
    PREFLIGHT_MODELS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PREFLIGHT_MODELS_OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"可用模型数: {len(available)}")
    print(f"模型列表缓存: {PREFLIGHT_MODELS_OUTPUT}")
    configured_models = list(dict.fromkeys([model_name, *call_config.model_candidates]))
    available_candidates = [item for item in configured_models if item in available]
    if not available_candidates:
        sample = ", ".join(str(item) for item in available[:20])
        raise RuntimeError(
            "No configured model is available for current BUZZ key. "
            f"Configured models: {', '.join(configured_models)}. "
            f"Available examples: {sample}"
        )
    if model_name not in available_candidates:
        call_config.model = available_candidates[0]
        print(f"模型预检: 已切换 {model_name} -> {call_config.model}")
    else:
        print(f"模型预检: 通过 ({model_name})")
    call_config.model_candidates = [item for item in call_config.model_candidates if item in available]
    if call_config.model_candidates:
        print(f"可用候选: {', '.join(call_config.model_candidates)}")


def build_current_prompt_task_preview_rows() -> list[dict[str, Any]]:
    from ai_gateway.subtasks.walmart_get_pic_prompt import _is_empty_row, load_config, read_excel_rows, validate_required_columns

    config = apply_batch_to_prompt_config(load_config(GET_PROMPT_CONFIG))
    if not Path(config.input_excel).exists():
        return []
    batch_id = batch_name_from_input()
    rows = []
    validate_required_columns(config)
    excel_rows = read_excel_rows(config.input_excel, config.sheet_name)
    for row_number, row in excel_rows:
        if _is_empty_row(row):
            continue
        sku = str(row.get(config.task_id_column) or f"row-{row_number}").strip()
        task_id = f"{batch_id}:{sku}"
        rows.append(
            {
                "task_id": task_id,
                "sku": sku,
                "row_number": row_number,
                "next_task_payload": {
                    "task_id": task_id,
                    "batch_id": batch_id,
                    "metadata": {"sku": sku, "source_row_number": row_number},
                },
            }
        )
    return rows
