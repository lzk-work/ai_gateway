"""Step 05: Upload generated images in the current batch to Aliyun OSS."""

from __future__ import annotations

import argparse

from workflow_common import UPLOAD_OSS_CONFIG, apply_batch_to_oss_config, print_batch_info, task_execution

from ai_gateway.subtasks.oss_upload_images import load_config, preview, run


def main() -> None:
    parser = argparse.ArgumentParser(description="05 上传 OSS")
    parser.add_argument("--dry-run", action="store_true", help="只预览 OSS 上传任务，不连接 OSS，不上传。")
    parser.add_argument("--batch-name", default=None, help="手动指定批次名；不填则按入参 Excel 文件名确定。")
    args = parser.parse_args()

    print("\n=== 05 上传 OSS ===")
    print_batch_info(args.batch_name)
    execution = task_execution()
    config = apply_batch_to_oss_config(load_config(UPLOAD_OSS_CONFIG), args.batch_name)
    config.max_records = execution.get("max_records")
    config.concurrency = execution.get("oss_concurrency", execution.get("concurrency", 1))
    config.batch_size = execution.get("oss_batch_size", config.batch_size)

    if args.dry_run:
        preview(config)
        return

    records = run(config)
    success_count = sum(1 for item in records if item.status in {"success", "skipped"})
    print("\n=== 05 汇总 ===")
    print(f"OSS上传: {len(records)} | 成功/跳过: {success_count} | 失败: {len(records) - success_count}")


if __name__ == "__main__":
    main()
