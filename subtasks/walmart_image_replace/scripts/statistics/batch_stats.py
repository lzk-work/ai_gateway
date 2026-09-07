"""Batch-level progress statistics for the Walmart image-replace workflow."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from workflow_common import batch_name_from_input, batch_paths, load_jsonl  # noqa: E402


def main() -> None:
    paths = batch_paths()
    batch_name = batch_name_from_input()
    print(f"\n=== 批次进度统计: {batch_name} ===")
    print(f"批次目录: {paths['root']}")

    inventory = load_jsonl(paths["inventory"])
    if inventory:
        to_gen = sum(r["to_generate"] for r in inventory)
        print(f"\n[01 查已有图片] SKU {len(inventory)} 条，需生成图 {to_gen} 张")
        by_store = Counter(r["store"] for r in inventory)
        print(f"  分店铺: {dict(by_store)}")

    model_results = load_jsonl(paths["model_results"])
    if model_results:
        total = sum(r.get("to_generate", 0) for r in model_results)
        print(f"[02 生成提示词] OSS 目录 {len(model_results)} 个，提示词 {total} 条")

    images = load_jsonl(paths["image_results"])
    if images:
        ok = sum(1 for r in images if r.get("status") == "success")
        sku_count = len({r.get("sku") for r in images})
        print(f"[03 生成图片] 行级记录 {len(images)} 行 / {sku_count} 个 OSS 目录（success {ok}）")

    oss = load_jsonl(paths["oss_results"])
    if oss:
        ok = sum(1 for r in oss if r.get("status") in ("success", "skipped"))
        sku_count = len({r.get("sku") for r in oss})
        print(f"[04 上传 OSS] 行级记录 {len(oss)} 行 / {sku_count} 个 OSS 目录（success/skipped {ok}）")

    payloads = load_jsonl(paths["payload"])
    if payloads:
        complete = sum(1 for r in payloads if r.get("complete"))
        print(f"[05 组装结果] SKU {len(payloads)} 条，complete {complete} 条")

    submits = load_jsonl(paths["submit_results"])
    if submits:
        ok = sum(1 for r in submits if r.get("status") in ("submitted", "success", "processed"))
        feeds = {r.get("feed_id") for r in submits if r.get("feed_id")}
        print(f"[06 沃尔玛提交] {len(submits)} 行（成功提交 {ok}）| feedId {len(feeds)} 个")
    else:
        print("[06 沃尔玛提交] 未运行")

    reconciles = load_jsonl(paths["reconcile_results"])
    if reconciles:
        dist = Counter(r.get("status") for r in reconciles)
        print(f"[07 沃尔玛对账] {len(reconciles)} 行，状态分布: {dict(dist)}")
    else:
        print("[07 沃尔玛对账] 未运行")

    if paths["report"].exists():
        report = load_jsonl(paths["report"])
        status = Counter(r.get("status") for r in report)
        print(f"[08 结果报告] 行 {len(report)} 条，状态分布: {dict(status)}")
        print(f"  报告文件: {paths['report_xlsx']}")
    else:
        print("[08 结果报告] 未生成")


if __name__ == "__main__":
    main()
