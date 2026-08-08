"""Step 02: Call BUZZ text model and write validated JSON results."""

from __future__ import annotations

import argparse

from workflow_common import (
    CALL_MODEL_CONFIG,
    apply_batch_to_call_config,
    build_current_prompt_task_preview_rows,
    print_batch_info,
    preflight_buzz_model,
    task_execution,
)

from ai_gateway.subtasks.walmart_call_prompt_model import (
    completed_ids,
    load_config,
    read_jsonl,
    read_jsonl_if_exists,
    run,
    source_task_id,
    source_task_sku,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="02 调用 BUZZ 文本模型")
    parser.add_argument("--dry-run", action="store_true", help="只预览待调用任务，不调用 BUZZ，不写结果。")
    parser.add_argument(
        "--preview-current-excel",
        action="store_true",
        help="试运行时按当前 Excel 内存预估任务，用于总流程 dry-run。",
    )
    args = parser.parse_args()

    execution = task_execution()
    config = apply_batch_to_call_config(load_config(CALL_MODEL_CONFIG))
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("concurrency", 1)
    print_batch_info()
    if args.dry_run:
        preview(config, execution, preview_current_excel=args.preview_current_excel)
        return
    if execution.get("preflight_model", True):
        preflight_buzz_model(config)

    records = run(config)
    success_count = sum(1 for item in records if item.status == "success")
    print("\n=== 02 汇总 ===")
    print(f"模型调用: {len(records)} | 成功: {success_count} | 失败/无效: {len(records) - success_count}")


def preview(config, execution, preview_current_excel: bool = False) -> None:
    source_tasks = build_current_prompt_task_preview_rows() if preview_current_excel else read_jsonl(config.input_path)
    existing_rows = read_jsonl_if_exists(config.output_path)
    completed = completed_ids(existing_rows) if config.skip_success else set()
    pending = [row for row in source_tasks if source_task_id(row) not in completed]
    skipped = len(source_tasks) - len(pending)
    selected = pending[: config.max_records] if config.max_records and config.max_records > 0 else pending

    print("\n=== 02 调用 BUZZ 文本模型 | 试运行 ===")
    print("试运行: 不调用 BUZZ，不写 JSONL/Excel")
    source_label = "当前 Excel 内存预估" if preview_current_excel else config.input_path
    print(f"输入任务: {source_label}")
    print(f"历史结果: {config.output_path}")
    print(f"任务总数: {len(source_tasks)} | 已成功跳过: {skipped} | 未成功/待处理: {len(pending)} | 本次将处理: {len(selected)}")
    print(f"网关: {config.gateway or '默认'} | 首选模型: {config.model} | 候选模型: {', '.join(config.model_candidates) or '无'}")
    print(f"并发: {config.concurrency} | max_records: {config.max_records} | stream: {config.stream} | preflight_model: {execution.get('preflight_model', True)}")
    if selected:
        print("样例:")
        for index, task in enumerate(selected[:5], start=1):
            print(f"  [{index}] SKU={source_task_sku(task)} | task_id={source_task_id(task)}")


if __name__ == "__main__":
    main()
