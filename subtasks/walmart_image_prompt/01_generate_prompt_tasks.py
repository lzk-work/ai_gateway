"""Step 01: Generate BUZZ prompt tasks from Walmart Excel."""

from __future__ import annotations

import argparse
from pathlib import Path

from workflow_common import GET_PROMPT_CONFIG, apply_batch_to_prompt_config, print_batch_info

from ai_gateway.subtasks.template_renderer import render_template
from ai_gateway.subtasks.walmart_get_pic_prompt import (
    _is_empty_row,
    load_config,
    precheck_task,
    read_excel_rows,
    run,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="01 生成提示词任务")
    parser.add_argument("--dry-run", action="store_true", help="只预览将要读取的数据，不写输出文件。")
    args = parser.parse_args()

    print("\n=== 01 生成提示词任务 ===")
    config = apply_batch_to_prompt_config(load_config(GET_PROMPT_CONFIG))
    print_batch_info()
    if args.dry_run:
        preview(config)
        return
    records = run(config)
    print(f"已生成任务: {len(records)}")


def preview(config) -> None:
    if not Path(config.input_excel).exists():
        print("试运行: 不写入 generated_prompt_tasks.jsonl")
        print(f"Excel 不存在: {config.input_excel}")
        print("请确认 stages/get_pic_prompt/config.json 中的 input.excel_path 是否指向当前批次入参文件。")
        return
    rows = [(row_number, row) for row_number, row in read_excel_rows(config.input_excel, config.sheet_name) if not _is_empty_row(row)]
    template = Path(config.prompt_template_path).read_text(encoding="utf-8-sig")
    passed = 0
    failed = 0
    samples = []
    for row_number, row in rows:
        rendered, _ = render_template(template, row, placeholder_mapping=config.placeholder_mapping)
        image_urls = [str(row.get(column)).strip() for column in config.image_columns if row.get(column)]
        status, _, _ = precheck_task(rendered, image_urls, config.limits)
        if status == "passed":
            passed += 1
        else:
            failed += 1
        if len(samples) < 5:
            sku = str(row.get(config.task_id_column) or f"row-{row_number}").strip()
            samples.append((row_number, sku, len(rendered), len(image_urls), status))

    print("试运行: 不写入 generated_prompt_tasks.jsonl")
    print(f"Excel: {config.input_excel}")
    print(f"Sheet: {config.sheet_name or 'active'}")
    print(f"有效数据行: {len(rows)} | 预检通过: {passed} | 预检失败: {failed}")
    print(f"输出位置: {config.output_path}")
    if samples:
        print("样例:")
        for row_number, sku, prompt_len, image_count, status in samples:
            print(f"  行{row_number} | SKU={sku} | prompt字符={prompt_len} | 图片={image_count} | 预检={status}")


if __name__ == "__main__":
    main()
