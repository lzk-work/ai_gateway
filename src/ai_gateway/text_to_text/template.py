from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

PLACEHOLDER = re.compile(r"{{\s*([^{}]+?)\s*}}")


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class PromptTemplate:
    def __init__(self, text: str) -> None:
        self.text = text
        self.placeholders = list(dict.fromkeys(match.strip() for match in PLACEHOLDER.findall(text)))
        if not self.placeholders:
            raise ValueError("提示词模板至少需要一个 {{ 表头 }} 占位符")

    def validate_headers(self, headers: list[str]) -> None:
        index = _header_index(headers)
        missing = [name for name in self.placeholders if normalize_name(name) not in index]
        if missing:
            raise ValueError(f"提示词占位符没有对应表头: {', '.join(missing)}；可用表头: {', '.join(headers)}")

    def render(self, row: dict[str, Any]) -> str:
        index = {normalize_name(name): stringify(value) for name, value in row.items()}

        def replace(match: re.Match[str]) -> str:
            name = match.group(1).strip()
            key = normalize_name(name)
            if key not in index:
                raise ValueError(f"占位符没有对应字段: {name}")
            return index[key]

        rendered = PLACEHOLDER.sub(replace, self.text)
        if PLACEHOLDER.search(rendered):
            raise ValueError("提示词仍包含未替换占位符")
        return rendered


def render_inline(template: str, row: dict[str, Any]) -> str:
    return PromptTemplate(template).render(row).strip()


def request_hash(prompt: str, request_contract: dict[str, Any]) -> str:
    import json

    payload = prompt + "\x1f" + json.dumps(request_contract, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _header_index(headers: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for header in headers:
        key = normalize_name(header)
        if not key:
            continue
        if key in result:
            raise ValueError(f"Excel 存在重复或大小写冲突表头: {header}")
        result[key] = header
    return result
