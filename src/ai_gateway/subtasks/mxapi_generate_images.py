"""Generate images with MXAPI gpt-image-2 from prepared workbook rows."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ai_gateway.clients.mxapi_image_client import MxapiImageClient
from ai_gateway.config.loader import load_app_config
from ai_gateway.validators.result_validator import extract_json


@dataclass(slots=True)
class MxapiGenerateImagesConfig:
    name: str
    gateways_path: str
    models_path: str
    gateway: str
    submit_endpoint: str
    query_endpoint: str
    model: str
    aspect_ratio: str
    quality: str
    resolution: str
    input_excel_path: str
    input_sheet_name: str
    model_results_path: str
    output_excel_path: str
    output_results_path: str
    checkpoint_path: str
    download_dir: str
    raw_responses_dir: str
    columns: dict[str, str]
    max_records: int | None = None
    concurrency: int = 1
    poll_interval_seconds: int = 5
    max_wait_seconds: int = 300
    submit_delay_seconds: float = 1.5
    download_timeout_seconds: int = 60
    max_submit_retries: int = 3
    max_download_retries: int = 2
    retry_delay_seconds: int = 5
    skip_success: bool = True
    poll_existing_task_id: bool = True


@dataclass(slots=True)
class ImageGenerationRecord:
    row_number: int
    sku: str
    image_name: str
    image_number: int | None
    status: str
    task_id: str | None
    reference_image: str | None
    generated_image_url: str | None
    downloaded_path: str | None
    file_size: int | None
    error_message: str | None
    retryable: bool
    submit_latency_ms: int | None
    poll_count: int
    total_wait_seconds: int | None
    created_at: str


def find_project_root(path: Path) -> Path:
    for candidate in [path.parent, *path.parents]:
        if (candidate / "src" / "ai_gateway").exists() and (candidate / "configs").exists():
            return candidate
    raise RuntimeError(f"Cannot find project root from config path: {path}")


def load_config(path: str | Path) -> MxapiGenerateImagesConfig:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    project_root = find_project_root(path.resolve())
    execution = data["execution"]
    gateway = execution["gateway"]
    model = execution["model"]
    limits = data.get("limits", {})
    retry = data.get("retry", {})
    resume = data.get("resume", {})
    return MxapiGenerateImagesConfig(
        name=data["name"],
        gateways_path=str(project_root / "configs" / "gateways.yaml"),
        models_path=str(project_root / "configs" / "models.yaml"),
        gateway=gateway["name"],
        submit_endpoint=gateway.get("endpoint_submit", "/api/v2/gpt-image-2"),
        query_endpoint=gateway.get("endpoint_query", "/api/v2/gpt-image/task"),
        model=model.get("name", "gpt-image-2"),
        aspect_ratio=model.get("aspect_ratio", "1:1"),
        quality=model.get("quality", "low"),
        resolution=model.get("resolution", "1K"),
        input_excel_path=data["input"]["excel_path"],
        input_sheet_name=data["input"].get("sheet_name", "Sheet1"),
        model_results_path=data["input"]["model_results_path"],
        output_excel_path=data["output"]["excel_path"],
        output_results_path=data["output"]["results_path"],
        checkpoint_path=data["output"].get("checkpoint_path", data["output"]["results_path"]),
        download_dir=data["output"]["download_dir"],
        raw_responses_dir=data["output"].get("raw_responses_dir", ""),
        columns=data["columns"],
        poll_interval_seconds=int(limits.get("poll_interval_seconds", 5)),
        max_wait_seconds=int(limits.get("max_wait_seconds", 300)),
        submit_delay_seconds=float(limits.get("submit_delay_seconds", 1.5)),
        download_timeout_seconds=int(limits.get("download_timeout_seconds", 60)),
        max_submit_retries=int(retry.get("max_submit_retries", 3)),
        max_download_retries=int(retry.get("max_download_retries", 2)),
        retry_delay_seconds=int(retry.get("retry_delay_seconds", 5)),
        skip_success=bool(resume.get("skip_success", True)),
        poll_existing_task_id=bool(resume.get("poll_existing_task_id", True)),
    )



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

    def upsert(self, record: ImageGenerationRecord) -> None:
        with self.lock:
            self.records[record_key(asdict(record))] = asdict(record)
            self.flush_locked()

    def flush_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for row in self.records.values():
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        temp_path.replace(self.path)


def record_key(row: dict[str, Any]) -> str:
    sku = row.get("sku")
    image_name = row.get("image_name")
    return f"{sku}::{image_name}" if sku and image_name else ""

def run(config: MxapiGenerateImagesConfig) -> list[ImageGenerationRecord]:
    app_config = load_app_config(config.gateways_path, config.models_path)
    gateway_config = app_config.gateways[config.gateway]
    client = MxapiImageClient(gateway_config, config.submit_endpoint, config.query_endpoint)

    prompt_map = load_prompt_map(config.model_results_path)
    rows, workbook, sheet, headers = load_work_rows(config)
    checkpoint_store = CheckpointStore(config.checkpoint_path)
    existing_records = checkpoint_store.rows()
    rows = apply_checkpoint_to_rows(rows, existing_records)
    completed = completed_keys(existing_records) if config.skip_success else set()
    pending_rows = [row for row in rows if row_key(row) not in completed]
    if config.max_records and config.max_records > 0:
        pending_rows = pending_rows[: config.max_records]

    print("\n=== MXAPI 图片生成阶段 ===", flush=True)
    print(
        f"图片任务总数: {len(rows)} | 已成功跳过: {len(rows) - len(pending_rows)} | 本次待处理: {len(pending_rows)}",
        flush=True,
    )
    records = process_rows(pending_rows, prompt_map, config, client, checkpoint_store)
    merged = merge_records(checkpoint_store.rows(), records, rows)
    write_jsonl_rows(merged, config.output_results_path)
    write_excel(workbook, sheet, headers, merged, config)
    return records


def load_work_rows(config: MxapiGenerateImagesConfig):
    input_path = Path(config.input_excel_path)
    workbook = load_workbook(input_path)
    sheet = workbook[config.input_sheet_name]
    headers = header_map(sheet)
    required = [
        config.columns["sku"],
        config.columns["reference_image"],
        config.columns["image_name"],
        config.columns["status"],
        config.columns["task_id"],
    ]
    missing = [name for name in required if name not in headers]
    if missing:
        raise RuntimeError("Missing image input headers: " + ", ".join(missing))

    rows: list[dict[str, Any]] = []
    for row_number in range(2, sheet.max_row + 1):
        sku = cell_text(sheet, row_number, headers[config.columns["sku"]])
        image_name = cell_text(sheet, row_number, headers[config.columns["image_name"]])
        reference_image = cell_text(sheet, row_number, headers[config.columns["reference_image"]])
        status = cell_text(sheet, row_number, headers[config.columns["status"]])
        task_id = cell_text(sheet, row_number, headers[config.columns["task_id"]])
        if not sku or not image_name:
            continue
        rows.append(
            {
                "row_number": row_number,
                "sku": sku,
                "image_name": image_name,
                "reference_image": reference_image,
                "status": status,
                "task_id": task_id,
                "image_number": parse_image_number(image_name),
            }
        )
    return rows, workbook, sheet, headers


def header_map(sheet) -> dict[str, int]:
    return {
        str(cell.value).strip(): cell.column
        for cell in sheet[1]
        if cell.value is not None and str(cell.value).strip()
    }


def cell_text(sheet, row: int, column: int) -> str:
    value = sheet.cell(row, column).value
    return "" if value is None else str(value).strip()


def row_key(row: dict[str, Any]) -> str:
    return f"{row['sku']}::{row['image_name']}"


def completed_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {f"{row.get('sku')}::{row.get('image_name')}" for row in rows if row.get("status") == "success"}


def apply_checkpoint_to_rows(rows: list[dict[str, Any]], checkpoint_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checkpoint_by_key = {record_key(row): row for row in checkpoint_rows if record_key(row)}
    enriched: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        saved = checkpoint_by_key.get(row_key(row))
        if saved:
            if saved.get("task_id"):
                merged["task_id"] = str(saved["task_id"])
            if saved.get("status"):
                merged["status"] = str(saved["status"])
        enriched.append(merged)
    return enriched


def parse_image_number(image_name: str) -> int | None:
    match = re.search(r"sub(\d+)", image_name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def load_prompt_map(model_results_path: str | Path) -> dict[str, dict[int, str]]:
    prompt_map: dict[str, dict[int, str]] = {}
    for row in read_jsonl_if_exists(model_results_path):
        if row.get("status") != "success" or row.get("validation_status") != "passed":
            continue
        sku = row.get("sku")
        full_output_path = row.get("full_output_path")
        if not sku or not full_output_path:
            continue
        text = Path(full_output_path).read_text(encoding="utf-8") if Path(full_output_path).exists() else ""
        parsed, parse_error = extract_json(text)
        if parse_error or not isinstance(parsed, dict):
            continue
        global_restrictions = parsed.get("global_prompt_restrictions")
        global_text = format_prompt_part(global_restrictions)
        item_map: dict[int, str] = {}
        for item in parsed.get("image_plan", []):
            if not isinstance(item, dict):
                continue
            image_number = item.get("image_number")
            if not image_number:
                continue
            prompt = (
                item.get("ai_image_generation_prompt")
                or item.get("image_generation_prompt")
                or item.get("prompt")
                or item.get("design_strategy")
                or ""
            )
            prompt = str(prompt).strip()
            if global_text:
                prompt = f"{prompt}\n\nGlobal Prompt Restrictions:\n{global_text}".strip()
            item_map[int(image_number)] = prompt
        prompt_map[str(sku).strip()] = item_map
    return prompt_map


def format_prompt_part(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False)


def process_rows(
    rows: list[dict[str, Any]],
    prompt_map: dict[str, dict[int, str]],
    config: MxapiGenerateImagesConfig,
    client: MxapiImageClient,
    checkpoint_store: CheckpointStore,
) -> list[ImageGenerationRecord]:
    if not rows:
        return []
    concurrency = max(int(config.concurrency or 1), 1)
    concurrency = min(concurrency, len(rows))
    print(f"图片生成并发: {concurrency}", flush=True)
    if concurrency == 1:
        records = []
        for index, row in enumerate(rows, start=1):
            records.append(process_one(index, len(rows), row, prompt_map, config, client, checkpoint_store))
        return records
    results: dict[int, ImageGenerationRecord] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(process_one, index, len(rows), row, prompt_map, config, client, checkpoint_store): index
            for index, row in enumerate(rows, start=1)
        }
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    return [results[index] for index in sorted(results)]


def process_one(
    index: int,
    total: int,
    row: dict[str, Any],
    prompt_map: dict[str, dict[int, str]],
    config: MxapiGenerateImagesConfig,
    client: MxapiImageClient,
    checkpoint_store: CheckpointStore,
) -> ImageGenerationRecord:
    sku = row["sku"]
    image_name = row["image_name"]
    image_number = row.get("image_number")
    print(f"[{index}/{total}] 开始生成 | SKU={sku} | 图片={image_name}", flush=True)
    prompt = prompt_map.get(sku, {}).get(image_number or -1, "")
    if not prompt:
        record = build_error_record(row, "PromptNotFound", "未找到对应 image_plan prompt")
        checkpoint_store.upsert(record)
        print(f"[{index}/{total}] 生成失败 | SKU={sku} | 错误=未找到对应提示词", flush=True)
        return record
    if not row.get("reference_image"):
        record = build_error_record(row, "ReferenceImageMissing", "参考图片链接为空")
        checkpoint_store.upsert(record)
        print(f"[{index}/{total}] 生成失败 | SKU={sku} | 错误=参考图片链接为空", flush=True)
        return record

    task_id = (row.get("task_id") or None) if config.poll_existing_task_id else None
    submit_latency_ms = None
    try:
        if not task_id:
            task_id, submit_latency_ms = submit_with_retry(client, prompt, row["reference_image"], config)
            checkpoint_store.upsert(build_submitted_record(row, task_id, submit_latency_ms))
            print(f"[{index}/{total}] 已提交 | SKU={sku} | task_id={task_id}", flush=True)
        poll_result, poll_count, wait_seconds = poll_until_done(client, task_id, config)
        image_url = first_image_url(poll_result)
        if not image_url:
            raise RuntimeError("结果中无图片URL")
        download_path = Path(config.download_dir) / f"{image_name}.png"
        file_size = download_with_retry(client, image_url, download_path, config)
        save_raw_response(config, image_name, poll_result)
        record = ImageGenerationRecord(
            row_number=row["row_number"],
            sku=sku,
            image_name=image_name,
            image_number=image_number,
            status="success",
            task_id=task_id,
            reference_image=row.get("reference_image"),
            generated_image_url=image_url,
            downloaded_path=str(download_path),
            file_size=file_size,
            error_message=None,
            retryable=False,
            submit_latency_ms=submit_latency_ms,
            poll_count=poll_count,
            total_wait_seconds=wait_seconds,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        checkpoint_store.upsert(record)
        print(f"[{index}/{total}] 生成成功 | SKU={sku} | 文件={download_path.name}", flush=True)
        return record
    except Exception as exc:
        record = build_error_record(row, exc.__class__.__name__, str(exc), task_id=task_id, submit_latency_ms=submit_latency_ms)
        checkpoint_store.upsert(record)
        print(f"[{index}/{total}] 生成失败 | SKU={sku} | 错误={short_error(str(exc))}", flush=True)
        return record


def submit_with_retry(client: MxapiImageClient, prompt: str, reference_image: str, config: MxapiGenerateImagesConfig) -> tuple[str, int | None]:
    payload = {
        "prompt": prompt,
        "aspect_ratio": config.aspect_ratio,
        "quality": config.quality,
        "resolution": config.resolution,
        "reference_images": [reference_image],
    }
    last_error: Exception | None = None
    for attempt in range(1, config.max_submit_retries + 1):
        if config.submit_delay_seconds > 0:
            time.sleep(config.submit_delay_seconds)
        try:
            response, latency_ms = client.submit(payload)
            if response.get("code") != 200:
                raise RuntimeError(str(response.get("message") or response)[:1000])
            task_id = (response.get("data") or {}).get("task_id")
            if not task_id:
                raise RuntimeError("No task_id in submit response")
            return str(task_id), latency_ms
        except Exception as exc:
            last_error = exc
            if attempt >= config.max_submit_retries:
                break
            time.sleep(config.retry_delay_seconds * attempt)
    raise RuntimeError(f"submit failed: {last_error}")


def poll_until_done(client: MxapiImageClient, task_id: str, config: MxapiGenerateImagesConfig) -> tuple[dict[str, Any], int, int]:
    started = time.time()
    poll_count = 0
    last_payload: dict[str, Any] = {}
    while time.time() - started <= config.max_wait_seconds:
        time.sleep(config.poll_interval_seconds)
        poll_count += 1
        payload, _ = client.query(task_id)
        last_payload = payload
        if payload.get("code") != 200:
            raise RuntimeError(str(payload.get("message") or payload)[:1000])
        data = payload.get("data") or {}
        status = data.get("status")
        if status == "completed":
            return payload, poll_count, int(time.time() - started)
        if status == "failed":
            raise RuntimeError(str(data.get("error") or "task failed"))
    raise RuntimeError(f"poll timeout after {config.max_wait_seconds}s: {last_payload}")


def first_image_url(payload: dict[str, Any]) -> str | None:
    result = ((payload.get("data") or {}).get("result") or {})
    urls: list[str] = []
    for key in ("source_images", "proxy_images", "images"):
        values = result.get(key) or []
        if isinstance(values, list):
            urls.extend(str(item) for item in values if item)
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            return url
        seen.add(url)
    return None


def short_error(message: str, limit: int = 120) -> str:
    text = " ".join(str(message).split())
    if "<!DOCTYPE html>" in text or "<html" in text.lower():
        if "HTTP 520" in text:
            return "HTTP 520 Cloudflare HTML 错误页，上游/中转站异常"
        if "HTTP 504" in text:
            return "HTTP 504 网关超时"
        return "HTTP HTML 错误页，上游/中转站异常"
    return text if len(text) <= limit else text[:limit] + "..."


def download_with_retry(client: MxapiImageClient, image_url: str, path: Path, config: MxapiGenerateImagesConfig) -> int:
    last_error: Exception | None = None
    for attempt in range(1, config.max_download_retries + 1):
        try:
            return client.download(image_url, path, timeout_seconds=config.download_timeout_seconds)
        except Exception as exc:
            last_error = exc
            if attempt >= config.max_download_retries:
                break
            time.sleep(config.retry_delay_seconds * attempt)
    raise RuntimeError(f"download failed: {last_error}")


def save_raw_response(config: MxapiGenerateImagesConfig, image_name: str, payload: dict[str, Any]) -> None:
    if not config.raw_responses_dir:
        return
    path = Path(config.raw_responses_dir) / f"{image_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")



def build_submitted_record(
    row: dict[str, Any],
    task_id: str,
    submit_latency_ms: int | None,
) -> ImageGenerationRecord:
    return ImageGenerationRecord(
        row_number=row["row_number"],
        sku=row["sku"],
        image_name=row["image_name"],
        image_number=row.get("image_number"),
        status="submitted",
        task_id=task_id,
        reference_image=row.get("reference_image"),
        generated_image_url=None,
        downloaded_path=None,
        file_size=None,
        error_message=None,
        retryable=True,
        submit_latency_ms=submit_latency_ms,
        poll_count=0,
        total_wait_seconds=None,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
def build_error_record(
    row: dict[str, Any],
    error_code: str,
    error_message: str,
    task_id: str | None = None,
    submit_latency_ms: int | None = None,
) -> ImageGenerationRecord:
    return ImageGenerationRecord(
        row_number=row["row_number"],
        sku=row["sku"],
        image_name=row["image_name"],
        image_number=row.get("image_number"),
        status="failed",
        task_id=task_id or row.get("task_id") or None,
        reference_image=row.get("reference_image"),
        generated_image_url=None,
        downloaded_path=None,
        file_size=None,
        error_message=f"{error_code}: {error_message}",
        retryable=error_code not in {"PromptNotFound", "ReferenceImageMissing"},
        submit_latency_ms=submit_latency_ms,
        poll_count=0,
        total_wait_seconds=None,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


def merge_records(existing_rows: list[dict[str, Any]], new_records: list[ImageGenerationRecord], source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {f"{row.get('sku')}::{row.get('image_name')}": row for row in existing_rows if row.get("sku") and row.get("image_name")}
    for record in new_records:
        merged[f"{record.sku}::{record.image_name}"] = asdict(record)
    ordered = []
    seen = set()
    for row in source_rows:
        key = row_key(row)
        if key in merged:
            ordered.append(merged[key])
            seen.add(key)
    return ordered


def read_jsonl_if_exists(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl_rows(rows: list[dict[str, Any]], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_excel(workbook, sheet, headers: dict[str, int], rows: list[dict[str, Any]], config: MxapiGenerateImagesConfig) -> None:
    for row in rows:
        row_number = row.get("row_number")
        if not isinstance(row_number, int):
            continue
        sheet.cell(row_number, headers[config.columns["status"]], value="成功" if row.get("status") == "success" else "失败")
        sheet.cell(row_number, headers[config.columns["task_id"]], value=row.get("task_id"))
    output_path = Path(config.output_excel_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    print(f"图片结果日志: {config.output_results_path}")
    print(f"图片结果Excel: {config.output_excel_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate images with MXAPI.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.max_records is not None:
        config.max_records = args.max_records
    if args.concurrency is not None:
        config.concurrency = args.concurrency
    records = run(config)
    success_count = sum(1 for item in records if item.status == "success")
    print(f"图片生成汇总: {len(records)} | 成功: {success_count} | 失败: {len(records) - success_count}")


if __name__ == "__main__":
    main()


