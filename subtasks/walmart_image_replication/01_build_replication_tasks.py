from __future__ import annotations

import argparse
from pathlib import Path

from scripts.build_replication_input import build, preview
from workflow_common import TASK_ROOT, load_task_config, paths, print_batch_info


def main() -> None:
    parser = argparse.ArgumentParser(description="01 构建图片复刻任务")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = load_task_config()
    print("\n=== 01 构建图片复刻任务 ===")
    print_batch_info()
    print(f"输入: {cfg['input']['excel_path']}")
    print("参考图顺序: 1=产品主图，2=对应原副图")
    if args.dry_run:
        summary = preview(cfg)
        print(
            f"源SKU={summary['source_skus']} | 主图任务={summary['main_rows']} | "
            f"副图任务={summary['sub_rows']} | 总任务={summary['generated_rows']} | "
            f"缺少主图SKU={summary['missing_main_skus']}"
        )
        if summary["samples"]:
            print("任务样例:")
            for item in summary["samples"]:
                print(
                    f"  SKU={item['sku']} | 图片={item['image_name']} | "
                    f"参考图={item['reference_count']}张"
                )
        print("试运行: 未写入任务 Excel")
        return
    summary = build(
        cfg,
        paths()["image_input"],
        TASK_ROOT / "prompts" / "walmart_image_replication_prompt.txt",
        TASK_ROOT / "prompts" / "main_image_optimization_prompt.txt",
    )
    print(
        f"源SKU={summary['source_skus']} | 主图任务={summary['main_rows']} | "
        f"副图任务={summary['sub_rows']} | 总任务={summary['generated_rows']} | "
        f"缺少主图SKU={summary['missing_main_skus']}"
    )
    print(f"输出: {paths()['image_input']}")


if __name__ == "__main__":
    main()
