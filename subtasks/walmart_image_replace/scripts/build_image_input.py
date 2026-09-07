"""Build image-input workbook for walmart_image_replace (dynamic row count).

与 walmart_image_prompt 的 scripts/build_sub_image_download_input.py 同一逻辑，
区别在于行数动态确定：不按固定 image_count 全量展开，而是按阶段 01 算出的
「缺失位置」逐位置生成一行（每个 OSS 目录 = 一个图片任务组，SKU 列 = OSS路径）。

图片命名 new_sub{位置}_{开发SKU}（不含扩展名，下载/上传阶段自动补 .png），
与 OSS 已有新附图命名一致。SKU 列 = OSS路径/开发SKU（图片流水线主键），
上传 key_template {sku}/{image_name}.png 渲染出的对象路径与已有图同目录。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import Workbook  # noqa: E402

from workflow_common import batch_paths, load_jsonl, load_stage_config  # noqa: E402

DEFAULT_IMAGE_NAME_TEMPLATE = "new_sub{position}_{dev_sku}"

# 图片入参 Excel 表头（与 stages/generate_images/config.json 的 columns 对应）
HEADERS = ["SKU", "参考图片链接", "图片命名", "图片类型", "下载结果", "task_id"]


def image_name_template() -> str:
    naming = load_stage_config("generate_images").get("naming", {})
    return naming.get("image_name_template") or DEFAULT_IMAGE_NAME_TEMPLATE


def build_rows(batch_name: str | None = None) -> list[dict]:
    """从阶段 01 的 inventory 展开图片入参行（按 OSS路径/开发SKU 去重，行数 = 缺失位置数）。"""
    paths = batch_paths(batch_name)
    template = image_name_template()
    rows: list[dict] = []
    seen: set[str] = set()
    for rec in load_jsonl(paths["inventory"]):
        oss_path = str(rec.get("oss_image_path", "")).strip()
        dev_sku = str(rec.get("dev_sku", "")).strip()
        # 图片流水线主键 = OSS路径/开发SKU（与 02 的 model_results.sku 一致）
        image_key = f"{oss_path.rstrip('/')}/{dev_sku}" if oss_path and dev_sku else oss_path
        if not image_key or image_key in seen:
            continue
        seen.add(image_key)
        main_image = str(rec.get("main_image_url", "")).strip()
        for position in rec.get("missing_positions", []):
            image_name = template.replace("{position}", str(position)).replace("{dev_sku}", dev_sku)
            rows.append({
                "sku": image_key,
                "reference_image": main_image,
                "image_name": image_name,
                "image_type": "",
                "position": position,
            })
    return rows


def run(batch_name: str | None = None) -> list[dict]:
    rows = build_rows(batch_name)
    paths = batch_paths(batch_name)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEADERS)
    for row in rows:
        ws.append([row["sku"], row["reference_image"], row["image_name"], row["image_type"], None, None])
    paths["image_input_excel"].parent.mkdir(parents=True, exist_ok=True)
    wb.save(paths["image_input_excel"])
    sku_count = len({r["sku"] for r in rows})
    print(f"选图模式=按缺失位置动态展开(共 {len(rows)} 行 / {sku_count} 个图片目录)")
    print(f"output_path={paths['image_input_excel']}")
    return rows


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="构建图片生成入参 Excel（动态行数）")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()
    run(args.batch_name)
