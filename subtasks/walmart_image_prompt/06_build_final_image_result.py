"""Step 06: Build final SKU image result workbook."""

from __future__ import annotations

import argparse

from final_image_result import build_final_image_result_from_logs, preview_final_image_result_from_logs
from workflow_common import batch_paths, print_batch_info


def main() -> None:
    parser = argparse.ArgumentParser(description="06 生成最终图片结果表")
    parser.add_argument("--dry-run", action="store_true", help="只预览最终结果表生成数量，不写 Excel。")
    parser.add_argument("--batch-name", default=None, help="手动指定批次名；不填则按入参 Excel 文件名确定。")
    args = parser.parse_args()

    print("\n=== 06 生成最终图片结果表 ===")
    print_batch_info(args.batch_name)
    paths = batch_paths(args.batch_name)
    input_path = paths["oss_results"]
    image_results_path = paths["image_results"]
    output_path = paths["final_image_excel"]

    if args.dry_run:
        summary = preview_final_image_result_from_logs(input_path, image_results_path, output_path)
        print("试运行: 不写最终结果 Excel")
    else:
        summary = build_final_image_result_from_logs(input_path, image_results_path, output_path)

    print(f"OSS结果日志: {summary.input_path}")
    print(f"图片结果日志: {image_results_path}")
    print(f"输出Excel: {summary.output_path}")
    print(f"源行数: {summary.source_rows} | 有效副图行: {summary.eligible_rows}")
    print(f"SKU数量: {summary.sku_count} | 达标SKU({summary.desired_count}张): {summary.complete_sku_count}")
    if summary.missing_by_sku:
        print(f"\n缺失类型清单（{len(summary.missing_by_sku)} 个 SKU 未凑满 {summary.desired_count} 张）:")
        for sku, types in sorted(summary.missing_by_sku.items()):
            print(f"  {sku}: 缺少 {', '.join(types)}")
    if not args.dry_run:
        print("最终图片结果表生成完成")


if __name__ == "__main__":
    main()
