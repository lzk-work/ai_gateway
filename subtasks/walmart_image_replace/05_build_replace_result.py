"""Step 05: Assemble final replace payload (main + secondary images).

适配 03/04 复用共享模块后的行级产物：
  - 阶段 03 输出 image_generation_results.jsonl（行级，sku=OSS路径/开发SKU）
  - 阶段 04 输出 oss_upload_results.jsonl（行级，sku=OSS路径/开发SKU）
主图来自入参「主图链接」列（独立，不进副图数组）；已有副图按 existing_positions
映射位置，新图按 new_sub{位置}_{开发SKU} 查行级上传记录。
OSS 对象路径 = {OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png（新图与已有图同目录）。
"""

from __future__ import annotations

import argparse
import json

from workflow_common import batch_paths, ensure_dirs, load_jsonl, oss_public_base, print_batch_info


def to_public_url(key: str, base: str | None) -> str:
    """把相对 oss_key 拼成公网 URL（无 OSS 配置时原样返回，兼容本地未配 OSS 的场景）。"""
    if not base:
        return key
    return f"{base}/{str(key).lstrip('/')}"


def main() -> None:
    parser = argparse.ArgumentParser(description="05 组装替换结果")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写输出。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 05 组装替换结果 ===")
    print_batch_info(args.batch_name)
    paths = ensure_dirs(args.batch_name)
    inventory = load_jsonl(paths["inventory"])
    oss_rows = load_jsonl(paths["oss_results"])
    if not inventory:
        msg = "未找到 image_inventory.jsonl，请先运行 01"
        if args.dry_run:
            print(msg + "（dry-run 跳过本阶段预览）")
            return
        raise SystemExit(msg)
    if not paths["oss_results"].exists():
        msg = "未找到 oss_upload_results.jsonl，请先运行 04"
        if args.dry_run:
            print(msg + "（dry-run 跳过本阶段预览）")
            return
        raise SystemExit(msg)
    # 文件存在但为空：所有 SKU 均不缺图（无需生成/上传），继续用已有图组装

    # 行级上传记录：(OSS路径, 图片命名) -> 记录；只认成功/跳过
    uploaded: dict[tuple[str, str], dict] = {}
    for r in oss_rows:
        if r.get("status") in ("success", "skipped"):
            uploaded[(str(r.get("sku", "")), str(r.get("image_name", "")))] = r

    records = []
    for inv in inventory:
        sku = inv["platform_sku"]
        target = int(inv.get("target_upload", 6))
        oss_path = str(inv.get("oss_image_path", "")).rstrip("/")
        dev_sku = str(inv.get("dev_sku", "")).strip()
        main = inv.get("main_image_url", "")
        # 已有副图：位置 -> URL（existing_positions 与 existing_images 一一对应）
        # existing_images 存的是相对 oss_key，组装时拼公网基座（无配置时原样保留）
        base = oss_public_base()
        positions = inv.get("existing_positions") or list(range(1, len(inv.get("existing_images", [])) + 1))
        existing_map = {p: to_public_url(url, base) for p, url in zip(positions, inv.get("existing_images", []))}
        secondary = []
        missing = []
        final = [{"position": 0, "url": main, "source": "main"}]
        for p in range(1, target + 1):
            if p in existing_map:
                secondary.append(existing_map[p])
                final.append({"position": p, "url": existing_map[p], "source": "existing"})
                continue
            up = uploaded.get((f"{oss_path}/{dev_sku}", f"new_sub{p}_{dev_sku}"))
            if up:
                secondary.append(up["oss_url"])
                final.append({"position": p, "url": up["oss_url"], "source": "new"})
            else:
                missing.append(p)
        complete = len(missing) == 0 and bool(main)
        records.append({
            "platform_sku": sku,
            "store": inv.get("store", ""),
            "gtin_type": "GTIN",
            "gtin": inv.get("gtin", ""),
            "main_image_url": main,
            "secondary_urls": secondary,
            "final_images": final,
            "missing_positions": missing,
            "complete": complete,
        })

    if args.dry_run:
        ok = sum(1 for r in records if r["complete"])
        print(f"试运行: 不写 replace_payload.jsonl；共 {len(records)} 条 SKU，完整 {ok} 条")
        return

    with open(paths["payload"], "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已写出替换结果: {len(records)} 条 SKU -> {paths['payload']}")


if __name__ == "__main__":
    main()
