"""Step 03b: Build main-image input, generate main images with MXAPI (fixed prompt), and download."""

from __future__ import annotations

import argparse
from workflow_common import load_stage_config
from pathlib import Path

from workflow_common import (
    check_image_provider,
    image_provider,
    GENERATE_MAIN_CONFIG,
    apply_batch_to_main_image_config,
    build_main_image_input_config_for_batch,
    print_batch_info,
    task_execution,
)

from ai_gateway.subtasks.mxapi_generate_images import (
    CheckpointStore,
    apply_checkpoint_to_rows,
    completed_keys,
    count_skus,
    desired_result_count,
    limit_rows_by_sku,
    load_config,
    load_work_rows,
    row_key,
    run,
)
from scripts.build_main_image_input import run as build_main_image_input


def main() -> None:
    parser = argparse.ArgumentParser(description="03b 生成并下载主图（固定提示词）")
    parser.add_argument("--dry-run", action="store_true", help="只预览主图任务，不生成下载模板，不调用生图平台。")
    args = parser.parse_args()

    check_image_provider(bind=not args.dry_run)

    if args.dry_run:
        preview()
        return

    print("\n=== 03b-1 生成主图下载入参 ===")
    print_batch_info()
    build_main_image_input(build_main_image_input_config_for_batch())

    print(f"\n=== 03b-2 调用 {image_provider().upper()} 生成主图（固定提示词）并下载 ===")
    execution = task_execution()
    config = apply_batch_to_main_image_config(load_stage_config(GENERATE_MAIN_CONFIG, load_config))
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("image_concurrency", execution.get("concurrency", 1))
    records = run(config)
    success_count = sum(1 for item in records if item.status == "success")
    submitted_count = sum(1 for item in records if item.status == "submitted")
    pending_count = sum(1 for item in records if item.status == "pending")
    skipped_count = sum(1 for item in records if item.status == "skipped")
    failed_count = sum(1 for item in records if item.status in {"failed", "failed_permanent", "failed_exhausted"})

    print("\n=== 03b 汇总 ===")
    print(
        f"本轮记录: {len(records)} | 下载成功: {success_count} | 新提交: {submitted_count} | "
        f"查询未确定: {pending_count} | 明确失败: {failed_count} | 目标已满足跳过: {skipped_count}"
    )


def preview() -> None:
    print("\n=== 03b 生成主图 | 试运行 ===")
    print("试运行: 不生成下载模板，不调用生图平台，不下载图片")
    execution = task_execution()
    config = load_stage_config(GENERATE_MAIN_CONFIG, load_config)
    config = apply_batch_to_main_image_config(config)
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("image_concurrency", execution.get("concurrency", 1))
    input_path = Path(config.input_excel_path)
    if not input_path.exists():
        print(f"主图入参 Excel 不存在: {input_path}")
        print("请先正式执行 03b，或单独运行 build_main_image_input.py 生成主图入参。")
        return

    rows, _, _, _ = load_work_rows(config)
    checkpoint = CheckpointStore(config.checkpoint_path)
    checkpoint_rows = checkpoint.rows()
    rows = apply_checkpoint_to_rows(rows, checkpoint_rows)
    completed = completed_keys(checkpoint_rows) if config.skip_success else set()
    pending = [row for row in rows if row_key(row) not in completed]
    selected = limit_rows_by_sku(pending, config.max_records)

    print(f"主图入参: {input_path}")
    print(f"checkpoint: {config.checkpoint_path}")
    local_success = sum(1 for row in rows if row_key(row) in completed)
    print(f"主图候选输入: {len(rows)} 行 / {count_skus(rows)} 个 SKU")
    print(
        f"主图最终目标: {desired_result_count(rows, config.desired_count)} 张 | "
        f"本地已成功(不重复处理): {local_success} 张 | "
        f"尚未成功/待查询: {len(pending)} 行"
    )
    print(
        f"本轮将处理: {len(selected)} 行 / {count_skus(selected)} 个 SKU "
        f"(max_records={config.max_records} 个 SKU)"
    )
    print(f"提示词模式: {config.prompt_mode} | 网关: {config.gateway} | 模型: {config.model} | 并发: {config.concurrency}")
    print(f"下载目录: {config.download_dir}")
    if selected:
        print("样例:")
        for index, row in enumerate(selected[:5], start=1):
            task_id = row.get("task_id") or "无"
            print(f"  [{index}] SKU={row.get('sku')} | 图片={row.get('image_name')} | task_id={task_id}")


if __name__ == "__main__":
    main()
