"""Step 06: 提交沃尔玛 item Feed，真实替换商品图片。

读取 05 的 replace_payload.jsonl，按店铺分组，为每张「完整(complete)」SKU 构造 MPItemFeed XML
（AdditionalProductAttributes/ImageUrls：MainImageUrl + 顺序 AlternateImageUrl），
调用沃尔玛 /v3/feeds?feedType=item 真实提交，记录 feedId 到 submit_results.jsonl（行级 checkpoint）。

安全约束：
- 仅提交 complete=True 且 store 在配置内且有主图的 SKU。不完整（缺图）的 SKU 跳过，
  因为沃尔玛图片属性为全量替换，提交不完整集合会丢失已有副图。
- 已成功提交（checkpoint 中存在非失败状态）的 SKU 跳过，支持幂等续跑；
  失败状态的 SKU 允许重提。

--dry-run：完全不触网、不写文件。仅按店铺分组、构造并打印将发送的 XML、列出将提交的 SKU，
  用于离线逻辑测试。
"""

from __future__ import annotations

import argparse
import json
import sys
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
    resolve_store_key,
)
from scripts.walmart_feed import (  # noqa: E402
    StoreCreds,
    WalmartClient,
    build_item_feed_xml,
)


def build_item_dict(rec: dict[str, Any]) -> dict[str, Any]:
    """把 05 payload 一行转成 feed XML 所需的图片结构。"""
    return {
        "sku": rec["platform_sku"],
        "gtin": rec.get("gtin", ""),
        "main_url": rec.get("main_image_url", ""),
        "alt_urls": rec.get("secondary_urls", []) or [],
    }


def group_eligible(payloads: list[dict], stores: dict, done_set: set) -> tuple[dict, list]:
    """按店铺分组可提交 SKU，并返回跳过的 (sku, reason) 列表。"""
    groups: dict[str, list[dict]] = {}
    skipped: list[tuple[str, str]] = []
    for rec in payloads:
        sku = rec.get("platform_sku", "")
        store = rec.get("store", "")
        if not rec.get("complete"):
            skipped.append((sku, "图片不完整(complete=False)，跳过以免丢失已有副图"))
            continue
        if not rec.get("main_image_url"):
            skipped.append((sku, "缺少主图，跳过"))
            continue
        if store not in stores:
            skipped.append((sku, f"店铺 {store} 不在 walmart_api.stores 配置，跳过"))
            continue
        if (store, sku) in done_set:
            skipped.append((sku, "已在 checkpoint 中成功提交，跳过"))
            continue
        groups.setdefault(store, []).append(build_item_dict(rec))
    return groups, skipped


def load_done_set(results_path: Path) -> set:
    done = set()
    for r in load_jsonl(results_path):
        status = r.get("status", "")
        # 失败状态允许重提；只有成功/已提交/已处理才跳过
        if status in ("submitted", "success", "processed"):
            done.add((r.get("store", ""), r.get("sku", "")))
    return done


def preview(groups: dict, skipped: list, token_cfg: dict) -> None:
    print("\n=== 06 提交沃尔玛 Feed | 试运行（不触网、不写文件）===")
    if not groups:
        print("无符合条件（完整+有主图+店铺在配置）的 SKU 可提交。")
    for store, items in groups.items():
        req_id = f"wm_img_{store}_preview"
        xml = build_item_feed_xml(items, req_id)
        print(f"\n--- 店铺 {store}：将提交 {len(items)} 个 SKU，Feed XML {len(xml)} 字节 ---")
        for it in items:
            print(f"    SKU={it['sku']} | 主图={it['main_url']} | 副图数={len(it['alt_urls'])}")
        # 打印 XML 头部便于肉眼核对结构（截断避免刷屏）
        snippet = xml.decode("utf-8")
        if len(snippet) > 1200:
            snippet = snippet[:1200] + "\n... (XML 已截断) ..."
        print("    Feed XML 预览：")
        for line in snippet.splitlines():
            print(f"      {line}")
    if skipped:
        print("\n--- 跳过（不提交）---")
        for sku, reason in skipped:
            print(f"    {sku}: {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="06 提交沃尔玛 Feed 替换图片（真实 API）")
    parser.add_argument("--dry-run", action="store_true", help="只预览将要发送的 Feed XML，不触网、不写文件。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 06 提交沃尔玛 Feed 替换图片 ===")
    print_batch_info(args.batch_name)
    paths = ensure_dirs(args.batch_name)

    if not paths["payload"].exists():
        msg = "未找到 replace_payload.jsonl，请先运行 05"
        if args.dry_run:
            print(msg + "（dry-run 跳过）")
            return
        raise SystemExit(msg)

    payloads = load_jsonl(paths["payload"])
    stores = walmart_stores()
    token_cfg = load_task_config().get("walmart_api", {})
    done_set = load_done_set(paths["submit_results"]) if paths["submit_results"].exists() else set()
    groups, skipped = group_eligible(payloads, stores, done_set)

    if args.dry_run:
        preview(groups, skipped, token_cfg)
        return

    # 真实提交
    new_rows: list[dict[str, Any]] = []
    for store, items in groups.items():
        store_cfg = stores[store]
        creds_raw = walmart_store_credentials(store)
        creds = StoreCreds(
            store_key=store,
            base_url=store_cfg.get("base_url", "https://marketplace.walmartapis.com"),
            client_id=creds_raw.get("client_id"),
            client_secret=creds_raw.get("client_secret"),
        )
        if not creds.ready():
            for it in items:
                new_rows.append({
                    "store": store, "sku": it["sku"], "gtin": it["gtin"],
                    "feed_id": "", "status": "error",
                    "error": "缺少 Walmart 凭证（local.env 未配置 client_id/client_secret）",
                    "submitted_at": "",
                })
            print(f"店铺 {store}: 缺少凭证，跳过 {len(items)} 个 SKU")
            continue
        client = WalmartClient(
            creds,
            token_endpoint=token_cfg.get("token_endpoint", "/v3/token"),
            feed_endpoint=token_cfg.get("feed_endpoint", "/v3/feeds"),
            token_cache_seconds=int(token_cfg.get("token_cache_seconds", 900)),
        )
        req_id = f"wm_img_{store}_{Path(__file__).stem}"
        try:
            xml = build_item_feed_xml(items, req_id)
            feed_id = client.submit_item_feed(xml)
        except RuntimeError as e:
            for it in items:
                new_rows.append({
                    "store": store, "sku": it["sku"], "gtin": it["gtin"],
                    "feed_id": "", "status": "error",
                    "error": str(e), "submitted_at": "",
                })
            print(f"店铺 {store}: 提交失败 - {e}")
            continue
        for it in items:
            new_rows.append({
                "store": store, "sku": it["sku"], "gtin": it["gtin"],
                "feed_id": feed_id, "status": "submitted",
                "error": "", "submitted_at": _now(),
            })
        print(f"店铺 {store}: 已提交 Feed {feed_id}（{len(items)} 个 SKU）")

    # 写回 submit_results（保留历史成功行 + 新提交行）
    existing = load_jsonl(paths["submit_results"]) if paths["submit_results"].exists() else []
    merged = existing + new_rows
    with open(paths["submit_results"], "w", encoding="utf-8") as f:
        for row in merged:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n06 完成：提交 {len(new_rows)} 行 -> {paths['submit_results']}")
    if skipped:
        print(f"（另有 {len(skipped)} 个 SKU 被跳过，详见上方日志）")


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
