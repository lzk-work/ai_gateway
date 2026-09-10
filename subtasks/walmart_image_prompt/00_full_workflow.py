"""Full Walmart image workflow controlled by ``config.json`` stage switches."""

from __future__ import annotations

import argparse
import runpy
import sys
import time
from pathlib import Path

from workflow_common import workflow_switches, check_image_provider, load_task_config
from scripts.execution_confirmation import print_execution_confirmation
from scripts.statistics.batch_stats import collect_stats, print_batch_stats

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


def run_cycle(dry_run: bool) -> dict:
    switches = workflow_switches()
    if switches["generate_main_image"] or switches["generate_and_download_images"]:
        check_image_provider(bind=not dry_run)
    stages = [
        ("generate_prompt_tasks", "01_generate_prompt_tasks.py", "01 生成提示词任务"),
        ("call_buzz_model", "02_call_buzz_model.py", "02 调用 BUZZ 模型"),
        ("generate_main_image", "03b_generate_main_images.py", "03b 生成/查询主图"),
        ("generate_and_download_images", "03_generate_and_download_images.py", "03 生成/查询副图"),
        ("upload_main_image", "05b_upload_main_oss.py", "05b 上传主图 OSS"),
        ("upload_oss", "05_upload_oss.py", "05 上传副图 OSS"),
        ("build_final_result", "06_build_final_image_result.py", "06 生成最终图片结果表"),
    ]
    stage_errors: list[str] = []
    for switch, filename, label in stages:
        if switches[switch]:
            try:
                run_step(filename, dry_run)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                message = f"{label}异常: {exc.__class__.__name__}: {exc}"
                stage_errors.append(message)
                print(f"[本轮阶段失败，继续后续阶段] {message}", flush=True)
        else:
            print(f"跳过 {label}")
    print_batch_stats()
    stats = collect_stats()
    stats["stage_errors"] = stage_errors
    return stats


def cycle_is_complete(stats: dict) -> bool:
    return (
        not stats.get("stage_errors")
        and stats.get("model_pending_skus", 0) == 0
        and stats.get("model_retryable_skus", stats.get("model_failed_skus", 0)) == 0
        and stats.get("image_pending_count", 0) == 0
        and stats.get("upload_pending_count", 0) == 0
        and stats.get("final_result_complete_sku_count", 0) >= stats.get("model_valid_skus", 0)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Walmart 图片业务总流程")
    parser.add_argument("--dry-run", action="store_true", help="只预览各阶段将要处理的数据，不调用接口，不写输出。")
    parser.add_argument("--once", action="store_true", help="只执行一轮，不按 scheduler 配置等待续跑。")
    args = parser.parse_args()

    print("\n=== Walmart 图片业务总流程 ===")
    if not print_execution_confirmation(args.dry_run):
        return

    scheduler = load_task_config().get("scheduler", {})
    interval = int(scheduler.get("interval_seconds", 10800))
    if interval <= 0:
        raise ValueError("scheduler.interval_seconds 必须大于 0")
    max_cycles = scheduler.get("max_cycles")
    max_cycles = int(max_cycles) if max_cycles is not None else None
    cycle = 0
    while True:
        cycle += 1
        print(f"\n=== 执行第 {cycle} 轮 ===")
        stats = run_cycle(args.dry_run)
        if args.dry_run or args.once or not bool(scheduler.get("enabled", False)):
            break
        if bool(scheduler.get("stop_when_complete", True)) and cycle_is_complete(stats):
            print("全部任务已完成，停止周期续跑。")
            break
        if max_cycles is not None and cycle >= max_cycles:
            print(f"已达到 scheduler.max_cycles={max_cycles}，停止周期续跑。")
            break
        print(f"本轮结束，{interval} 秒后从 01 阶段开始下一轮；按 Ctrl+C 可安全停止。", flush=True)
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n收到中断，已在两轮之间安全停止。")
            break
    print("\n=== 总流程结束 ===")


if __name__ == "__main__":
    main()
