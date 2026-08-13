"""Execution confirmation summary for the Walmart image workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workflow_common import (
    CALL_MODEL_CONFIG,
    GENERATE_IMAGES_CONFIG,
    GET_PROMPT_CONFIG,
    PROJECT_ROOT,
    UPLOAD_OSS_CONFIG,
    batch_name_from_input,
    batch_paths,
    load_task_config,
    task_execution,
    task_input,
    workflow_switches,
)

from ai_gateway.config.loader import load_app_config, load_local_env
from ai_gateway.subtasks.walmart_get_pic_prompt import _is_empty_row, load_config, read_excel_rows, validate_required_columns


def print_execution_confirmation(dry_run: bool = False) -> bool:
    task_config = load_task_config()
    execution = task_execution()
    input_config = task_input()
    switches = workflow_switches()
    paths = batch_paths()
    batch_name = batch_name_from_input()
    excel_path = input_config.get("excel_path", "")
    sheet_name = input_config.get("sheet_name") or "active"
    task_count = count_input_rows()

    call_config = read_json(CALL_MODEL_CONFIG)
    image_config = read_json(GENERATE_IMAGES_CONFIG)
    upload_config = read_json(UPLOAD_OSS_CONFIG)
    app_config = load_app_config(PROJECT_ROOT / "configs" / "gateways.yaml", PROJECT_ROOT / "configs" / "models.yaml")
    local_env = load_local_env(PROJECT_ROOT / "configs" / "local.env")

    print("\n=== 执行前确认 ===")
    print(f"业务任务: {task_config.get('name', 'walmart_image_prompt')}")
    print(f"运行模式: {'试运行' if dry_run else '正式执行'}")
    print(f"批次名: {batch_name}")
    print(f"批次目录: {paths['root']}")
    print(f"入参Excel: {excel_path}")
    print(f"Sheet: {sheet_name}")
    print(f"Excel有效任务数: {task_count}")
    print(f"业务 max_records: {execution.get('max_records')}")
    print(
        "阶段开关: "
        f"01={switches['generate_prompt_tasks']} | "
        f"02={switches['call_buzz_model']} | "
        f"03={switches['generate_and_download_images']} | "
        f"05={switches['upload_oss']} | "
        f"06={switches['build_final_result']}"
    )

    print("\n--- 01 生成提示词任务 ---")
    print_stage_state(switches["generate_prompt_tasks"])
    print(f"输出任务: {paths['prompt_tasks']}")

    print("\n--- 02 BUZZ 文本模型 ---")
    print_stage_state(switches["call_buzz_model"])
    model = call_config.get("execution", {}).get("model", {})
    gateway = call_config.get("execution", {}).get("gateway", {})
    gateway_name = gateway.get("name", "buzz")
    gateway_config = app_config.gateways.get(gateway_name)
    print(f"网关: {gateway_name}")
    if gateway_config:
        print(f"API: {gateway_config.base_url}{gateway.get('endpoint', '/v1/chat/completions')}")
        print(f"Key环境变量: {gateway_config.api_key_env}")
        print(f"超时/重试: {gateway_config.timeout_seconds}s / {gateway_config.max_retries}")
    print(f"模型: {model.get('name')}")
    print(f"候选模型: {', '.join(model.get('candidates', [])) or '无'}")
    print(f"stream: {model.get('stream')} | max_tokens: {model.get('max_tokens')} | temperature: {model.get('temperature')}")
    print(f"并发: {execution.get('concurrency', 1)} | 启动模型预检: {execution.get('preflight_model', True)}")
    print(f"结果日志: {paths['model_results']}")
    print(f"完整输出: {paths['full_outputs']}")

    print("\n--- 03 MXAPI 生成并下载图片 ---")
    print_stage_state(switches["generate_and_download_images"])
    image_gateway = image_config.get("execution", {}).get("gateway", {})
    image_model = image_config.get("execution", {}).get("model", {})
    image_gateway_name = image_gateway.get("name", "mxapi")
    image_gateway_config = app_config.gateways.get(image_gateway_name)
    print(f"网关: {image_gateway_name}")
    if image_gateway_config:
        print(f"提交API: {image_gateway_config.base_url}{image_gateway.get('endpoint_submit')}")
        print(f"查询API: {image_gateway_config.base_url}{image_gateway.get('endpoint_query')}")
        print(f"Key环境变量: {image_gateway_config.api_key_env}")
        print(f"超时/重试: {image_gateway_config.timeout_seconds}s / {image_gateway_config.max_retries}")
    print(
        "模型参数: "
        f"{image_model.get('name')} | "
        f"aspect_ratio={image_model.get('aspect_ratio')} | "
        f"quality={image_model.get('quality')} | "
        f"resolution={image_model.get('resolution')}"
    )
    print(f"图片并发: {execution.get('image_concurrency', execution.get('concurrency', 1))}")
    print(f"下载目录: {paths['download_dir']}")
    print(f"图片结果: {paths['image_excel']}")

    print("\n--- 05 上传 OSS ---")
    print_stage_state(switches["upload_oss"])
    # 业务总配置 config.json 的 oss 块优先，未配置时回退到阶段配置默认值。
    oss = {**upload_config.get("oss", {}), **load_task_config().get("oss", {})}
    default_prefix = local_env.get("ALIYUN_OSS_DEFAULT_PREFIX", "images").strip("/")
    bucket = local_env.get("ALIYUN_OSS_BUCKET", "<未配置>")
    endpoint = local_env.get("ALIYUN_OSS_ENDPOINT", "<未配置>")
    key_template = str(oss.get("key_template") or "").lstrip("/")
    full_key_template = f"{default_prefix}/{key_template}" if default_prefix else key_template
    print(f"OSS Bucket: {bucket}")
    print(f"OSS Endpoint: {endpoint}")
    print(f"OSS对象路径模板: {full_key_template}")
    print(f"overwrite: {oss.get('overwrite')}")
    print(f"上传并发: {execution.get('oss_concurrency', execution.get('concurrency', 1))} | batch_size: {execution.get('oss_batch_size')}")
    print(f"上传结果: {paths['oss_excel']}")

    print("\n--- 06 最终图片结果表 ---")
    print_stage_state(switches["build_final_result"])
    print(f"最终结果表: {paths['final_image_excel']}")

    if dry_run:
        print("\n试运行模式不需要确认。")
        return True

    answer = input("\n确认执行请直接回车；输入任意内容后回车取消执行: ")
    if answer.strip():
        print("已取消执行。")
        return False
    print("已确认，开始执行。")
    return True


def print_stage_state(enabled: bool) -> None:
    print(f"状态: {'执行' if enabled else '跳过'}")


def count_input_rows() -> int:
    config = load_config(GET_PROMPT_CONFIG)
    from workflow_common import apply_batch_to_prompt_config

    config = apply_batch_to_prompt_config(config)
    if not Path(config.input_excel).exists():
        return 0
    validate_required_columns(config)
    return sum(1 for _, row in read_excel_rows(config.input_excel, config.sheet_name) if not _is_empty_row(row))


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
