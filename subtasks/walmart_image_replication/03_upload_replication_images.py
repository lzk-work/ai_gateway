from __future__ import annotations

from workflow_common import UPLOAD_CONFIG, load_task_config, upload_config_data
import argparse

from ai_gateway.subtasks.oss_upload_images import load_config, preview, run


def main() -> None:
    parser = argparse.ArgumentParser(description="03 上传复刻图片到 OSS")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_config(UPLOAD_CONFIG, config_data=upload_config_data())
    task = load_task_config()
    cfg.max_records = task.get("execution", {}).get("max_records")
    cfg.concurrency = int(task.get("execution", {}).get("oss_concurrency", 1))
    if args.dry_run:
        preview(cfg)
    else:
        records = run(cfg)
        print(f"本轮上传={len(records)} | 成功/跳过={sum(r.status in {'success', 'skipped'} for r in records)}")


if __name__ == "__main__":
    main()
