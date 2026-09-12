from __future__ import annotations

from workflow_common import GENERATE_CONFIG, generation_config_data, image_provider, load_task_config, paths, print_batch_info
import argparse

from ai_gateway.clients.image_batch import check_batch_provider
from ai_gateway.subtasks.mxapi_generate_images import (
    CheckpointStore, apply_checkpoint_to_rows, completed_keys, count_skus,
    load_config, load_work_rows, row_key, run,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="02 生成或查询复刻图片")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("\n=== 02 生成或查询复刻图片 ===")
    print_batch_info()
    check_batch_provider(paths()["root"], image_provider(), bind=not args.dry_run)
    cfg = load_config(GENERATE_CONFIG, config_data=generation_config_data())
    task = load_task_config()
    cfg.provider = image_provider()
    cfg.gateway = cfg.provider
    cfg.max_records = task.get("execution", {}).get("max_records")
    cfg.concurrency = int(task.get("execution", {}).get("image_concurrency", 1))
    cfg.desired_count = 1 + max(int(task.get("image_generation", {}).get("max_sub_images", 5)), 0)
    cfg.max_regenerations_per_image = int(task.get("image_generation", {}).get("max_regenerations_per_image", 2))
    cfg.generate_main_images = bool(task.get("image_generation", {}).get("generate_main_images", True))
    cfg.generate_sub_images = bool(task.get("image_generation", {}).get("generate_sub_images", True))
    if not cfg.generate_main_images and not cfg.generate_sub_images:
        print("主图和副图生成均已关闭，本阶段不调用图片接口。")
    if args.dry_run:
        input_path = paths()["image_input"]
        print(f"平台={cfg.provider} | 模型={cfg.model} | 并发={cfg.concurrency}")
        if not input_path.exists():
            print(f"任务 Excel 尚未生成: {input_path}")
            print("01阶段已预览源数据；正式运行时会先生成任务 Excel。")
            return
        rows, workbook, _, _ = load_work_rows(cfg)
        try:
            saved = CheckpointStore(cfg.checkpoint_path, cfg.provider).rows()
            enriched = apply_checkpoint_to_rows(rows, saved)
            done = completed_keys(saved, cfg.max_regenerations_per_image) if cfg.skip_success else set()
            active = [
                row for row in enriched
                if (cfg.generate_main_images if row["image_name"].startswith("new_main_") else cfg.generate_sub_images)
            ]
            pending = [row for row in active if row_key(row) not in done]
            submitted = sum(1 for row in pending if row.get("task_id"))
            new = len(pending) - submitted
            print(
                f"生成开关: 主图={'开' if cfg.generate_main_images else '关'} | "
                f"副图={'开' if cfg.generate_sub_images else '关'}"
            )
            print(
                f"全部任务={len(rows)}行/{count_skus(rows)}个SKU | 本次启用={len(active)}行 | "
                f"关闭类型不处理={len(rows)-len(active)}行 | 已成功跳过={len(active)-len(pending)} | "
                f"待查询已有task_id={submitted} | 待提交新任务={new}"
            )
            for row in pending[:5]:
                refs = row.get("reference_image") or []
                ref_count = len(refs) if isinstance(refs, list) else 1
                action = "查询" if row.get("task_id") else "提交"
                print(f"  {action} | SKU={row['sku']} | 图片={row['image_name']} | 参考图={ref_count}张")
        finally:
            workbook.close()
        print("试运行: 未调用接口、未下载图片、未写结果")
        return
    records = run(cfg)
    counts = {status: sum(r.status == status for r in records) for status in {r.status for r in records}}
    print(f"本轮结果: {counts}")


if __name__ == "__main__":
    main()
