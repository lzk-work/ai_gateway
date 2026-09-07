"""Step 03: Build image input workbook, generate images with MXAPI, and download files.

与 walmart_image_prompt 的 03_generate_and_download_images.py 同一逻辑：
  03-1 scripts/build_image_input.py  按「缺失位置」动态展开图片入参 Excel（行数不固定）
  03-2 ai_gateway.subtasks.mxapi_generate_images  复用共享模块调 MXAPI + checkpoint 续跑 + 下载

区别：walmart_image_prompt 每个 SKU 固定生成 image_count 张；本任务按阶段 01
算出的缺失位置生成（每个 OSS 目录 = 一个图片任务组，SKU 列 = OSS路径）。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from workflow_common import (
    STAGE_CONFIGS,
    apply_batch_to_image_config,
    batch_paths,
    load_jsonl,
    print_batch_info,
    task_execution,
)

from scripts.build_image_input import run as build_image_input  # noqa: E402


def preview(batch_name: str | None) -> None:
    print("\n=== 03 生成图片 | 试运行 ===")
    print("试运行: 不生成图片入参，不调用 MXAPI，不下载图片")
    paths = batch_paths(batch_name)
    inventory = load_jsonl(paths["inventory"])
    if not inventory:
        print("未找到 image_inventory.jsonl，请先运行 01。")
        return
    seen: set[str] = set()
    total = 0
    for rec in inventory:
        oss_path = str(rec.get("oss_image_path", "")).strip()
        if not oss_path or oss_path in seen:
            continue
        seen.add(oss_path)
        total += len(rec.get("missing_positions", []))
    print(f"图片任务: {len(seen)} 个 OSS 目录 / {total} 行（按缺失位置动态展开）")
    print(f"checkpoint: {paths['image_checkpoint']}")
    execution = task_execution()
    print(f"max_records: {execution.get('max_records')} | 并发(image_concurrency): {execution.get('image_concurrency', execution.get('concurrency', 1))}")
    print(f"下载目录: {paths['download_dir']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="03 生成并下载图片")
    parser.add_argument("--dry-run", action="store_true", help="只预览图片任务，不生成入参，不调用 MXAPI。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    if args.dry_run:
        preview(args.batch_name)
        return

    print("\n=== 03-1 生成图片入参（按缺失位置动态展开）===")
    print_batch_info(args.batch_name)
    build_image_input(args.batch_name)

    print("\n=== 03-2 调用 MXAPI 生成并下载图片 ===")
    from ai_gateway.subtasks.mxapi_generate_images import load_config, run

    execution = task_execution()
    config = apply_batch_to_image_config(load_config(STAGE_CONFIGS["generate_images"]))
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("image_concurrency", execution.get("concurrency", 1))
    records = run(config)
    success_count = sum(1 for item in records if item.status == "success")

    print("\n=== 03 汇总 ===")
    print(f"图片任务: {len(records)} | 成功: {success_count} | 失败: {len(records) - success_count}")


if __name__ == "__main__":
    main()
