"""Build sub-image download input workbook for successful Walmart SKUs."""

from __future__ import annotations

import json
from copy import copy
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

TASK_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = TASK_ROOT / "stages" / "build_sub_image_download_input" / "config.json"


def header_map(worksheet) -> dict[str, int]:
    return {
        str(cell.value).strip(): cell.column
        for cell in worksheet[1]
        if cell.value is not None and str(cell.value).strip()
    }


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = Path(path)
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def successful_skus(results_path: str | Path) -> set[str]:
    skus: set[str] = set()
    from ai_gateway.subtasks.walmart_call_prompt_model import inspect_result_text

    for row in read_jsonl(results_path):
        full_output_path = row.get("full_output_path")
        if full_output_path:
            text_path = Path(full_output_path)
            if not text_path.exists():
                continue
            _, _, validation_error = inspect_result_text(text_path.read_text(encoding="utf-8", errors="replace"))
            if validation_error:
                continue
        elif row.get("status") != "success" or row.get("validation_status") != "passed":
            continue
        sku = row.get("sku")
        if sku:
            skus.add(str(sku).strip())
    return skus


def copy_row_style(worksheet, source_row: int, target_row: int) -> None:
    for col_idx in range(1, worksheet.max_column + 1):
        source_cell = worksheet.cell(source_row, col_idx)
        target_cell = worksheet.cell(target_row, col_idx)
        if source_cell.has_style:
            target_cell._style = copy(source_cell._style)
        if source_cell.number_format:
            target_cell.number_format = source_cell.number_format
        if source_cell.alignment:
            target_cell.alignment = copy(source_cell.alignment)
        if source_cell.font:
            target_cell.font = copy(source_cell.font)
        if source_cell.fill:
            target_cell.fill = copy(source_cell.fill)
        if source_cell.border:
            target_cell.border = copy(source_cell.border)


def require_headers(headers: dict[str, int], names: list[str], label: str) -> None:
    missing = [name for name in names if name not in headers]
    if missing:
        raise RuntimeError(f"Missing {label} headers: {', '.join(missing)}")


def run(config: dict[str, Any]) -> None:
    input_config = config["input"]
    output_config = config["output"]
    columns = config["columns"]
    image_count = int(config.get("image_count", 6))

    success_skus = successful_skus(input_config["model_results_path"])
    if not success_skus:
        raise RuntimeError("No successful SKUs found in model results.")

    source_wb = load_workbook(input_config["source_excel_path"], read_only=True, data_only=True)
    source_ws = source_wb[input_config["source_sheet_name"]]
    source_headers = header_map(source_ws)
    require_headers(
        source_headers,
        [columns["source_sku"], columns["source_main_image"]],
        "source Excel",
    )

    template_wb = load_workbook(input_config["template_path"])
    template_ws = template_wb[input_config["template_sheet_name"]]
    template_headers = header_map(template_ws)
    require_headers(
        template_headers,
        [
            columns["template_sku"],
            columns["template_reference_image"],
            columns["template_image_name"],
            columns["template_download_result"],
            columns["template_task_id"],
        ],
        "template Excel",
    )
    remove_columns_by_header(template_ws, ["OSS上传结果", "结果确认"])
    template_headers = header_map(template_ws)

    if template_ws.max_row > 1:
        template_ws.delete_rows(2, template_ws.max_row - 1)

    sku_col = source_headers[columns["source_sku"]]
    main_image_col = source_headers[columns["source_main_image"]]
    style_row = 2
    output_row = 2
    generated_skus: list[str] = []
    empty_sku_streak = 0
    stop_after_empty_sku_rows = int(config.get("stop_after_empty_sku_rows", 200))

    for row_idx in range(2, source_ws.max_row + 1):
        raw_sku = source_ws.cell(row_idx, sku_col).value
        if raw_sku is None:
            empty_sku_streak += 1
            if empty_sku_streak >= stop_after_empty_sku_rows:
                break
            continue
        sku = str(raw_sku).strip()
        if not sku:
            empty_sku_streak += 1
            if empty_sku_streak >= stop_after_empty_sku_rows:
                break
            continue
        empty_sku_streak = 0
        if sku not in success_skus:
            continue
        main_image = source_ws.cell(row_idx, main_image_col).value
        main_image = "" if main_image is None else str(main_image).strip()
        generated_skus.append(sku)

        for image_no in range(1, image_count + 1):
            image_name = f"new_sub{image_no}_{sku}"
            copy_row_style(template_ws, style_row, output_row)
            template_ws.cell(output_row, template_headers[columns["template_sku"]]).value = sku
            template_ws.cell(output_row, template_headers[columns["template_reference_image"]]).value = main_image
            template_ws.cell(output_row, template_headers[columns["template_image_name"]]).value = image_name
            template_ws.cell(output_row, template_headers[columns["template_download_result"]]).value = None
            template_ws.cell(output_row, template_headers[columns["template_task_id"]]).value = None
            output_row += 1

    output_path = Path(output_config["excel_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template_wb.save(output_path)
    print(f"successful_skus={len(generated_skus)}")
    print(f"generated_rows={output_row - 2}")
    print(f"output_path={output_path}")


def remove_columns_by_header(worksheet, header_names: list[str]) -> None:
    headers = header_map(worksheet)
    columns = sorted(
        [headers[name] for name in header_names if name in headers],
        reverse=True,
    )
    for column in columns:
        worksheet.delete_cols(column)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    run(config)


if __name__ == "__main__":
    main()
