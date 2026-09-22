"""Upload generated images to Aliyun OSS with per-image checkpointing."""

from __future__ import annotations

import argparse
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from PIL import Image

from ai_gateway.clients.aliyun_oss_client import (
    AliyunOssClient,
    build_public_url_without_client,
    load_aliyun_oss_config,
)
from ai_gateway.config.loader import load_local_env
from ai_gateway.clients.mxapi_image_client import validate_image_file


_IMAGE_RESULT_UPDATE_LOCK = threading.Lock()
_GENERATION_RECORD_CACHE: dict[Path, dict[str, dict[str, Any]]] = {}


@dataclass(slots=True)
class OssUploadConfig:
    name: str
    project_root: str
    input_excel_path: str
    input_sheet_name: str
    download_dir: str
    output_excel_path: str
    output_results_path: str
    checkpoint_path: str
    columns: dict[str, str]
    oss_prefix: str
    key_template: str
    url_template: str | None = None
    overwrite: bool = True
    max_records: int | None = None
    concurrency: int = 5
    batch_size: int = 500
    skip_success: bool = True
    image_results_path: str | None = None
    output_format: str = "original"
    jpeg_quality: int = 95
    jpeg_subsampling: int = 0
    jpeg_optimize: bool = True
    transparent_policy: str = "keep_png"
    delete_source_after_upload: bool = False


@dataclass(slots=True)
class OssUploadRecord:
    row_number: int
    sku: str
    image_name: str
    status: str
    local_path: str
    oss_key: str
    oss_url: str | None
    file_size: int | None
    error_message: str | None
    retryable: bool
    created_at: str


class CheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock = threading.Lock()
        self.records: dict[str, dict[str, Any]] = {}
        for row in read_jsonl_if_exists(self.path):
            key = record_key(row)
            if key:
                self.records[key] = row

    def rows(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.records.values())

    def upsert(self, record: OssUploadRecord) -> None:
        with self.lock:
            row = asdict(record)
            append_jsonl_row(self.path, row)
            self.records[record_key(row)] = row


def find_project_root(path: Path) -> Path:
    for candidate in [path.parent, *path.parents]:
        if (candidate / "src" / "ai_gateway").exists() and (candidate / "configs").exists():
            return candidate
    raise RuntimeError(f"Cannot find project root from config path: {path}")


def load_config(path: str | Path, *, config_data: dict[str, Any] | None = None) -> OssUploadConfig:
    path = Path(path)
    data = config_data if config_data is not None else json.loads(Path(path).read_text(encoding="utf-8-sig"))
    project_root = find_project_root(path.resolve())
    oss = data.get("oss", {})
    limits = data.get("limits", {})
    resume = data.get("resume", {})
    image_output = data.get("image_output") or oss.get("image_output") or {}
    if not image_output:
        # Stage configs may keep business policy in the task-level config.
        # Resolve it only from this stage's own directory; never scan batches.
        task_config_path = path.resolve().parents[2] / "config.json" if len(path.resolve().parents) > 2 else None
        if task_config_path and task_config_path.is_file():
            task_data = json.loads(task_config_path.read_text(encoding="utf-8-sig"))
            image_output = (task_data.get("oss") or {}).get("image_output") or {}
    return OssUploadConfig(
        name=data["name"],
        project_root=str(project_root),
        input_excel_path=data["input"]["image_result_excel_path"],
        input_sheet_name=data["input"].get("sheet_name", "Sheet1"),
        download_dir=data["input"]["download_dir"],
        output_excel_path=data["output"]["excel_path"],
        output_results_path=data["output"]["results_path"],
        checkpoint_path=data["output"]["checkpoint_path"],
        image_results_path=data["input"].get("image_results_path"),
        columns=data["columns"],
        oss_prefix=oss.get("prefix", "walmart").strip("/"),
        key_template=oss.get("key_template", "walmart/{sku}/{image_name}.png"),
        url_template=oss.get("url_template"),
        overwrite=bool(oss.get("overwrite", True)),
        concurrency=int(limits.get("max_workers", 5)),
        batch_size=int(limits.get("batch_size", 500)),
        skip_success=bool(resume.get("skip_success", True)),
        output_format=str(image_output.get("format", "original")).strip().lower(),
        jpeg_quality=int(image_output.get("quality", 95)),
        jpeg_subsampling=int(image_output.get("subsampling", 0)),
        jpeg_optimize=bool(image_output.get("optimize", True)),
        transparent_policy=str(image_output.get("transparent_policy", "keep_png")).strip().lower(),
        delete_source_after_upload=bool(image_output.get("delete_source_after_upload", False)),
    )


def run(config: OssUploadConfig) -> list[OssUploadRecord]:
    rows, workbook, sheet, headers = load_work_rows(config)
    checkpoint = CheckpointStore(config.checkpoint_path)
    existing = checkpoint.rows()
    completed = completed_keys(existing, rows) if config.skip_success else set()
    pending = [row for row in rows if row_key(row) not in completed]
    if config.max_records and config.max_records > 0:
        pending = limit_rows_by_sku(pending, config.max_records)

    print("\n=== 05 上传 OSS ===", flush=True)
    print(
        f"图片总数: {len(rows)} 行 / {count_skus(rows)} 个 SKU | "
        f"已成功跳过: {len(rows) - len(pending)} 行 | "
        f"本次待上传: {len(pending)} 行 / {count_skus(pending)} 个 SKU "
        f"(max_records={config.max_records} 个 SKU)",
        flush=True,
    )
    client = AliyunOssClient(load_aliyun_oss_config(config.project_root))
    records = process_rows(pending, config, client, checkpoint)
    merged = merge_records(checkpoint.rows(), records, rows)
    write_jsonl_rows(merged, config.output_results_path)
    write_excel(workbook, sheet, headers, merged, config)
    return records


def preview(config: OssUploadConfig) -> None:
    if not Path(config.input_excel_path).exists():
        print("\n=== 05 上传 OSS | 试运行 ===")
        print("试运行: 不连接 OSS，不上传，不写 JSONL/Excel")
        print(f"OSS 上传输入 Excel 不存在: {config.input_excel_path}")
        print("请先完成 03 图片生成下载，或确认当前入参文件名对应的批次目录是否正确。")
        return
    rows, _, _, _ = load_work_rows(config)
    existing = read_jsonl_if_exists(config.checkpoint_path)
    completed = completed_keys(existing, rows) if config.skip_success else set()
    pending = [row for row in rows if row_key(row) not in completed]
    selected = limit_rows_by_sku(pending, config.max_records)

    env_values = load_local_env(Path(config.project_root) / "configs" / "local.env")
    bucket = os.environ.get("ALIYUN_OSS_BUCKET") or env_values.get("ALIYUN_OSS_BUCKET") or "<bucket>"
    endpoint = os.environ.get("ALIYUN_OSS_ENDPOINT") or env_values.get("ALIYUN_OSS_ENDPOINT") or "<endpoint>"
    default_prefix = os.environ.get("ALIYUN_OSS_DEFAULT_PREFIX") or env_values.get("ALIYUN_OSS_DEFAULT_PREFIX") or "images"

    print("\n=== 05 上传 OSS | 试运行 ===")
    print("试运行: 不连接 OSS，不上传，不写 JSONL/Excel")
    print(f"输入Excel: {config.input_excel_path}")
    print(f"图片目录: {config.download_dir}")
    print(f"checkpoint: {config.checkpoint_path}")
    print(
        f"图片总数: {len(rows)} 行 / {count_skus(rows)} 个 SKU | "
        f"已成功跳过: {len(rows) - len(pending)} 行 | "
        f"本次将上传: {len(selected)} 行 / {count_skus(selected)} 个 SKU "
        f"(max_records={config.max_records} 个 SKU)"
    )
    print(f"并发: {config.concurrency} | batch_size: {config.batch_size} | overwrite: {config.overwrite}")
    if selected:
        print("样例:")
        for index, row in enumerate(selected[:5], start=1):
            oss_key = row["oss_key"]
            url = build_public_url_without_client(bucket, endpoint, default_prefix, oss_key)
            print(f"  [{index}] SKU={row['sku']} | 图片={Path(row['local_path']).name} | OSS={url}")


def load_work_rows(config: OssUploadConfig):
    input_path = Path(config.input_excel_path)
    if not input_path.exists():
        raise RuntimeError(f"OSS 上传输入 Excel 不存在: {input_path}")
    workbook = load_workbook(input_path)
    sheet = workbook[config.input_sheet_name]
    headers = header_map(sheet)
    required = [
        config.columns["sku"],
        config.columns["image_name"],
    ]
    missing = [name for name in required if name not in headers]
    if missing:
        raise RuntimeError("Missing OSS upload input headers: " + ", ".join(missing))

    if config.image_results_path and Path(config.image_results_path).exists():
        rows = load_work_rows_from_image_results(config, sheet, headers)
        return rows, workbook, sheet, headers

    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row_number in range(2, sheet.max_row + 1):
        sku = cell_text(sheet, row_number, headers[config.columns["sku"]])
        image_name = cell_text(sheet, row_number, headers[config.columns["image_name"]])
        if not sku or not image_name:
            continue
        download_status_col = config.columns.get("download_status")
        if download_status_col and download_status_col in headers:
            download_status = cell_text(sheet, row_number, headers[download_status_col])
            if download_status != "成功":
                continue
        unique_key = f"{sku}::{image_name}"
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        source_path = Path(config.download_dir) / image_file_name(image_name)
        local_path, extension = planned_output(source_path, config)
        oss_key = render_template(config.key_template, sku=sku, image_name=source_path.stem, extension=extension)
        rows.append(
            {
                "row_number": row_number,
                "sku": sku,
                "image_name": image_name,
                "local_path": str(local_path),
                "source_path": str(source_path),
                "oss_key": oss_key,
            }
        )
    return rows, workbook, sheet, headers


def load_work_rows_from_image_results(config: OssUploadConfig, sheet, headers: dict[str, int]) -> list[dict[str, Any]]:
    image_rows = read_jsonl_if_exists(config.image_results_path or "")
    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in image_rows:
        if row.get("status") != "success":
            continue
        sku = str(row.get("sku") or "").strip()
        image_name = str(row.get("image_name") or "").strip()
        if not sku or not image_name:
            continue
        unique_key = f"{sku}::{image_name}"
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        source_path = Path(row.get("downloaded_path") or str(Path(config.download_dir) / image_file_name(image_name)))
        local_path, extension = planned_output(source_path, config)
        oss_key = render_template(config.key_template, sku=sku, image_name=source_path.stem, extension=extension)
        row_number = row.get("row_number")
        rows.append(
            {
                "row_number": row_number if isinstance(row_number, int) else 0,
                "sku": sku,
                "image_name": image_name,
                "local_path": str(local_path),
                "source_path": str(source_path),
                "oss_key": oss_key,
            }
        )
    row_numbers = current_sheet_row_numbers(sheet, headers, config)
    for row in rows:
        row["row_number"] = row_numbers.get(row_key(row), row.get("row_number") or 0)
    return rows


def process_rows(
    rows: list[dict[str, Any]],
    config: OssUploadConfig,
    client: AliyunOssClient,
    checkpoint: CheckpointStore,
) -> list[OssUploadRecord]:
    if not rows:
        sync_generation_results(config)
        return []
    concurrency = max(int(config.concurrency or 1), 1)
    concurrency = min(concurrency, len(rows))
    print(f"OSS上传并发: {concurrency}", flush=True)
    if concurrency == 1:
        ordered = [process_one(index, len(rows), row, config, client, checkpoint) for index, row in enumerate(rows, start=1)]
    else:
        results: dict[int, OssUploadRecord] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(process_one, index, len(rows), row, config, client, checkpoint): index
                for index, row in enumerate(rows, start=1)
            }
            for future in as_completed(futures):
                index = futures[future]
                results[index] = future.result()
        ordered = [results[index] for index in sorted(results)]
    sync_generation_results(config)
    return ordered


def process_one(
    index: int,
    total: int,
    row: dict[str, Any],
    config: OssUploadConfig,
    client: AliyunOssClient,
    checkpoint: CheckpointStore,
) -> OssUploadRecord:
    sku = row["sku"]
    source_path = Path(row.get("source_path") or row["local_path"])
    local_path = Path(row["local_path"])
    print(f"[{index}/{total}] 开始上传 | SKU={sku} | 图片={local_path.name}", flush=True)
    try:
        local_path, extension = prepare_upload_image(source_path, config)
        row["local_path"] = str(local_path)
        row["oss_key"] = str(Path(str(row["oss_key"])).with_suffix("." + extension)).replace("\\", "/")
    except Exception as exc:
        record = build_record(row, "conversion_failed", None, f"图片转码失败: {exc}", retryable=True)
        checkpoint.upsert(record)
        print(f"[{index}/{total}] 上传失败 | SKU={sku} | 错误={short_error(record.error_message or '')}", flush=True)
        return record
    if not validate_image_file(local_path):
        record = build_record(row, "invalid_file", None, f"本地文件不是有效图片: {local_path}", retryable=False)
        checkpoint.upsert(record)
        print(f"[{index}/{total}] 上传失败 | SKU={sku} | 错误=本地文件不是有效图片", flush=True)
        return record

    result = client.upload_file(local_path, row["oss_key"], overwrite=config.overwrite)
    if result.get("success"):
        status = "skipped" if result.get("skipped") else "success"
        url = client.public_url(row["oss_key"])
        record = build_record(row, status, url, None, retryable=False, file_size=result.get("size"))
        checkpoint.upsert(record)
        if config.delete_source_after_upload and source_path != local_path and source_path.is_file():
            try:
                update_generation_local_path(config, row, local_path)
                source_path.unlink()
            except OSError as exc:
                print(f"[{index}/{total}] 警告 | SKU={sku} | OSS已成功，但删除源图失败: {exc}", flush=True)
        label = "已存在跳过" if status == "skipped" else "上传成功"
        print(f"[{index}/{total}] {label} | SKU={sku} | URL={url}", flush=True)
        return record

    record = build_record(row, "failed", None, str(result.get("error") or "upload failed"), retryable=True)
    checkpoint.upsert(record)
    print(f"[{index}/{total}] 上传失败 | SKU={sku} | 错误={short_error(record.error_message or '')}", flush=True)
    return record


def build_record(
    row: dict[str, Any],
    status: str,
    oss_url: str | None,
    error_message: str | None,
    retryable: bool,
    file_size: int | None = None,
) -> OssUploadRecord:
    return OssUploadRecord(
        row_number=row["row_number"],
        sku=row["sku"],
        image_name=row["image_name"],
        status=status,
        local_path=row["local_path"],
        oss_key=row["oss_key"],
        oss_url=oss_url,
        file_size=file_size,
        error_message=error_message,
        retryable=retryable,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


def merge_records(existing_rows: list[dict[str, Any]], new_records: list[OssUploadRecord], source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {record_key(row): row for row in existing_rows if record_key(row)}
    for record in new_records:
        merged[record_key(asdict(record))] = asdict(record)
    ordered = []
    seen = set()
    for row in source_rows:
        key = row_key(row)
        if key in merged:
            current = dict(merged[key])
            current["row_number"] = row["row_number"]
            current["local_path"] = row["local_path"]
            current["oss_key"] = row["oss_key"]
            ordered.append(current)
            seen.add(key)
    return ordered


def write_excel(workbook, sheet, headers: dict[str, int], rows: list[dict[str, Any]], config: OssUploadConfig) -> None:
    result_columns = ["OSS上传状态", "OSS上传URL", "OSS上传错误", "OSS上传时间"]
    for column_name in result_columns:
        if column_name not in headers:
            headers[column_name] = sheet.max_column + 1
            sheet.cell(row=1, column=headers[column_name], value=column_name)

    row_numbers_by_key = current_sheet_row_numbers(sheet, headers, config)
    for row in rows:
        key = record_key(row)
        row_number = row_numbers_by_key.get(key)
        if not row_number:
            continue
        sheet.cell(row_number, headers["OSS上传状态"], value=display_status(str(row.get("status") or "")))
        sheet.cell(row_number, headers["OSS上传URL"], value=row.get("oss_url"))
        sheet.cell(row_number, headers["OSS上传错误"], value=row.get("error_message"))
        sheet.cell(row_number, headers["OSS上传时间"], value=row.get("created_at"))

    output_path = Path(config.output_excel_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    print(f"OSS结果日志: {config.output_results_path}")
    print(f"OSS结果Excel: {config.output_excel_path}")


def current_sheet_row_numbers(sheet, headers: dict[str, int], config: OssUploadConfig) -> dict[str, int]:
    sku_col = headers[config.columns["sku"]]
    image_name_col = headers[config.columns["image_name"]]
    row_numbers: dict[str, int] = {}
    for row_number in range(2, sheet.max_row + 1):
        sku = cell_text(sheet, row_number, sku_col)
        image_name = cell_text(sheet, row_number, image_name_col)
        if not sku or not image_name:
            continue
        key = f"{sku}::{image_name}"
        row_numbers.setdefault(key, row_number)
    return row_numbers


def header_map(sheet) -> dict[str, int]:
    return {
        str(cell.value).strip(): cell.column
        for cell in sheet[1]
        if cell.value is not None and str(cell.value).strip()
    }


def cell_text(sheet, row: int, column: int) -> str:
    value = sheet.cell(row, column).value
    return "" if value is None else str(value).strip()


def image_file_name(image_name: str) -> str:
    suffix = Path(image_name).suffix
    return image_name if suffix else f"{image_name}.png"


def _has_transparency(path: Path) -> bool:
    with Image.open(path) as image:
        return image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)


def planned_output(source_path: Path, config: OssUploadConfig) -> tuple[Path, str]:
    if config.output_format in {"jpeg", "jpg"}:
        if source_path.is_file() and config.transparent_policy == "keep_png" and _has_transparency(source_path):
            return source_path, source_path.suffix.lstrip(".").lower() or "png"
        return source_path.with_suffix(".jpg"), "jpg"
    return source_path, source_path.suffix.lstrip(".").lower() or "png"


def prepare_upload_image(source_path: Path, config: OssUploadConfig) -> tuple[Path, str]:
    planned, extension = planned_output(source_path, config)
    if not source_path.is_file():
        if planned.is_file() and validate_image_file(planned):
            return planned, extension
        raise RuntimeError(f"本地图片不存在: {source_path}")
    if not validate_image_file(source_path):
        raise RuntimeError(f"本地文件不是有效图片: {source_path}")
    if planned == source_path:
        return source_path, extension
    with Image.open(source_path) as image:
        if _has_transparency(source_path):
            rgba = image.convert("RGBA")
            output = Image.new("RGB", rgba.size, "white")
            output.paste(rgba, mask=rgba.getchannel("A"))
        else:
            output = image.convert("RGB")
        temporary = planned.with_suffix(planned.suffix + ".part")
        output.save(temporary, format="JPEG", quality=config.jpeg_quality,
                    optimize=config.jpeg_optimize, subsampling=config.jpeg_subsampling)
    if not validate_image_file(temporary):
        temporary.unlink(missing_ok=True)
        raise RuntimeError("转码输出不是有效图片")
    temporary.replace(planned)
    return planned, "jpg"


def update_generation_local_path(config: OssUploadConfig, row: dict[str, Any], local_path: Path) -> None:
    """Append the JPG path to the generation checkpoint before deleting PNG."""
    if not config.image_results_path:
        return
    results_path = Path(config.image_results_path).resolve()
    checkpoint_path = generation_checkpoint_path(results_path)
    key = row_key(row)
    with _IMAGE_RESULT_UPDATE_LOCK:
        records = _GENERATION_RECORD_CACHE.get(checkpoint_path)
        if records is None:
            records = latest_rows_by_key(checkpoint_path)
            if not records:
                records = latest_rows_by_key(results_path)
            _GENERATION_RECORD_CACHE[checkpoint_path] = records
        saved = records.get(key)
        if not saved:
            return
        updated = dict(saved)
        # A validated local image has already been accepted by OSS at this
        # point.  Preserve that terminal fact even when the process-wide cache
        # was populated in an earlier scheduler cycle while the task was only
        # submitted/pending.
        updated["status"] = "success"
        updated["downloaded_path"] = str(local_path)
        updated["file_size"] = local_path.stat().st_size
        append_jsonl_row(checkpoint_path, updated)
        records[key] = updated


def generation_checkpoint_path(results_path: Path) -> Path:
    if results_path.name == "image_generation_results.jsonl":
        return results_path.with_name("image_generation_checkpoint.jsonl")
    return results_path


def latest_rows_by_key(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for saved in read_jsonl_if_exists(path):
        key = record_key(saved)
        if key:
            latest[key] = saved
    return latest


def append_jsonl_row(path: Path, row: dict[str, Any]) -> None:
    """Append one durable state transition without rewriting prior history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.is_file() and path.stat().st_size:
        with path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            if existing.read(1) not in {b"\n", b"\r"}:
                prefix = "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + json.dumps(row, ensure_ascii=False) + "\n")


def sync_generation_results(config: OssUploadConfig) -> None:
    """Compact updated local JPG paths into the generation summary once per run."""
    if not config.image_results_path:
        return
    results_path = Path(config.image_results_path).resolve()
    checkpoint_path = generation_checkpoint_path(results_path)
    if not results_path.is_file() or not checkpoint_path.is_file():
        return
    try:
        with _IMAGE_RESULT_UPDATE_LOCK:
            checkpoint_rows = _GENERATION_RECORD_CACHE.get(checkpoint_path)
            if checkpoint_rows is None:
                checkpoint_rows = latest_rows_by_key(checkpoint_path)
                _GENERATION_RECORD_CACHE[checkpoint_path] = checkpoint_rows
            rows = read_jsonl_if_exists(results_path)
            changed = False
            for saved in rows:
                current = checkpoint_rows.get(record_key(saved))
                if not current or not current.get("downloaded_path"):
                    continue
                for field in ("status", "downloaded_path", "file_size"):
                    if saved.get(field) != current.get(field):
                        saved[field] = current.get(field)
                        changed = True
            if changed:
                temporary = results_path.with_suffix(results_path.suffix + ".tmp")
                write_jsonl_rows(rows, temporary)
                temporary.replace(results_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"警告: 生成结果路径汇总暂未同步，将在下次续跑重试: {exc}", flush=True)


def render_template(template: str, **values: str) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered.replace("\\", "/").lstrip("/")


def row_key(row: dict[str, Any]) -> str:
    return f"{row['sku']}::{row['image_name']}"


def count_skus(rows: list[dict[str, Any]]) -> int:
    return len({str(row.get("sku") or "").strip() for row in rows if str(row.get("sku") or "").strip()})


def limit_rows_by_sku(rows: list[dict[str, Any]], max_records: int | None) -> list[dict[str, Any]]:
    """按 SKU 为单位截断：最多保留前 max_records 个 SKU 的全部行。

    max_records 语义为“源数据行数（SKU 数）”，每个 SKU 展开的图片行作为一个整体，
    要么全部保留、要么全部截断，避免同一 SKU 只上传部分图片。
    """
    if not max_records or max_records <= 0:
        return rows
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for row in rows:
        sku = str(row.get("sku") or "").strip()
        if not sku:
            continue
        if sku not in seen:
            if len(seen) >= max_records:
                continue
            seen.add(sku)
        selected.append(row)
    return selected


def record_key(row: dict[str, Any]) -> str:
    sku = row.get("sku")
    image_name = row.get("image_name")
    return f"{sku}::{image_name}" if sku and image_name else ""


def completed_keys(
    rows: list[dict[str, Any]],
    work_rows: list[dict[str, Any]] | None = None,
) -> set[str]:
    current = {record_key(row): row for row in (work_rows or []) if record_key(row)}
    completed: set[str] = set()
    for row in rows:
        key = record_key(row)
        if row.get("status") not in {"success", "skipped"} or not key:
            continue
        work = current.get(key)
        if work:
            # Prefer the exact file that was uploaded. This keeps historical
            # PNG successes complete after future batches switch to JPEG.
            path = Path(str(row.get("local_path") or work.get("local_path") or ""))
            if not path.is_file() or not validate_image_file(path):
                continue
            previous_size = row.get("file_size")
            if isinstance(previous_size, int) and previous_size > 0 and path.stat().st_size != previous_size:
                continue
        completed.add(key)
    return completed


def read_jsonl_if_exists(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    nonempty = [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]
    for position, (line_number, line) in enumerate(nonempty):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if position == len(nonempty) - 1:
                break
            raise ValueError(f"JSONL中间记录损坏: {path}:{line_number + 1}")
    return rows


def write_jsonl_rows(rows: list[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def display_status(status: str) -> str:
    return {
        "success": "成功",
        "skipped": "跳过",
        "failed": "失败",
        "missing_file": "本地图片不存在",
    }.get(status, status)


def short_error(message: str, limit: int = 120) -> str:
    text = " ".join(str(message).split())
    return text if len(text) <= limit else text[:limit] + "..."


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload generated images to Aliyun OSS.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.max_records is not None:
        config.max_records = args.max_records
    if args.concurrency is not None:
        config.concurrency = args.concurrency
    if args.dry_run:
        preview(config)
        return
    records = run(config)
    success_count = sum(1 for item in records if item.status in {"success", "skipped"})
    print(f"OSS上传汇总: {len(records)} | 成功/跳过: {success_count} | 失败: {len(records) - success_count}")


if __name__ == "__main__":
    main()
