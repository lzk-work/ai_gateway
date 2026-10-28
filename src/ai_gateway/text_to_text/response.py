from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any, Callable


def parse_response(text: str, config: dict[str, Any]) -> dict[str, Any]:
    response_type = config.get("type", "raw_text")
    if not text.strip():
        raise ValueError("模型返回文本为空")
    if response_type == "raw_text":
        return {}
    if response_type == "json":
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        value = json.loads(cleaned)
        if not isinstance(value, dict):
            raise ValueError("JSON 响应必须是对象")
        return value
    if response_type == "fixed_fields":
        fields = config.get("fields") or []
        if not fields:
            raise ValueError("fixed_fields 响应需要配置 fields")
        cleaned = re.sub(r"^```(?:text)?\s*|\s*```$", "", text.strip(), flags=re.I)
        positions = []
        for field in fields:
            match = re.search(
                rf"(?m)^\s*(?:\d+\s*[.、．)）—-]\s*)?"
                rf"(?:\*\*\s*)?{re.escape(field)}(?:\s*\*\*)?\s*[:：]\s*",
                cleaned,
            )
            if not match:
                raise ValueError(f"响应缺少字段: {field}")
            positions.append((field, match.start(), match.end()))
        if [item[1] for item in positions] != sorted(item[1] for item in positions):
            raise ValueError("响应字段顺序不正确")
        parsed: dict[str, Any] = {}
        for index, (field, _, value_start) in enumerate(positions):
            value_end = positions[index + 1][1] if index + 1 < len(positions) else len(cleaned)
            value = cleaned[value_start:value_end].strip()
            if field in config.get("required_fields", fields) and not value:
                raise ValueError(f"响应字段为空: {field}")
            parsed[field] = value
        return parsed
    raise ValueError(f"不支持的响应类型: {response_type}")


def load_validator(task_root: Path, filename: str | None) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None:
    if not filename:
        return None
    path = task_root / filename
    spec = importlib.util.spec_from_file_location(f"text_task_validator_{task_root.name}", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"无法加载校验器: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate
