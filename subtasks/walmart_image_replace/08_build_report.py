"""Step 08: Build final upload result report (derived, regenerated each run).

Columns: 店铺 | 平台SKU | GTIN | 上传的图片链接 | 是否成功 | 失败原因 | 沃尔玛上架状态

是否成功 = 替换结果 complete（全部副图已生成并上传 OSS）。
沃尔玛上架状态（若已运行 06/07）= 07 对账结果按 SKU 汇总：
  成功（沃尔玛已接受） / 失败（沃尔玛拒绝，失败原因附沃尔玛错误） / 处理中（稍后重跑 07）
未运行 07 时显示「未提交」。每次运行覆盖 result_report.jsonl / .xlsx。
"""

from __future__ import annotations

import argparse
import json

from workflow_common import batch_paths, ensure_dirs, load_jsonl, print_batch_info

STATUS_LABEL = {
    "success": "成功",
    "pending": "未完成",
}
WALMART_STATUS_LABEL = {
    "success": "成功",
    "failed": "失败",
    "in_progress": "处理中",
    "error": "查询失败",
}
ERROR_STATUS = {"failed", "error"}


def build_rows(payloads: list[dict], oss_rows: list[dict],
               reconcile_rows: list[dict]) -> tuple[list[dict], bool]:
    """生成报告行。返回 (rows, has_reconcile)。"""
    # 按 (store, sku) 聚合对账结果；同一 SKU 多次对账取最后一条
    recon: dict[tuple, dict] = {}
    for r in reconcile_rows:
        recon[(r.get("store", ""), r.get("sku", ""))] = r
    has_reconcile = bool(recon)

    rows = []
    for p in payloads:
        sku = p["platform_sku"]
        complete = bool(p.get("complete", False))
        missing = p.get("missing_positions", [])
        error_reason = ""
        if missing:
            error_reason = f"缺少副图位置: {missing}"
        if not p.get("main_image_url"):
            error_reason = (error_reason + "；" if error_reason else "") + "主图链接缺失"
        raw_status = "success" if complete and not error_reason else "pending"
        label = STATUS_LABEL.get(raw_status, raw_status)
        image_links = "\n".join(item["url"] for item in p.get("final_images", []))

        wm_label, wm_reason = "未提交", ""
        r = recon.get((p.get("store", ""), sku))
        if r:
            wm_raw = r.get("status", "")
            wm_label = WALMART_STATUS_LABEL.get(wm_raw, wm_raw or "未知")
            errs = r.get("errors") or []
            descs = [e.get("description") or e.get("code", "") for e in errs if isinstance(e, dict)]
            wm_reason = "; ".join(d for d in descs if d)
            if wm_raw == "in_progress":
                wm_reason = wm_reason or f"feedStatus={r.get('feed_status', '')}，稍后重跑 07"
        rows.append({
            "store": p.get("store", ""),
            "platform_sku": sku,
            "gtin": p.get("gtin", ""),
            "image_links": image_links,
            "status": label,
            "error_reason": error_reason,
            "walmart_status": wm_label,
            "walmart_error": wm_reason if r and r.get("status") in ERROR_STATUS else "",
        })
    return rows, has_reconcile


def write_xlsx(path, rows: list[dict]) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        print("（未安装 openpyxl，跳过 xlsx 输出；仅写 jsonl）")
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "上传结果"
    headers = ["店铺", "平台SKU", "GTIN", "上传的图片链接", "是否成功", "失败原因", "沃尔玛上架状态", "沃尔玛失败原因"]
    ws.append(headers)
    for r in rows:
        ws.append([r["store"], r["platform_sku"], r["gtin"], r["image_links"],
                   r["status"], r["error_reason"], r["walmart_status"], r["walmart_error"]])
    wb.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="08 生成本次上传结果报告")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写文件。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 08 生成本次上传结果报告 ===")
    print_batch_info(args.batch_name)
    paths = ensure_dirs(args.batch_name)
    payloads = load_jsonl(paths["payload"])
    oss_rows = load_jsonl(paths["oss_results"])
    reconcile_rows = load_jsonl(paths["reconcile_results"])
    if not payloads:
        msg = "未找到 replace_payload.jsonl，请先运行 05"
        if args.dry_run:
            print(msg + "（dry-run 跳过）")
            return
        raise SystemExit(msg)

    rows, has_reconcile = build_rows(payloads, oss_rows, reconcile_rows)
    print(f"生成报告行数: {len(rows)}" + ("（已合并 07 沃尔玛对账状态）" if has_reconcile else "（未运行 06/07，沃尔玛上架状态=未提交）"))
    for r in rows:
        print(f"  {r['store']}\t{r['platform_sku']}\t{r['gtin']}\t{r['status']}\t沃尔玛: {r['walmart_status']}"
              + (f"\t失败原因: {r['error_reason']}" if r["error_reason"] else ""))

    if args.dry_run:
        print("试运行: 不写文件。")
        return

    with open(paths["report"], "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_xlsx(paths["report_xlsx"], rows)
    print(f"已写出报告 -> {paths['report']} 与 {paths['report_xlsx']}")


if __name__ == "__main__":
    main()
