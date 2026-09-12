#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立审核预览导出（不接入 workflow 配置，手动运行）。

把生成的结果图（主图 + 副图，仅 success 的）缩略后嵌入 Excel，
并在图块之后附「对应链接」列，供业务人员直接审核。
左侧加 SKU / 标题 / 五点 入参信息列。每张图压成最长边 400px 的 JPEG，
避免 100 个 SKU 直接嵌原图导致 xlsx 破 G。

布局：SKU | 标题 | 五点 | [全部嵌入图] | [全部对应链接]
（链接仅取 OSS 上传成功的落地地址 oss_url，写成可点击超链接；
 未成功上传 OSS 的图链接留空。本脚本应在 01-06 全部完成后手动运行）

用法：
    python 07_export_review.py                 # 用总 config.json 的 input excel 推断批次
    python 07_export_review.py --batch 批次名   # 显式指定批次目录名
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from PIL import Image  # noqa: E402
import openpyxl  # noqa: E402
from openpyxl.drawing.image import Image as XLImage  # noqa: E402
from openpyxl.styles import Font  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from workflow_common import (  # noqa: E402
    batch_name_from_input,
    batch_paths,
    load_task_config,
)

THUMB_SIZE = 400          # 缩略图最长边（px）
JPEG_QUALITY = 75         # JPEG 压缩质量
MAIN_TYPE = "Main Image"  # 主图结果记录的 image_type
# 源表入参列名（用于读取 标题 / 五点）
SRC_SKU_COL = "SKU"
SRC_TITLE_COL = "标题"
SRC_BULLET_COL = "五点"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_source_meta() -> dict[str, dict]:
    """读取源 Excel 的 SKU -> {标题, 五点} 映射（用于审核表左侧信息列）。"""
    input_cfg = load_task_config().get("input", {})
    path = input_cfg.get("excel_path")
    sheet = input_cfg.get("sheet_name")
    if not path or not Path(path).exists():
        print(f"    [提示] 未找到源 Excel，标题/五点列将为空: {path}")
        return {}
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        print(f"    [警告] 读取源 Excel 失败: {exc}")
        return {}
    ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
    it = ws.iter_rows(values_only=True)
    try:
        header = next(it)
    except StopIteration:
        wb.close()
        return {}
    cols = {str(name).strip(): i for i, name in enumerate(header) if name is not None}
    si = cols.get(SRC_SKU_COL)
    ti = cols.get(SRC_TITLE_COL)
    bi = cols.get(SRC_BULLET_COL)
    meta: dict[str, dict] = {}
    for row in it:
        if si is None or si >= len(row):
            break
        sku = str(row[si] or "").strip()
        if not sku:
            continue
        meta[sku] = {
            "title": str(row[ti]).strip() if (ti is not None and ti < len(row) and row[ti] is not None) else "",
            "bullets": str(row[bi]).strip() if (bi is not None and bi < len(row) and row[bi] is not None) else "",
        }
    wb.close()
    return meta


def make_thumbnail(source_path: Path) -> tuple[int, int, io.BytesIO] | None:
    """读取本地 PNG，缩到最长边 THUMB_SIZE，转 JPEG 返回 (宽, 高, 字节流)。"""
    try:
        img = Image.open(source_path)
        img.thumbnail((THUMB_SIZE, THUMB_SIZE))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
        buf.seek(0)
        return img.width, img.height, buf
    except Exception as exc:  # 图片损坏/无法读取，跳过该图
        print(f"    [警告] 缩略图失败: {source_path} -> {exc}")
        return None


def collect_by_sku(records: list[dict], is_main: bool) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for rec in records:
        if rec.get("status") != "success":
            continue
        sku = str(rec.get("sku") or "").strip()
        if not sku:
            continue
        # 主图文件里的记为主图；副图文件里的记为副图（按 image_number 排序）
        if is_main != (str(rec.get("image_type") or "").strip() == MAIN_TYPE):
            continue
        grouped.setdefault(sku, []).append(rec)
    for sku in grouped:
        grouped[sku].sort(key=lambda r: (r.get("image_number") or 0))
    return grouped


def load_oss_map(path: Path) -> dict[str, str]:
    """读取 OSS 上传结果，建立 sku::image_name -> oss_url 映射。

    仅取 status 为 success/skipped（已落地的）记录；未上传或上传失败的图不进映射。
    """
    mapping: dict[str, str] = {}
    for rec in load_jsonl(path):
        if str(rec.get("status") or "") not in {"success", "skipped"}:
            continue
        sku = str(rec.get("sku") or "").strip()
        image_name = str(rec.get("image_name") or "").strip()
        url = rec.get("oss_url")
        if not sku or not image_name or not url:
            continue
        mapping[f"{sku}::{image_name}"] = str(url)
    return mapping


def split_skus(skus: list[str], max_skus_per_file: int) -> list[list[str]]:
    if max_skus_per_file <= 0:
        raise ValueError("review.max_skus_per_file 必须大于 0")
    return [skus[index:index + max_skus_per_file] for index in range(0, len(skus), max_skus_per_file)]


def output_paths(base: Path, part_count: int) -> list[Path]:
    if part_count <= 1:
        return [base]
    width = max(3, len(str(part_count)))
    return [base.with_name(f"{base.stem}_{index:0{width}d}{base.suffix}") for index in range(1, part_count + 1)]


def export(batch: str, out_path: Path) -> None:
    paths = batch_paths(batch)
    sub_records = load_jsonl(Path(paths["image_results"]))
    main_records = load_jsonl(Path(paths["main_image_results"]))
    if not sub_records and not main_records:
        print(f"未找到任何结果记录，批次目录可能不存在或尚未生成：{paths['root']}")
        return

    # OSS 最终落地地址映射（优先用；缺失则回退 generated_image_url）
    oss_map = {}
    oss_sub = load_oss_map(Path(paths["oss_results"]))
    oss_main = load_oss_map(Path(paths["main_oss_results"]))
    oss_map.update(oss_sub)
    oss_map.update(oss_main)
    has_oss = bool(oss_sub or oss_main)
    if not has_oss:
        print("    [警告] 未读取到 OSS 上传结果（05/05b 尚未运行），所有链接将为空。请确认 01-06 已全部完成后再运行本脚本。")

    main_map = collect_by_sku(main_records, is_main=True)
    sub_map = collect_by_sku(sub_records, is_main=False)
    source_meta = load_source_meta()

    all_skus = sorted(set(main_map) | set(sub_map))
    if not all_skus:
        print("没有 status=success 的结果图可嵌入。")
        return

    # 每 SKU 图片序列：主图在前，副图按 image_number 在后
    def images_for(sku: str) -> list[dict]:
        return main_map.get(sku, []) + sub_map.get(sku, [])

    max_imgs = max(len(images_for(sku)) for sku in all_skus)
    max_skus_per_file = int(load_task_config().get("review", {}).get("max_skus_per_file", 1000))
    sku_parts = split_skus(all_skus, max_skus_per_file)
    outputs = output_paths(out_path, len(sku_parts))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for old in [out_path, *out_path.parent.glob(f"{out_path.stem}_*{out_path.suffix}")]:
        if old.is_file() and old not in outputs:
            old.unlink()

    success_count = oss_link_count = 0
    for output, part_skus in zip(outputs, sku_parts):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "审核预览"
        img_header = ["主图"] + [f"副图{i}" for i in range(1, max_imgs)]
        link_header = ["主图链接"] + [f"副图{i}链接" for i in range(1, max_imgs)]
        header = ["SKU", "标题", "五点"] + img_header + link_header
        ws.append(header)
        for col_idx in range(1, len(header) + 1):
            ws.cell(row=1, column=col_idx).font = Font(bold=True)
        ws.freeze_panes = "D2"
        info_width = 3
        img_start = info_width + 1
        link_start = img_start + max_imgs
        part_images = 0
        for row_idx, sku in enumerate(part_skus, start=2):
            meta = source_meta.get(sku, {})
            ws.cell(row=row_idx, column=1, value=sku)
            ws.cell(row=row_idx, column=2, value=meta.get("title", ""))
            ws.cell(row=row_idx, column=3, value=meta.get("bullets", ""))
            ws.cell(row=row_idx, column=3).alignment = openpyxl.styles.Alignment(wrap_text=True, vertical="top")
            imgs = images_for(sku)
            max_h = THUMB_SIZE
            for j, rec in enumerate(imgs):
                col_idx = img_start + j
                col = get_column_letter(col_idx)
                src = rec.get("downloaded_path")
                thumb = make_thumbnail(Path(str(src))) if src and Path(str(src)).exists() else None
                if not thumb:
                    ws.cell(row=row_idx, column=col_idx, value="生成失败/缺失")
                    continue
                w, h, buf = thumb
                max_h = max(max_h, h)
                xl_img = XLImage(buf)
                xl_img.width, xl_img.height = w, h
                ws.add_image(xl_img, f"{col}{row_idx}")
                success_count += 1
                part_images += 1
            for j, rec in enumerate(imgs):
                col_idx = link_start + j
                url = oss_map.get(f"{sku}::{rec.get('image_name')}")
                if url:
                    oss_link_count += 1
                    cell = ws.cell(row=row_idx, column=col_idx, value=str(url))
                    cell.hyperlink = str(url)
                    cell.font = Font(color="0563C1", underline="single")
            ws.row_dimensions[row_idx].height = max_h * 0.75 + 6
        ws.column_dimensions["A"].width = 22
        ws.column_dimensions["B"].width = 30
        ws.column_dimensions["C"].width = 45
        for col_idx in range(img_start, link_start):
            ws.column_dimensions[get_column_letter(col_idx)].width = THUMB_SIZE / 7.0 + 2
        for col_idx in range(link_start, link_start + max_imgs):
            ws.column_dimensions[get_column_letter(col_idx)].width = 40
        ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(part_skus) + 1}"
        wb.save(output)
        wb.close()
        print(f"分卷完成: {output.name} | SKU={len(part_skus)} | 图片={part_images}")
    print(f"\n=== 审核预览导出完成 ===")
    print(f"SKU 数: {len(all_skus)} | 每卷最多: {max_skus_per_file} | 文件数: {len(outputs)} | 嵌入成功图: {success_count} 张 | 含标题/五点列: {sum(1 for s in all_skus if s in source_meta)}")
    print(f"链接: 仅 OSS 成功上传地址，命中 {oss_link_count}/{success_count} 张" + ("" if has_oss else "（警告: 未读取到 OSS 结果, 链接全空）"))
    print(f"布局: SKU|标题|五点 | [嵌入图×{max_imgs}] | [链接×{max_imgs}]")
    print(f"缩略图: 最长边 {THUMB_SIZE}px / JPEG q{JPEG_QUALITY}")
    for output in outputs:
        print(f"输出: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="导出结果图审核预览 Excel（缩略图+链接）")
    parser.add_argument("--batch", default=None, help="批次目录名，缺省从总 config.json 推断")
    args = parser.parse_args()

    batch = args.batch or batch_name_from_input()
    out_path = batch_paths(batch)["root"] / "07_review" / "审核预览.xlsx"
    print(f"批次: {batch}")
    print(f"输出: {out_path}")
    export(batch, out_path)


if __name__ == "__main__":
    main()
