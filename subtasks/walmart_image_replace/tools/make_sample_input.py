"""Generate a minimal sample input Excel for walmart_image_replace.

表头（中文，与定稿入参表一致）：
    平台SKU  GTIN  店铺  OSS路径  开发SKU  主图链接  标题  五点
（五点为单个单元格：五条卖点合并在同一单元格内，换行分隔）
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

TASK_ROOT = Path(__file__).resolve().parent.parent
OUT = TASK_ROOT / "input" / "sample_replace.xlsx"

HEADER = ["平台SKU", "GTIN", "店铺", "OSS路径", "开发SKU", "主图链接", "标题", "五点"]

# platform_sku, gtin, store, oss_path, dev_sku, main_image_url, title, bullets(单单元格，五条卖点)
ROWS = [
    ["SKU_A001", "000000000001", "store_us", "develop/SKU_A001", "DEV_A001",
     "https://oss.example.com/develop/SKU_A001/main.png", "红色运动水壶",
     "不锈钢材质\n户外便携\n大容量\n防漏设计\n简约风格"],
    ["SKU_B002", "000000000002", "store_us", "develop/SKU_B002", "DEV_B002",
     "https://oss.example.com/develop/SKU_B002/main.png", "蓝色收纳箱",
     "大容量\n家居整理\n可折叠\n耐磨\n北欧风"],
    ["SKU_C003", "000000000003", "store_ca", "develop/SKU_C003", "DEV_C003",
     "https://oss.example.com/develop/SKU_C003/main.png", "无线鼠标",
     "静音点击\n办公通用\n长续航\n人体工学\n黑色"],
    ["SKU_FAIL4", "000000000004", "store_us", "develop/SKU_FAIL4", "DEV_FAIL4",
     "https://oss.example.com/develop/SKU_FAIL4/main.png", "失败演示商品",
     "故意\n用于\n演示\n对账\n失败回流"],
    ["SKU_D005", "000000000005", "store_ca", "develop/SKU_D005", "DEV_D005",
     "https://oss.example.com/develop/SKU_D005/main.png", "儿童绘本",
     "精装\n早教\n图文并茂\n安全油墨\n礼盒装"],
]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"已生成示例入参: {OUT} ({len(ROWS)} 行；含 SKU_FAIL4 用于演示对账失败回流)")


if __name__ == "__main__":
    main()
