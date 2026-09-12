from __future__ import annotations

import argparse

from replication_final_result import build
from workflow_common import paths


def main() -> None:
    parser = argparse.ArgumentParser(description="04 生成图片复刻最终结果表")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    p = paths()
    if args.dry_run:
        print(f"试运行不写最终表 | 输出={p['final_excel']}")
        return
    summary = build(p["image_input"], p["image_results"], p["oss_results"], p["final_excel"])
    print(f"最终SKU={summary['sku_count']} | 完整SKU={summary['complete_skus']} | 已上传图片={summary['uploaded_images']}")
    print(f"输出: {p['final_excel']}")


if __name__ == "__main__":
    main()
