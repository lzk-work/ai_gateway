"""Step 07: 对账沃尔玛 Feed，确认图片替换是否真实生效。

读取 06 的 submit_results.jsonl，按 (店铺, feed_id) 分组，轮询沃尔玛：
  1. GET /v3/feeds/{feedId}          → feedStatus（INPROGRESS/PROCESSED/...）
  2. GET /v3/feeds/{feedId}/items    → 每 SKU 的 ingestionStatus（SUCCESS/DATA_ERROR/...）+ 错误明细
按 SKU 聚合写出 reconcile_results.jsonl：
  status ∈ success(沃尔玛已接受) / failed(沃尔玛拒绝) / in_progress(仍在处理，稍后重跑 07)

--dry-run：完全不触网、不写文件。仅列出待对账的 feedId 与 SKU 映射、轮询参数，用于离线逻辑测试。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from workflow_common import (  # noqa: E402
    batch_paths,
    ensure_dirs,
    load_jsonl,
    load_task_config,
    print_batch_info,
    walmart_stores,
    walmart_store_credentials,
)
from scripts.walmart_feed import StoreCreds, WalmartClient  # noqa: E402

# ingestionStatus → 本地状态
STATUS_MAP = {
    "SUCCESS": "success",
    "ACCEPTED": "success",
    "DATA_ERROR": "failed",
    "SYSTEM_ERROR": "failed",
    "PARTIAL_SUCCESS": "failed",
}


def derive_status(ingestion_status: str) -> str:
    return STATUS_MAP.get(ingestion_status, "in_progress")


def group_feeds(submit_rows: list[dict]) -> dict[tuple, list[dict]]:
    """按 (store, feed_id) 分组提交记录（feed_id 为空的 error 行不参与对账）。"""
    groups: dict[tuple, list[dict]] = {}
    for r in submit_rows:
        feed_id = str(r.get("feed_id", "") or "")
        if not feed_id:
            continue
        groups.setdefault((r.get("store", ""), feed_id), []).append(r)
    return groups


def build_client(store: str, stores: dict, token_cfg: dict) -> WalmartClient | None:
    store_cfg = stores.get(store)
    if not store_cfg:
        print(f"店铺 {store} 不在配置，跳过对账")
        return None
    raw = walmart_store_credentials(store)
    creds = StoreCreds(
        store_key=store,
        base_url=store_cfg.get("base_url", "https://marketplace.walmartapis.com"),
        client_id=raw.get("client_id"),
        client_secret=raw.get("client_secret"),
    )
    if not creds.ready():
        print(f"店铺 {store} 缺少 Walmart 凭证，跳过对账")
        return None
    return WalmartClient(
        creds,
        token_endpoint=token_cfg.get("token_endpoint", "/v3/token"),
        feed_endpoint=token_cfg.get("feed_endpoint", "/v3/feeds"),
        token_cache_seconds=int(token_cfg.get("token_cache_seconds", 900)),
    )


def poll_feed(client: WalmartClient, feed_id: str, max_attempts: int, interval: int) -> dict:
    """轮询 feed 状态直到 PROCESSED 或超过次数。"""
    status: dict[str, Any] = {}
    for attempt in range(1, max_attempts + 1):
        status = client.get_feed_status(feed_id)
        feed_status = str(status.get("feedStatus") or "")
        print(f"    第 {attempt}/{max_attempts} 次查询: feedStatus={feed_status}")
        if feed_status == "PROCESSED":
            return status
        if attempt < max_attempts:
            time.sleep(interval)
    return status


def reconcile_one(client: WalmartClient, feed_id: str, skus: list[dict],
                  max_attempts: int, interval: int) -> list[dict]:
    """对账单个 feed：先轮询状态，PROCESSED 后取明细，按 SKU 输出行。"""
    status = poll_feed(client, feed_id, max_attempts, interval)
    feed_status = str(status.get("feedStatus") or "")
    now = datetime.now().isoformat(timespec="seconds")

    if feed_status != "PROCESSED":
        # 仍在处理或状态异常：全部标记 in_progress，等下次重跑 07
        return [{
            "store": s.get("store", ""), "sku": s.get("sku", ""), "gtin": s.get("gtin", ""),
            "feed_id": feed_id, "feed_status": feed_status,
            "status": "in_progress", "walmart_status": "",
            "errors": status.get("ingestionErrors", []), "reconciled_at": now,
        } for s in skus]

    items = client.get_feed_items(feed_id)
    by_sku: dict[str, dict] = {}
    for it in items:
        if it.get("sku"):
            by_sku[it["sku"]] = it

    rows = []
    for s in skus:
        sku = s.get("sku", "")
        it = by_sku.get(sku)
        if it is None:
            rows.append({
                "store": s.get("store", ""), "sku": sku, "gtin": s.get("gtin", ""),
                "feed_id": feed_id, "feed_status": feed_status,
                "status": "in_progress", "walmart_status": "NOT_FOUND_IN_FEED",
                "errors": [{"code": "ITEM_NOT_FOUND",
                            "description": "feed 已处理但明细中未找到该 SKU，请稍后重跑 07 对账"}],
                "reconciled_at": now,
            })
            continue
        wstatus = str(it.get("ingestionStatus") or "")
        rows.append({
            "store": s.get("store", ""), "sku": sku, "gtin": s.get("gtin", ""),
            "feed_id": feed_id, "feed_status": feed_status,
            "status": derive_status(wstatus), "walmart_status": wstatus,
            "errors": it.get("errors", []), "reconciled_at": now,
        })
    return rows


def preview(groups: dict, token_cfg: dict, poll_cfg: dict) -> None:
    print("\n=== 07 对账沃尔玛 Feed | 试运行（不触网、不写文件）===")
    if not groups:
        print("无可对账的 feed（submit_results 为空或全部为 error 行）。")
        return
    interval = int(poll_cfg.get("interval_seconds", 30))
    max_attempts = int(poll_cfg.get("max_attempts", 20))
    print(f"轮询参数: 每 {interval} 秒一次，最多 {max_attempts} 次（可改 config.json feed.poll）")
    for (store, feed_id), rows in groups.items():
        print(f"\n--- 店铺 {store} | feedId={feed_id} | {len(rows)} 个 SKU ---")
        for r in rows:
            print(f"    SKU={r.get('sku')}（status={r.get('status')}）")
        print("    将依次: GET /v3/feeds/{feedId} 轮询至 PROCESSED → GET /v3/feeds/{feedId}/items 按 SKU 取 ingestionStatus")


def main() -> None:
    parser = argparse.ArgumentParser(description="07 对账沃尔玛 Feed 替换结果（真实 API）")
    parser.add_argument("--dry-run", action="store_true", help="只列出待对账 feed，不触网、不写文件。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 07 对账沃尔玛 Feed 替换结果 ===")
    print_batch_info(args.batch_name)
    paths = ensure_dirs(args.batch_name)

    if not paths["submit_results"].exists():
        msg = "未找到 submit_results.jsonl，请先运行 06"
        if args.dry_run:
            print(msg + "（dry-run 跳过）")
            return
        raise SystemExit(msg)

    submit_rows = load_jsonl(paths["submit_results"])
    groups = group_feeds(submit_rows)
    stores = walmart_stores()
    token_cfg = load_task_config().get("walmart_api", {})
    poll_cfg = load_task_config().get("feed", {}).get("poll", {})

    if args.dry_run:
        preview(groups, token_cfg, poll_cfg)
        return

    max_attempts = int(poll_cfg.get("max_attempts", 20))
    interval = int(poll_cfg.get("interval_seconds", 30))

    all_rows: list[dict[str, Any]] = []
    for (store, feed_id), rows in groups.items():
        print(f"\n--- 对账 feedId={feed_id}（店铺 {store}，{len(rows)} 个 SKU）---")
        client = build_client(store, stores, token_cfg)
        if client is None:
            for r in rows:
                all_rows.append({
                    "store": store, "sku": r.get("sku", ""), "gtin": r.get("gtin", ""),
                    "feed_id": feed_id, "feed_status": "",
                    "status": "error", "walmart_status": "",
                    "errors": [{"description": "店铺缺少凭证或配置，无法对账"}],
                    "reconciled_at": datetime.now().isoformat(timespec="seconds"),
                })
            continue
        try:
            all_rows.extend(reconcile_one(client, feed_id, rows, max_attempts, interval))
        except RuntimeError as e:
            print(f"    对账失败: {e}")
            for r in rows:
                all_rows.append({
                    "store": store, "sku": r.get("sku", ""), "gtin": r.get("gtin", ""),
                    "feed_id": feed_id, "feed_status": "",
                    "status": "error", "walmart_status": "",
                    "errors": [{"description": str(e)}],
                    "reconciled_at": datetime.now().isoformat(timespec="seconds"),
                })

    with open(paths["reconcile_results"], "w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    counter = Counter(r["status"] for r in all_rows)
    print(f"\n07 完成：{len(all_rows)} 行 -> {paths['reconcile_results']} | 状态分布: {dict(counter)}")
    print("提示：in_progress 可稍后重跑 07；failed 的 SKU 请核对 errors 字段（沃尔玛侧拒绝原因）。")


if __name__ == "__main__":
    main()
