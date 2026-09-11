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
PREFLIGHT_MODELS_OUTPUT = TASK_ROOT / "scripts" / "output" / "available_text_models.json"
BATCHES_ROOT = TASK_ROOT / "batches"


def load_task_config() -> dict[str, Any]:
    if not TASK_CONFIG.exists():
        return {}
    return json.loads(TASK_CONFIG.read_text(encoding="utf-8-sig"))


def task_execution() -> dict[str, Any]:
    return load_task_config().get("execution", {})


def image_provider() -> str:
    provider = load_task_config().get("image_provider", "mxapi")
    if provider not in {"tuzi", "mxapi"}:
        raise ValueError(f"Unsupported image_provider: {provider}")
    return provider


def check_image_provider(*, bind: bool = False) -> None:
    from ai_gateway.clients.image_batch import check_batch_provider
    check_batch_provider(batch_root(), image_provider(), bind=bind)


def apply_image_provider(config):
    config.provider = image_provider()
    config.gateway = config.provider
    gateway = image_gateway_contract()
    config.submit_endpoint = gateway["endpoint_submit"]
    config.query_endpoint = gateway["endpoint_query"]
    return config


def image_gateway_contract() -> dict[str, str]:
    """Protocol endpoints are code, not per-stage user settings."""
    provider = image_provider()
    submit, query = {
        "tuzi": ("/v1/videos", "/v1/videos"),
        "mxapi": ("/api/v2/gpt-image-2", "/api/v2/gpt-image/task"),
    }[provider]
    return {"name": provider, "endpoint_submit": submit, "endpoint_query": query}


def load_stage_data(path: str | Path) -> dict[str, Any]:
    """Resolve the single business input and derived paths before parsing a stage."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    stage = path.parent.name
    if set(data.get("retry", {})) & {"max_retries", "max_submit_retries"}:
        raise ValueError(f"{stage}: configure retry count only in configs/gateways.yaml")
    obsolete = set(data) & {"output", "batch_id", "validation", "prompt_column"}
    obsolete_inputs = set(data.get("input", {})) & {
        "excel_path", "source_excel_path", "source_sheet_name", "model_results_path",
        "prompt_tasks_path", "image_result_excel_path", "download_dir",
    }
    if obsolete or obsolete_inputs:
        raise ValueError(f"{stage}: obsolete stage settings; use business config/derived paths: {sorted(obsolete | obsolete_inputs)}")
    if stage in {"generate_main_image", "generate_sub_images"} and "gateway" in data.get("execution", {}):
        raise ValueError(f"{stage}: choose image_provider only in business config")
    source = task_input()
    if not source.get("excel_path"):
        raise ValueError("config.json input.excel_path is required")
    paths = batch_paths()
    inputs = data.setdefault("input", {})
    outputs = data.setdefault("output", {})
    if stage == "get_pic_prompt":
        inputs.update(excel_path=source["excel_path"], sheet_name=source.get("sheet_name", "Sheet1"))
        outputs["prompt_tasks_path"] = str(paths["prompt_tasks"])
        data["batch_id"] = batch_name_from_input()
    elif stage == "call_prompt_model":
        inputs.update(prompt_tasks_path=str(paths["prompt_tasks"]), source_excel_path=source["excel_path"])
        outputs.update(model_results_path=str(paths["model_results"]), full_outputs_dir=str(paths["full_outputs"]),
                       excel_result_path=str(paths["model_excel"]))
    elif stage in {"generate_main_image", "generate_sub_images"}:
        main = stage == "generate_main_image"
        data["execution"]["gateway"] = image_gateway_contract()
        inputs.update(excel_path=str(paths["main_image_input_excel" if main else "image_input_excel"]),
                      model_results_path=str(paths["model_results"]))
        keys = ("main_image_excel", "main_image_results", "main_image_checkpoint", "main_download_dir", "main_raw_responses") if main else (
            "image_excel", "image_results", "image_checkpoint", "download_dir", "raw_responses")
        outputs.update(zip(("excel_path", "results_path", "checkpoint_path", "download_dir", "raw_responses_dir"),
                           (str(paths[key]) for key in keys)))
    elif stage in {"upload_main_image", "upload_oss"}:
        main = stage == "upload_main_image"
        inputs.update(image_result_excel_path=str(paths["main_image_excel" if main else "image_excel"]),
                      image_results_path=str(paths["main_image_results" if main else "image_results"]),
                      download_dir=str(paths["main_download_dir" if main else "download_dir"]))
        keys = ("main_oss_excel", "main_oss_results", "main_oss_checkpoint") if main else (
            "oss_excel", "oss_results", "oss_checkpoint")
        outputs.update(zip(("excel_path", "results_path", "checkpoint_path"), (str(paths[key]) for key in keys)))
        data["oss"].update(load_task_config()["oss"])
        data["limits"]["max_workers"] = task_execution().get("oss_concurrency", task_execution().get("concurrency", 1))
    elif stage in {"build_main_image_input", "build_sub_image_download_input"}:
        inputs.update(source_excel_path=source["excel_path"], source_sheet_name=source.get("sheet_name", "Sheet1"))
        main = stage == "build_main_image_input"
        if not main:
            inputs["model_results_path"] = str(paths["model_results"])
        outputs["excel_path"] = str(paths["main_image_input_excel" if main else "image_input_excel"])
    else:
        raise ValueError(f"Unknown Walmart stage: {stage}")
    return data


def load_stage_config(path, loader):
    """Keep legacy shared loaders unchanged for other businesses."""
    config = loader(path, config_data=load_stage_data(path))
    if Path(path).parent.name in {"generate_main_image", "generate_sub_images"}:
        apply_image_provider(config)
    return config


def task_input() -> dict[str, Any]:
    return load_task_config().get("input", {})


def workflow_switches() -> dict[str, bool]:
    workflow = load_task_config().get("workflow", {})
    return {
        "generate_prompt_tasks": bool(workflow.get("generate_prompt_tasks", True)),
        "call_prompt_model": bool(workflow.get("call_prompt_model", True)),
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
    raise ValueError("config.json input.excel_path is required")


def batch_root(batch_name: str | None = None) -> Path:
    return BATCHES_ROOT / (safe_batch_name(batch_name) if batch_name else batch_name_from_input())


def batch_paths(batch_name: str | None = None) -> dict[str, Path]:
    root = batch_root(batch_name)
    model_root = root / "02_call_prompt_model"
    return {
        "root": root,
        "prompt_tasks": root / "01_get_pic_prompt" / "generated_prompt_tasks.jsonl",
        "model_results": model_root / "model_results.jsonl",
        "full_outputs": model_root / "full_outputs",
        "model_excel": model_root / "walmart_results.xlsx",
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
    # BUZZ 副图参考数量(sub_image_count)唯一来源：总配置 workflow.buzz_sub_image_count
    # （stage 配置不再保留该字段，避免两处不一致）
    workflow = load_task_config().get("workflow", {})
    if "buzz_sub_image_count" in workflow and workflow["buzz_sub_image_count"] is not None:
        config.sub_image_count = int(workflow["buzz_sub_image_count"])
    if workflow.get("buzz_sub_reference_columns"):
        config.sub_reference_columns = list(workflow["buzz_sub_reference_columns"])
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
    apply_image_provider(config)
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
    # OSS对象模板只有业务总配置一处来源。
    task_oss = load_task_config().get("oss", {})
    if task_oss.get("key_template") is not None:
        config.key_template = str(task_oss["key_template"])
    return config


def build_image_input_config_for_batch() -> dict[str, Any]:
    config = load_stage_data(BUILD_IMAGE_INPUT_CONFIG)
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
    config = load_stage_data(BUILD_MAIN_CONFIG)
    input_config = task_input()
    paths = batch_paths()
    if input_config.get("excel_path"):
        config["input"]["source_excel_path"] = input_config["excel_path"]
    if input_config.get("sheet_name"):
        config["input"]["source_sheet_name"] = input_config["sheet_name"]
    config["output"]["excel_path"] = str(paths["main_image_input_excel"])
    return config


def apply_batch_to_main_image_config(config):
    apply_image_provider(config)
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
    # OSS对象模板只有业务总配置一处来源。
    task_oss = load_task_config().get("oss", {})
    if task_oss.get("key_template") is not None:
        config.key_template = str(task_oss["key_template"])
    return config


def key_fingerprint(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:12]


def preflight_text_model(call_config) -> None:
    from ai_gateway.config.loader import load_app_config
    from ai_gateway.subtasks.walmart_call_prompt_model import fetch_gateway_models

    app_config = load_app_config(call_config.gateways_path, call_config.models_path)
    model_name = call_config.model or app_config.default_model
    gateway_name = call_config.gateway or app_config.models.get(model_name, {}).get("gateway") or app_config.default_gateway
    gateway = app_config.gateways[gateway_name]
    api_key = gateway.api_key()
    gateway_label = gateway_name.upper()
    models_output = PREFLIGHT_MODELS_OUTPUT.with_name(f"available_{gateway_name}_models.json")
    print("\n=== 启动检查 ===")
    print(f"{gateway_label} Key: {gateway.api_key_env} ({key_fingerprint(api_key)})")

    available = fetch_gateway_models(gateway)
    payload = {"object": "list", "data": [{"id": item} for item in available]}
    models_output.parent.mkdir(parents=True, exist_ok=True)
    models_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"可用模型数: {len(available)}")
    print(f"模型列表缓存: {models_output}")
    configured_models = list(dict.fromkeys([model_name, *call_config.model_candidates]))
    available_candidates = [item for item in configured_models if item in available]
    if not available_candidates:
        sample = ", ".join(str(item) for item in available[:20])
        raise RuntimeError(
            f"No configured model is available for current {gateway_label} key. "
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

    config = apply_batch_to_prompt_config(load_stage_config(GET_PROMPT_CONFIG, load_config))
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
