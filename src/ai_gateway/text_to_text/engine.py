from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_gateway.config.loader import load_app_config
from ai_gateway.retry_policy import gateway_max_attempts, is_retryable_error

from .config import TaskDefinition
from .excel_io import export_results, read_excel, snapshot_input
from .models import BatchPaths, CallResult, InputRecord
from .response import load_validator, parse_response
from .state_store import StateStore
from .template import PromptTemplate, normalize_name, render_inline, request_hash, stringify
from .tuzi import TuziTextGateway


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value.strip()).strip("._-") or "batch"


def make_batch_id(task_name: str) -> str:
    return f"{safe_name(task_name)}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"


class StartLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = max(float(interval), 0.0)
        self.lock = threading.Lock()
        self.next_start = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self.lock:
            now = time.monotonic()
            target = max(now, self.next_start)
            self.next_start = target + self.interval
        if target > now:
            time.sleep(target - now)


class TextBatchEngine:
    def __init__(self, project_root: Path, task_root: Path, task: TaskDefinition, batch_id: str) -> None:
        self.project_root = project_root
        self.task_root = task_root
        self.task = task
        self.batch_id = safe_name(batch_id)
        root = task.root / "batches" / self.batch_id
        self.paths = BatchPaths(root, root / "state.sqlite3", root / "manifest.json", root / "snapshots",
                                root / "result.xlsx", root / "failed.xlsx", root / "results.jsonl", root / "raw_outputs")

    def prepare(self, source_path: Path, *, create_snapshot: bool) -> tuple[str, list[InputRecord], list[str]]:
        if not source_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {source_path}")
        input_config = self.task.input
        if input_config.get("type", "excel") != "excel":
            raise ValueError(f"当前版本仅支持 Excel 输入，收到: {input_config.get('type')}")
        sheet_name, headers, source_rows = read_excel(source_path, input_config.get("sheet_name"), int(input_config.get("header_row", 1)))
        template = PromptTemplate(self.task.prompt)
        template.validate_headers(headers)
        record_id_template = str(input_config.get("record_id_template") or "").strip()
        id_template = PromptTemplate(record_id_template) if record_id_template else None
        if id_template:
            id_template.validate_headers(headers)
        action_column = input_config.get("action_column")
        image_url_columns = [str(name) for name in input_config.get("image_url_columns", [])]
        required_image_url_columns = [
            str(name) for name in input_config.get("required_image_url_columns", [])
        ]
        unknown_required_image_columns = [
            name for name in required_image_url_columns if name not in image_url_columns
        ]
        if unknown_required_image_columns:
            raise ValueError(
                "必填图片列未包含在 image_url_columns 中: "
                + ", ".join(unknown_required_image_columns)
            )
        if image_url_columns:
            header_index = {normalize_name(name) for name in headers}
            missing_image_headers = [
                name for name in image_url_columns if normalize_name(name) not in header_index
            ]
            if missing_image_headers:
                raise ValueError(
                    "图片链接列没有对应表头: " + ", ".join(missing_image_headers)
                )
        request_contract = {
            "task": self.task.name, "task_version": self.task.version,
            "model": self.task.gateway.get("model"), "max_tokens": self.task.gateway.get("max_tokens", 1200),
            "temperature": self.task.gateway.get("temperature", 0.1), "response": self.task.response,
        }
        records: list[InputRecord] = []
        keys: set[str] = set()
        for row_number, fields in source_rows:
            lookup = {normalize_name(name): value for name, value in fields.items()}
            missing = [name for name in input_config.get("required_placeholders", []) if not stringify(lookup.get(normalize_name(name)))]
            missing.extend(
                name
                for name in required_image_url_columns
                if not self._image_urls(fields, [name])
            )
            record_key = render_inline(record_id_template, fields) if id_template else f"row:{row_number}"
            if not record_key:
                raise ValueError(f"第 {row_number} 行 record_id_template 渲染为空")
            if record_key in keys:
                raise ValueError(f"用户配置的记录键重复: {record_key}（第 {row_number} 行）")
            keys.add(record_key)
            prompt = template.render(fields)
            action = stringify(lookup.get(normalize_name(action_column))) if action_column else "auto"
            action = action.casefold() or "auto"
            action_aliases = {"自动": "auto", "重跑": "rerun", "跳过": "skip"}
            action = action_aliases.get(action, action)
            if action not in {"auto", "rerun", "skip"}:
                raise ValueError(f"第 {row_number} 行处理动作无效: {action}")
            if missing:
                prompt = prompt
            image_urls = self._image_urls(fields, image_url_columns)
            row_contract = request_contract
            if image_url_columns:
                row_contract = {
                    **request_contract,
                    "images": {
                        "urls": image_urls,
                        "detail": str(self.task.gateway.get("image_detail", "auto")),
                    },
                }
            records.append(
                InputRecord(
                    record_key,
                    row_number,
                    fields,
                    prompt,
                    request_hash(prompt, row_contract),
                    action,
                    image_urls,
                )
            )
            records[-1].fields["__missing_required__"] = missing
        if create_snapshot:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            snapshot_input(source_path, self.paths.snapshots, run_id)
        return sheet_name, records, headers

    @staticmethod
    def _image_urls(fields: dict[str, Any], columns: list[str]) -> list[str]:
        if not columns:
            return []
        lookup = {normalize_name(name): value for name, value in fields.items()}
        urls: list[str] = []
        for column in columns:
            value = stringify(lookup.get(normalize_name(column)))
            for line in value.splitlines():
                url = line.strip()
                if url and url not in {"0", "0.0"} and url not in urls:
                    urls.append(url)
        return urls

    def dry_run(self, source_path: Path) -> dict[str, Any]:
        sheet, records, headers = self.prepare(source_path, create_snapshot=False)
        invalid_rows = [
            record.source_row
            for record in records
            if record.fields.get("__missing_required__")
        ]
        return {"task": self.task.name, "task_version": self.task.version, "batch_id": self.batch_id,
                "source": str(source_path), "sheet": sheet, "headers": headers,
                "records": len(records), "placeholders": PromptTemplate(self.task.prompt).placeholders,
                "input_invalid": len(invalid_rows), "input_invalid_rows": invalid_rows}

    def run(
        self,
        source_path: Path,
        *,
        max_records: int | None = None,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        sheet_name, records, _ = self.prepare(source_path, create_snapshot=True)
        self._write_manifest(source_path, sheet_name)
        store = StateStore(self.paths.state)
        try:
            pending: list[InputRecord] = []
            for record in records:
                old = store.get(record.record_key)
                if record.action == "skip":
                    if not old or old["input_hash"] != record.input_hash:
                        store.stage(record, "skipped")
                    continue
                if record.action == "rerun" or self._should_run(
                    old, record.input_hash, retry_failed=retry_failed
                ):
                    store.stage(record, "pending")
                    pending.append(record)
            if max_records and max_records > 0:
                pending = pending[:max_records]
            results = self._execute(pending, store)
            all_records = store.all()
            output_fields = list(self.task.response.get("fields") or [])
            export_results(source_path, self.paths.result, sheet_name, all_records, output_fields)
            self._write_jsonl(all_records)
            return {"task": self.task.name, "batch_id": self.batch_id, "total": len(records),
                    "selected": len(pending), "success": sum(1 for item in results if item.status == "success"),
                    "failed": sum(1 for item in results if item.status != "success"), "result": str(self.paths.result)}
        finally:
            store.close()

    @staticmethod
    def _should_run(
        old: dict[str, Any] | None,
        input_hash: str,
        *,
        retry_failed: bool = False,
    ) -> bool:
        if not old or old["input_hash"] != input_hash:
            return True
        if retry_failed and str(old["status"]).endswith("_failed"):
            return True
        return old["status"] in {"pending", "api_transient_failed", "cancelled"}

    def _execute(self, records: list[InputRecord], store: StateStore) -> list[CallResult]:
        if not records:
            return []
        app = load_app_config(self.project_root / "configs" / "gateways.yaml", self.project_root / "configs" / "models.yaml")
        gateway_name = self.task.gateway.get("name", "tuzi_text")
        gateway_config = app.gateways[gateway_name]
        gateway = TuziTextGateway(gateway_config)
        limiter = StartLimiter(float(self.task.execution.get("request_start_interval_seconds", 0)))
        validator = load_validator(self.task.root, self.task.response.get("validator"))
        concurrency = max(int(self.task.execution.get("concurrency", 1)), 1)
        results: list[CallResult] = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(self._call_one, record, gateway, gateway_config, limiter, validator): record for record in records}
            try:
                for future in as_completed(futures):
                    result = future.result()
                    store.save(result)
                    self._write_raw(result)
                    results.append(result)
                    print(f"[{len(results)}/{len(records)}] {result.record_key}: {result.status}")
            except KeyboardInterrupt:
                for future in futures:
                    future.cancel()
                raise
        return results

    def _call_one(self, record, gateway, gateway_config, limiter, validator) -> CallResult:
        now = lambda: datetime.now().astimezone().isoformat(timespec="seconds")
        missing = record.fields.get("__missing_required__") or []
        if missing:
            return CallResult(record.record_key, record.source_row, record.input_hash, "input_invalid",
                              error_category="missing_required", error_message=", ".join(missing), updated_at=now())
        maximum = gateway_max_attempts(gateway_config)
        last_error: Exception | None = None
        for attempt in range(1, maximum + 1):
            try:
                limiter.wait()
                text, request_id, latency_ms, _ = gateway.call(
                    prompt=record.rendered_prompt, model=self.task.gateway["model"],
                    max_tokens=int(self.task.gateway.get("max_tokens", 1200)),
                    temperature=float(self.task.gateway.get("temperature", 0.1)),
                    image_urls=record.image_urls,
                    image_detail=str(self.task.gateway.get("image_detail", "auto")),
                )
                parsed = parse_response(text, self.task.response)
                if validator:
                    parsed = validator(record.fields, parsed)
                return CallResult(record.record_key, record.source_row, record.input_hash, "success", text, parsed,
                                  self.task.gateway["model"], request_id, latency_ms, attempt, updated_at=now())
            except ValueError as exc:
                last_error = exc
                if attempt > int(self.task.execution.get("validation_retry_count", 0)):
                    return CallResult(record.record_key, record.source_row, record.input_hash, "validation_failed",
                                      model=self.task.gateway["model"], attempts=attempt, error_category="validation",
                                      error_message=str(exc)[:1000], updated_at=now())
            except Exception as exc:
                last_error = exc
                retryable = (
                    type(exc).__name__ == "ChunkedEncodingError"
                    or is_retryable_error(type(exc).__name__, str(exc))
                )
                if not retryable or attempt >= maximum:
                    status = "api_transient_failed" if retryable else "api_permanent_failed"
                    return CallResult(record.record_key, record.source_row, record.input_hash, status,
                                      model=self.task.gateway["model"], attempts=attempt, error_category=type(exc).__name__,
                                      error_message=str(exc)[:1000], updated_at=now())
            time.sleep(float(self.task.execution.get("retry_delay_seconds", 3)))
        raise RuntimeError(str(last_error))

    def _write_manifest(self, source_path: Path, sheet_name: str) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        manifest = {"batch_id": self.batch_id, "task_name": self.task.name, "task_version": self.task.version,
                    "source_path": str(source_path.resolve()), "source_hash": source_hash, "sheet_name": sheet_name,
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        self.paths.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_raw(self, result: CallResult) -> None:
        if not result.raw_text:
            return
        self.paths.raw_outputs.mkdir(parents=True, exist_ok=True)
        (self.paths.raw_outputs / f"{safe_name(result.record_key)}.txt").write_text(result.raw_text, encoding="utf-8")

    def _write_jsonl(self, records: list[dict[str, Any]]) -> None:
        self.paths.results_jsonl.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")
