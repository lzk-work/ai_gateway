"""Step 04: Upload generated images in the current batch to Aliyun OSS.

与 walmart_image_prompt 的 05_upload_oss.py 同一逻辑：复用共享模块
ai_gateway.subtasks.oss_upload_images（行级 checkpoint、幂等续跑、并发上传）。
OSS key = key_template 渲染（{sku}=OSS路径，{image_name}=不含扩展名的文件名）。
"""

from __future__ import annotations

import argparse
import json

from workflow_common import (
    STAGE_CONFIGS,
    apply_batch_to_oss_config,
    batch_paths,
    load_jsonl,
    load_stage_config,
    print_batch_info,
    task_execution,
)


def render_key(key_template: str, sku: str, image_name: str) -> str:
    return (
        key_template.replace("{sku}", sku).replace("{image_name}", image_name)
        .replace("\\", "/").lstrip("/")
    )


def preview(batch_name: str | None) -> None:
    print("\n=== 04 上传 OSS | 试运行 ===")
    print("试运行: 不连接 OSS，不上传，不写 JSONL/Excel")
    paths = batch_paths(batch_name)
    rows = load_jsonl(paths["image_results"])
    success = [r for r in rows if r.get("status") == "success"]
    sku_count = len({r.get("sku") for r in success})
    print(f"生成结果: {len(rows)} 行 | 成功: {len(success)} 行 / {sku_count} 个 OSS 目录")
    key_template = load_stage_config("upload_oss").get("oss", {}).get("key_template", "{sku}/{image_name}.png")
    print(f"key_template: {key_template}")
    for row in success[:5]:
        print(f"  SKU={row.get('sku')} | 图片={row.get('image_name')} | OSS={render_key(key_template, row.get('sku', ''), row.get('image_name', ''))}")


def main() -> None:
    parser = argparse.ArgumentParser(description="04 上传 OSS")
    parser.add_argument("--dry-run", action="store_true", help="只预览 OSS 上传任务，不连接 OSS，不上传。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 04 上传 OSS ===")
    print_batch_info(args.batch_name)

    if args.dry_run:
        preview(args.batch_name)
        return

    from ai_gateway.subtasks.oss_upload_images import load_config, run

    execution = task_execution()
    config = apply_batch_to_oss_config(load_config(STAGE_CONFIGS["upload_oss"]), args.batch_name)
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("oss_concurrency", execution.get("concurrency", 1))
    config.batch_size = execution.get("oss_batch_size", config.batch_size)

    records = run(config)
    success_count = sum(1 for item in records if item.status in {"success", "skipped"})
    print("\n=== 04 汇总 ===")
    print(f"OSS上传: {len(records)} | 成功/跳过: {success_count} | 失败: {len(records) - success_count}")


if __name__ == "__main__":
    main()
