from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_ROOT.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ai_gateway.text_to_text.config import load_task
from ai_gateway.text_to_text.engine import TextBatchEngine, make_batch_id


def latest_batch(task_root: Path) -> str | None:
    root = task_root / "batches"
    candidates = sorted((item for item in root.iterdir() if item.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
    return candidates[0].name if candidates else None


def main() -> None:
    parser = argparse.ArgumentParser(description="通用 Excel 文本输入 → 兔子 API → 文本输出")
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--input")
    parser.add_argument("--batch-id")
    parser.add_argument("--latest", action="store_true", help="使用该任务最近批次")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="在同一批次中重试全部失败记录，成功记录不会重跑",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-records", type=int)
    args = parser.parse_args()
    tasks_root = TASK_ROOT / "tasks"
    if args.list_tasks:
        for item in sorted(tasks_root.iterdir()):
            if (item / "task.json").exists():
                print(item.name)
        return
    if not args.task:
        parser.error("需要 --task")
    task = load_task(tasks_root, args.task)
    batch_id = args.batch_id or (latest_batch(task.root) if args.latest else None) or make_batch_id(task.name)
    engine = TextBatchEngine(PROJECT_ROOT, TASK_ROOT, task, batch_id)
    source = Path(args.input) if args.input else None
    if source is None and engine.paths.manifest.exists():
        source = Path(json.loads(engine.paths.manifest.read_text(encoding="utf-8"))["source_path"])
    if source is None and task.input.get("default_path"):
        source = task.root / str(task.input["default_path"])
    if source is None:
        parser.error("新批次需要 --input；续跑可使用 --batch-id 或 --latest")
    summary = engine.dry_run(source) if args.dry_run else engine.run(
        source,
        max_records=args.max_records,
        retry_failed=args.retry_failed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
