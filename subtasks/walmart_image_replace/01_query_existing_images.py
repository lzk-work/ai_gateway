"""Step 01: Read Walmart replace input Excel and query existing OSS images.

入参表头（中文）固定为：
    平台SKU  GTIN  店铺  OSS路径  开发SKU  主图链接  标题  五点
（五点为单个单元格，五条卖点合并在同一单元格内）
阶段参数（命名正则、min/max 副图数）在 stages/query_existing_images/config.json。

已有图探测（真实模式，默认）：对公共读 OSS 公网 URL 发 GET + Range: bytes=0-0，
逐位置探测 {OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png 是否存在。
副图位置有界（1..max_sub_images），无需列举目录。
注意：不用 HEAD——本机代理环境下 HEAD 可能被拒（实测 HTTP 000），GET 正常。
依赖 configs/local.env 的 ALIYUN_OSS_* 配置做真实探测；缺少配置时报错退出，不再静默回退。
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from openpyxl import load_workbook

from workflow_common import (
    batch_paths,
    ensure_dirs,
    load_stage_config,
    load_task_config,
    oss_public_base,
    print_batch_info,
    resolve_store_key,
    task_replace,
)


# 中文表头 -> 内部字段名（代码与 jsonl 流水线统一用英文）
HEADER_MAP = {
    "平台SKU": "platform_sku",
    "GTIN": "gtin",
    "店铺": "store",
    "OSS路径": "oss_image_path",
    "开发SKU": "dev_sku",
    "主图链接": "main_image_url",
    "标题": "title",
    "五点": "bullets",
}
REQUIRED_HEADERS = list(HEADER_MAP.keys())


def read_rows(excel_path: str, sheet_name, header_map=None):
    wb = load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return [], []
    raw_header = [str(c).strip() if c is not None else "" for c in rows[0]]
    # 应用映射：若表头在 header_map 中则转为内部字段名，否则保留原样（兼容英文表头）
    mapped_header = [(header_map.get(h, h) if header_map else h) for h in raw_header]
    data = []
    for r in rows[1:]:
        if all(c is None or str(c).strip() == "" for c in r):
            continue
        data.append({mapped_header[i]: r[i] for i in range(min(len(mapped_header), len(r)))})
    return raw_header, data


# 已有新附图命名：{OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png  （位置从 1 开始）
# 正则来自 stages/query_existing_images/config.json 的 naming.existing_name_pattern
DEFAULT_EXISTING_NAME_PATTERN = r"^new_sub(\d+)_(?P<dev>.+?)\.png$"


def existing_name_re() -> re.Pattern:
    pattern = load_stage_config("query_existing_images").get("naming", {}).get("existing_name_pattern")
    return re.compile(pattern or DEFAULT_EXISTING_NAME_PATTERN, re.IGNORECASE)


def existing_object_key(oss_path: str, dev_sku: str, position: int) -> str:
    """已有新附图对象 key（不含 default_prefix）：{OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png。"""
    return f"{oss_path.strip('/')}/{dev_sku}/new_sub{position}_{dev_sku}.png"


def probe_url_exists(url: str, timeout: float = 10.0) -> bool | None:
    """GET + Range 探测公共读对象是否存在。

    返回 True=存在 / False=404 不存在 / None=网络或权限异常（无法判断）。
    403 视为不存在（对象缺失时 OSS 公共读也可能回 403），由调用方统计提示。
    """
    req = urllib.request.Request(
        url,
        headers={"Range": "bytes=0-0", "User-Agent": "ai-gateway-walmart-replace/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        if e.code in (404, 403):
            return False
        return None
    except Exception:
        return None


def probe_existing_positions(
    items: list[tuple[int, str, str]],
    base_url: str,
    max_n: int,
    concurrency: int = 8,
) -> tuple[dict[int, list[int]], int]:
    """并发探测每个 (行号, OSS路径, 开发SKU) 的已有副图位置。

    返回 ({行号: 有序位置列表}, 网络异常次数)。
    """
    tasks = [
        (idx, position, f"{base_url}/{existing_object_key(oss_path, dev_sku, position)}")
        for idx, oss_path, dev_sku in items
        for position in range(1, max_n + 1)
    ]
    results: dict[int, list[int]] = {idx: [] for idx, _, _ in items}
    error_count = 0

    def _probe(task):
        idx, position, url = task
        return idx, position, probe_url_exists(url)

    if tasks:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(tasks))) as executor:
            for idx, position, exists in executor.map(_probe, tasks):
                if exists is True:
                    results[idx].append(position)
                elif exists is None:
                    error_count += 1
    return {idx: sorted(positions) for idx, positions in results.items()}, error_count


def main() -> None:
    parser = argparse.ArgumentParser(description="01 查询已有图片")
    parser.add_argument("--dry-run", action="store_true", help="只预览读取结果，不写输出。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 01 查询已有图片 ===")
    print_batch_info(args.batch_name)
    input_cfg = load_task_config().get("input", {})
    replace_cfg = task_replace()
    min_n = int(replace_cfg.get("min_sub_images", 4))
    max_n = int(replace_cfg.get("max_sub_images", 6))
    excel_path = input_cfg.get("excel_path")
    sheet_name = input_cfg.get("sheet_name")
    name_re = existing_name_re()

    raw_header, rows = read_rows(excel_path, sheet_name, HEADER_MAP)
    missing_cols = [c for c in REQUIRED_HEADERS if c not in raw_header]
    if missing_cols:
        raise SystemExit(f"Excel 缺少必需列（中文表头）: {missing_cols}")

    # --- 真实探测：依赖 configs/local.env 的 ALIYUN_OSS_* 配置 ---
    base_url = oss_public_base()
    if not base_url:
        raise SystemExit("缺少 OSS 配置（configs/local.env 需 ALIYUN_OSS_BUCKET / ALIYUN_OSS_ENDPOINT），无法探测已有图，请先补齐配置")
    print(f"真实探测: {base_url}（GET Range，位置 1..{max_n}）")

    paths = ensure_dirs(args.batch_name)
    records = []
    for row in rows:
        sku = str(row.get("platform_sku", "")).strip()
        if not sku:
            continue
        store = resolve_store_key(str(row.get("store", "")).strip())
        oss_path = str(row.get("oss_image_path", "")).strip()
        dev_sku = str(row.get("dev_sku", "")).strip()
        main_image_url = str(row.get("main_image_url", "")).strip()
        gtin = str(row.get("gtin", "")).strip()
        title = str(row.get("title", "")).strip()
        bullets = str(row.get("bullets", "") or "").strip()
        records.append({
            "platform_sku": sku,
            "store": store,
            "oss_image_path": oss_path,
            "dev_sku": dev_sku,
            "main_image_url": main_image_url,
            "gtin": gtin,
            "title": title,
            "bullets": bullets,
            "min_sub_images": min_n,
            "max_sub_images": max_n,
        })

    # --- 新附图计数规则：下限 min_n、上限 max_n，按真实探测到的 existing_positions 计算 ---
    items = [(i, r["oss_image_path"], r["dev_sku"]) for i, r in enumerate(records)]
    positions_by_row, error_count = probe_existing_positions(items, base_url, max_n)
    if error_count:
        print(f"[警告] {error_count} 个探测请求网络异常，对应位置按不存在处理（可能误判为缺失，重跑可恢复）")
    for i, rec in enumerate(records):
        rec["existing_positions"] = positions_by_row[i]

    for rec in records:
        existing_count = len(rec["existing_positions"])
        target_upload = min(max_n, max(existing_count, min_n))
        rec["target_upload"] = target_upload
        rec["existing_images"] = [
            existing_object_key(rec["oss_image_path"], rec["dev_sku"], p) for p in rec["existing_positions"]
        ]
        rec["existing_count"] = existing_count
        rec["missing_positions"] = [p for p in range(1, target_upload + 1) if p not in rec["existing_positions"]]
        rec["to_generate"] = len(rec["missing_positions"])
        rec["existing_source"] = "oss"

    if records and not any(r.get("existing_count") for r in records):
        print("[提示] 全部 SKU 均未探测到已有图——若 bucket 非公共读或地域填错，探测会全部 404，请核对 ALIYUN_OSS_ENDPOINT / bucket ACL")

    if args.dry_run:
        print(f"试运行: 不写 image_inventory.jsonl；共 {len(records)} 条 SKU（真实 OSS 探测，共需生成 {sum(r['to_generate'] for r in records)} 张）")
        for rec in records[:10]:
            print(f"  SKU={rec['platform_sku']} store={rec['store']} 已有={rec['existing_count']} 目标上传={rec['target_upload']} 缺失={rec['missing_positions']}")
        return

    with open(paths["inventory"], "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    total_missing = sum(r["to_generate"] for r in records)
    print(f"已写出 image_inventory: {len(records)} 条 -> {paths['inventory']}（真实 OSS 探测，共需生成 {total_missing} 张）")


if __name__ == "__main__":
    main()
