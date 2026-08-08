"""Full Walmart image-prompt workflow.

Default behavior follows config.json workflow switches. Image generation is disabled
by default because it consumes image-generation credits.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from workflow_common import workflow_switches
from scripts.statistics.batch_stats import print_batch_stats

TASK_ROOT = Path(__file__).resolve().parent


def run_step(filename: str, dry_run: bool) -> None:
    old_argv = sys.argv[:]
    sys.argv = [filename]
    if dry_run:
        sys.argv.append("--dry-run")
        if filename == "02_call_buzz_model.py":
            sys.argv.append("--preview-current-excel")
    try:
        runpy.run_path(str(TASK_ROOT / filename), run_name="__main__")
    finally:
        sys.argv = old_argv


def main() -> None:
    parser = argparse.ArgumentParser(description="Walmart 图片业务总流程")
    parser.add_argument("--dry-run", action="store_true", help="只预览各阶段将要处理的数据，不调用接口，不写输出。")
    args = parser.parse_args()

    switches = workflow_switches()
    print("\n=== Walmart 图片业务总流程 ===")
    if args.dry_run:
        print("运行模式: 试运行，只预览，不调用接口，不写输出")
    print(
        "阶段开关: "
        f"01={switches['generate_prompt_tasks']} | "
        f"02={switches['call_buzz_model']} | "
        f"03={switches['generate_and_download_images']} | "
        f"05={switches['upload_oss']} | "
        f"06={switches['build_final_result']}"
    )

    if switches["generate_prompt_tasks"]:
        run_step("01_generate_prompt_tasks.py", args.dry_run)
    else:
        print("跳过 01 生成提示词任务")

    if switches["call_buzz_model"]:
        run_step("02_call_buzz_model.py", args.dry_run)
    else:
        print("跳过 02 调用 BUZZ 模型")

    if switches["generate_and_download_images"]:
        run_step("03_generate_and_download_images.py", args.dry_run)
    else:
        print("跳过 03 生成并下载图片。如需开启，在 config.json 的 workflow.generate_and_download_images 改为 true。")

    if switches["upload_oss"]:
        run_step("05_upload_oss.py", args.dry_run)
    else:
        print("跳过 05 上传 OSS。如需开启，在 config.json 的 workflow.upload_oss 改为 true。")

    if switches["build_final_result"]:
        run_step("06_build_final_image_result.py", args.dry_run)
    else:
        print("跳过 06 生成最终图片结果表。如需开启，在 config.json 的 workflow.build_final_result 改为 true。")

    print_batch_stats()
    print("\n=== 总流程结束 ===")


if __name__ == "__main__":
    main()
