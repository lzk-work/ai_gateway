"""Shared helpers for Walmart image-replace workflow entry scripts."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_ROOT.parents[1]
SRC_DIR = PROJECT_ROOT / "src"
# 复用框架共享模块（mxapi_generate_images / oss_upload_images），与 walmart_image_prompt 同款做法
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

BATCHES_ROOT = TASK_ROOT / "batches"
TASK_CONFIG = TASK_ROOT / "config.json"

# 各阶段配置（与 walmart_image_prompt 惯例一致：阶段参数在 stages/<stage>/config.json）
STAGE_CONFIGS = {
    "query_existing_images": TASK_ROOT / "stages" / "query_existing_images" / "config.json",
    "generate_prompts": TASK_ROOT / "stages" / "generate_prompts" / "config.json",
    "generate_images": TASK_ROOT / "stages" / "generate_images" / "config.json",
    "upload_oss": TASK_ROOT / "stages" / "upload_oss" / "config.json",
    "build_replace_result": TASK_ROOT / "stages" / "build_replace_result" / "config.json",
    "submit_replace": TASK_ROOT / "stages" / "submit_replace" / "config.json",
    "reconcile": TASK_ROOT / "stages" / "reconcile" / "config.json",
    "build_report": TASK_ROOT / "stages" / "build_report" / "config.json",
}


def load_task_config() -> dict[str, Any]:
    if not TASK_CONFIG.exists():
        return {}
    return json.loads(TASK_CONFIG.read_text(encoding="utf-8-sig"))


def load_stage_config(stage: str) -> dict[str, Any]:
    """加载指定阶段的 stages/<stage>/config.json（不存在则返回空 dict）。"""
    path = STAGE_CONFIGS[stage]
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def task_input() -> dict[str, Any]:
    return load_task_config().get("input", {})


def task_replace() -> dict[str, Any]:
    """替换参数（min/max 副图数等），优先读阶段配置，任务级 replace 段为兼容保留。"""
    stage = load_stage_config("query_existing_images")
    if stage:
        limits = stage.get("limits", {})
        return {"min_sub_images": limits.get("min_sub_images", 4),
                "max_sub_images": limits.get("max_sub_images", 6)}
    return load_task_config().get("replace", {})


def task_execution() -> dict[str, Any]:
    return load_task_config().get("execution", {})


def walmart_stores() -> dict[str, Any]:
    return load_task_config().get("walmart_api", {}).get("stores", {})


def load_local_env() -> dict[str, str]:
    """读取 configs/local.env（已 .gitignore），返回 key→value 映射。

    与共享模块 oss_upload_images.load_local_env 同源，但本任务独立实现以避免
    运行时 import src.ai_gateway（本地未装 requests/oss2 时仍能读取本地配置）。
    """
    env_path = PROJECT_ROOT / "configs" / "local.env"
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def oss_public_base() -> str | None:
    """拼 OSS 公网访问基座：https://{bucket}.{endpoint}/{default_prefix}。

    bucket/endpoint 来自 configs/local.env（ALIYUN_OSS_BUCKET / ALIYUN_OSS_ENDPOINT，
    default_prefix 取 ALIYUN_OSS_DEFAULT_PREFIX，默认 images）。
    任一必需项缺失返回 None，调用方据此报错退出（不再静默回退 mock）。
    """
    env = load_local_env()

    def get(name: str, default: str = "") -> str:
        return os.environ.get(name) or env.get(name) or default

    bucket = get("ALIYUN_OSS_BUCKET").strip()
    endpoint = get("ALIYUN_OSS_ENDPOINT").strip()
    if not bucket or not endpoint:
        return None
    endpoint = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    prefix = get("ALIYUN_OSS_DEFAULT_PREFIX", "images").strip().strip("/")
    return f"https://{bucket}.{endpoint}/{prefix}" if prefix else f"https://{bucket}.{endpoint}"


def walmart_store_credentials(store_key: str) -> dict[str, str | None]:
    """按 store_key 从 configs/local.env 加载沃尔玛 API 凭证。

    返回 {"client_id": ..., "client_secret": ...}。
    任一凭证缺失则对应值为 None，调用方应在预检中拦截。
    """
    stores = walmart_stores()
    store_key = resolve_store_key(store_key, stores)
    store_cfg = stores.get(store_key)
    if not store_cfg:
        return {"client_id": None, "client_secret": None}
    env = load_local_env()
    return {
        "client_id": os.environ.get(store_cfg.get("api_key_env", "")) or env.get(store_cfg.get("api_key_env", "")),
        "client_secret": os.environ.get(store_cfg.get("secret_env", "")) or env.get(store_cfg.get("secret_env", "")),
    }


def resolve_store_key(name: str, stores: dict[str, Any] | None = None) -> str:
    """把入参 Excel 的「店铺」列值解析为 config.json stores 的 key。

    匹配优先级：
      1. name 直接等于某个 store key（如 'store_us'）→ 返回 name
      2. name 等于某个 store 的 business_unit（如 '娜美-沃尔玛'）→ 返回对应 key
      3. 均不命中 → 原样返回，让下游 `p['store'] not in stores` 拦截报错
    """
    if stores is None:
        stores = walmart_stores()
    if name in stores:
        return name
    for key, cfg in stores.items():
        if str(cfg.get("business_unit", "")).strip() == name:
            return key
    return name


def walmart_token_config() -> dict[str, Any]:
    """沃尔玛 API token 获取参数（feed 级 auth 用）。"""
    return load_task_config().get("walmart_api", {})


def workflow_switches() -> dict[str, bool]:
    w = load_task_config().get("workflow", {})
    return {
        "query_existing_images": bool(w.get("query_existing_images", True)),
        "generate_prompts": bool(w.get("generate_prompts", True)),
        "generate_images": bool(w.get("generate_images", True)),
        "upload_oss": bool(w.get("upload_oss", True)),
        "build_replace_result": bool(w.get("build_replace_result", True)),
        "submit_replace": bool(w.get("submit_replace", True)),
        "reconcile": bool(w.get("reconcile", True)),
        "build_report": bool(w.get("build_report", True)),
    }


def safe_batch_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unnamed_batch"


def batch_name_from_input() -> str:
    excel_path = task_input().get("excel_path")
    if excel_path:
        return safe_batch_name(Path(excel_path).stem)
    return "default_batch"


def batch_root(batch_name: str | None = None) -> Path:
    return BATCHES_ROOT / (safe_batch_name(batch_name) if batch_name else batch_name_from_input())


def batch_paths(batch_name: str | None = None) -> dict[str, Path]:
    root = batch_root(batch_name)
    return {
        "root": root,
        "inventory": root / "01_query_existing_images" / "image_inventory.jsonl",
        # 02 产出与 walmart_image_prompt 的 02 同构：model_results.jsonl + full_outputs/<sku>.json，
        # 供共享模块 mxapi_generate_images.load_prompt_map 直接消费。
        "model_results": root / "02_generate_prompts" / "model_results.jsonl",
        "full_outputs": root / "02_generate_prompts" / "full_outputs",
        # 03 图片流水线（与 walmart_image_prompt 03/04 同构）
        "image_input_excel": root / "03_generate_images" / "image_input.xlsx",
        "image_results": root / "03_generate_images" / "image_generation_results.jsonl",
        "image_checkpoint": root / "03_generate_images" / "image_generation_checkpoint.jsonl",
        "image_excel": root / "03_generate_images" / "image_generation_result.xlsx",
        "download_dir": root / "03_generate_images" / "downloaded_images",
        "raw_responses": root / "03_generate_images" / "raw_responses",
        # 04 OSS 上传（复用共享 oss_upload_images，行级记录）
        "oss_results": root / "04_upload_oss" / "oss_upload_results.jsonl",
        "oss_checkpoint": root / "04_upload_oss" / "oss_upload_checkpoint.jsonl",
        "oss_excel": root / "04_upload_oss" / "oss_upload_result.xlsx",
        "payload": root / "05_build_replace_result" / "replace_payload.jsonl",
        # 06/07 沃尔玛 Feed 真实提交与对账
        "submit_results": root / "06_submit_replace" / "submit_results.jsonl",
        "reconcile_results": root / "07_reconcile" / "reconcile_results.jsonl",
        "report": root / "08_build_report" / "result_report.jsonl",
        "report_xlsx": root / "08_build_report" / "result_report.xlsx",
    }


def ensure_dirs(batch_name: str | None = None) -> dict[str, Path]:
    paths = batch_paths(batch_name)
    for p in paths.values():
        if p.suffix:  # 文件
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir(parents=True, exist_ok=True)
    return paths


def print_batch_info(batch_name: str | None = None) -> None:
    effective = safe_batch_name(batch_name) if batch_name else batch_name_from_input()
    print(f"批次名: {effective}")
    print(f"批次目录: {batch_root(batch_name)}")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def apply_batch_to_image_config(config):
    """把批次目录注入共享模块 mxapi_generate_images 的配置对象。"""
    paths = batch_paths()
    config.input_excel_path = str(paths["image_input_excel"])
    config.model_results_path = str(paths["model_results"])
    config.output_excel_path = str(paths["image_excel"])
    config.output_results_path = str(paths["image_results"])
    config.checkpoint_path = str(paths["image_checkpoint"])
    config.download_dir = str(paths["download_dir"])
    config.raw_responses_dir = str(paths["raw_responses"])
    # 本任务的图片行数已在 01/03-1 按「缺失位置」精确展开，无需共享模块的
    # desired_count 截断（其取值硬编码来自 walmart_image_prompt 总配置，与本品无关）。
    config.desired_count = None
    config.image_type_order = []
    return config


def apply_batch_to_oss_config(config, batch_name: str | None = None):
    """把批次目录注入共享模块 oss_upload_images 的配置对象。"""
    paths = batch_paths(batch_name)
    config.input_excel_path = str(paths["image_excel"])
    config.image_results_path = str(paths["image_results"])
    config.download_dir = str(paths["download_dir"])
    config.output_excel_path = str(paths["oss_excel"])
    config.output_results_path = str(paths["oss_results"])
    config.checkpoint_path = str(paths["oss_checkpoint"])
    return config
