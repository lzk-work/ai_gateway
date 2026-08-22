"""Step 03: Build image input workbook, generate images with MXAPI, and download files."""

from __future__ import annotations

import argparse
from pathlib import Path

from workflow_common import (
    GENERATE_IMAGES_CONFIG,
    apply_batch_to_image_config,
    batch_paths,
    build_image_input_config_for_batch,
    print_batch_info,
    task_execution,
    workflow_switches,
)

from ai_gateway.subtasks.mxapi_generate_images import (
    CheckpointStore,
    _load_success_skus,
    apply_checkpoint_to_rows,
    completed_keys,
    count_skus,
    limit_rows_by_sku,
    load_config,
    load_work_rows,
    row_key,
    run,
)
from scripts.build_sub_image_download_input import run as build_image_input


def main() -> None:
    parser = argparse.ArgumentParser(description="03 生成并下载图片")
    parser.add_argument("--dry-run", action="store_true", help="只预览图片任务，不生成下载模板，不调用 MXAPI。")
    args = parser.parse_args()

    if args.dry_run:
        preview()
        return

    print("\n=== 03-1 生成图片下载入参 ===")
    print_batch_info()
    build_image_input(build_image_input_config_for_batch())

    print("\n=== 03-2 调用 MXAPI 生成并下载图片 ===")
    execution = task_execution()
    config = apply_batch_to_image_config(load_config(GENERATE_IMAGES_CONFIG))
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("image_concurrency", execution.get("concurrency", 1))
    # 副图依赖主图成功：仅当总流程开启主图时启用，避免主图没生成白花副图积分
    if workflow_switches().get("generate_main_image"):
        config.require_success_results_path = str(batch_paths()["main_image_results"])
        print(f"副图依赖主图成功: {config.require_success_results_path}")
    records = run(config)
    success_count = sum(1 for item in records if item.status == "success")
    blocked_count = sum(1 for item in records if item.status == "blocked")
    failed_count = len(records) - success_count - blocked_count

    print("\n=== 03 汇总 ===")
    print(f"图片任务: {len(records)} | 成功: {success_count} | 依赖未满足(跳过): {blocked_count} | 失败: {failed_count}")


def preview() -> None:
    print("\n=== 03 生成并下载图片 | 试运行 ===")
    print("试运行: 不生成下载模板，不调用 MXAPI，不下载图片")
    execution = task_execution()
    config = load_config(GENERATE_IMAGES_CONFIG)
    config = apply_batch_to_image_config(config)
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("image_concurrency", execution.get("concurrency", 1))
    input_path = Path(config.input_excel_path)
    if not input_path.exists():
        print(f"图片入参 Excel 不存在: {input_path}")
        print("请先正式执行 03，或单独运行 build_sub_image_download_input.py 生成图片入参。")
        return

    rows, _, _, _ = load_work_rows(config)
    checkpoint = CheckpointStore(config.checkpoint_path)
    checkpoint_rows = checkpoint.rows()
    rows = apply_checkpoint_to_rows(rows, checkpoint_rows)
    completed = completed_keys(checkpoint_rows) if config.skip_success else set()
    pending = [row for row in rows if row_key(row) not in completed]
    blocked_preview = 0
    if workflow_switches().get("generate_main_image"):
        mp = batch_paths().get("main_image_results")
        if mp and Path(mp).exists():
            success_skus = _load_success_skus(mp)
            kept = [r for r in pending if str(r.get("sku") or "").strip() in success_skus]
            blocked_preview = len(pending) - len(kept)
            pending = kept
    selected = limit_rows_by_sku(pending, config.max_records)

    print(f"图片入参: {input_path}")
    print(f"checkpoint: {config.checkpoint_path}")
    print(
        f"图片任务总数: {len(rows)} 行 / {count_skus(rows)} 个 SKU | "
        f"已成功跳过: {len(completed)} 行 | "
        f"依赖未满足(跳过): {blocked_preview} 行 | "
        f"未成功/待处理: {len(pending)} 行 / {count_skus(pending)} 个 SKU | "
        f"本次将处理: {len(selected)} 行 / {count_skus(selected)} 个 SKU "
        f"(max_records={config.max_records} 个 SKU)"
    )
    if blocked_preview:
        print(f"副图依赖主图成功: 因主图未成功将跳过副图行={blocked_preview}")
    print(f"网关: {config.gateway} | 模型: {config.model} | 并发: {config.concurrency} | max_records: {config.max_records}")
    print(f"下载目录: {config.download_dir}")
    if selected:
        print("样例:")
        for index, row in enumerate(selected[:5], start=1):
            task_id = row.get("task_id") or "无"
            print(f"  [{index}] SKU={row.get('sku')} | 图片={row.get('image_name')} | task_id={task_id}")


if __name__ == "__main__":
    main()
