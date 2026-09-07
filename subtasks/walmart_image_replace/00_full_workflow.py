"""Full Walmart image-replace workflow (real external calls)."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from workflow_common import workflow_switches

TASK_ROOT = Path(__file__).resolve().parent


def run_step(filename: str, dry_run: bool, extra: list[str] | None = None) -> None:
    old = sys.argv[:]
    sys.argv = [filename]
    if dry_run:
        sys.argv.append("--dry-run")
    if extra:
        sys.argv.extend(extra)
    try:
        runpy.run_path(str(TASK_ROOT / filename), run_name="__main__")
    finally:
        sys.argv = old


def main() -> None:
    parser = argparse.ArgumentParser(description="沃尔玛图片替换总流程（真实链路：OSS 探测 / BUZZ 提示词 / MXAPI 生图 / OSS 上传 / 沃尔玛 Feed 提交与对账）")
    parser.add_argument("--dry-run", action="store_true", help="只预览各阶段数据，不调用接口，不写输出。")
    args = parser.parse_args()

    switches = workflow_switches()
    print("\n=== 沃尔玛图片替换总流程 ===")
    if switches["query_existing_images"]:
        run_step("01_query_existing_images.py", args.dry_run)
    else:
        print("跳过 01 查询已有图片")
    if switches["generate_prompts"]:
        run_step("02_generate_prompts.py", args.dry_run)
    else:
        print("跳过 02 生成提示词")
    if switches["generate_images"]:
        run_step("03_generate_images.py", args.dry_run)
    else:
        print("跳过 03 生成图片")
    if switches["upload_oss"]:
        run_step("04_upload_oss.py", args.dry_run)
    else:
        print("跳过 04 上传 OSS")
    if switches["build_replace_result"]:
        run_step("05_build_replace_result.py", args.dry_run)
    else:
        print("跳过 05 组装替换结果")
    if switches["submit_replace"]:
        run_step("06_submit_replace.py", args.dry_run)
    else:
        print("跳过 06 提交沃尔玛 Feed")
    if switches["reconcile"]:
        run_step("07_reconcile.py", args.dry_run)
    else:
        print("跳过 07 对账沃尔玛 Feed")
    if switches["build_report"]:
        run_step("08_build_report.py", args.dry_run)
    else:
        print("跳过 08 生成报告")
    print("\n=== 总流程结束 ===")


if __name__ == "__main__":
    main()
