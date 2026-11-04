from __future__ import annotations

import re
from typing import Any


SUCCESS_FIELDS = [
    "status",
    "product_description",
    "feature_1",
    "feature_2",
    "feature_3",
    "feature_4",
    "feature_5",
]
FAIL_FIELDS = ["status", "message"]
FEATURE_FIELDS = [f"feature_{index}" for index in range(1, 6)]
ENGLISH_WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
FORBIDDEN_AGE_WORDS = re.compile(
    r"\b(?:child|childs|baby|children|kid|kids|toy|toys|teenager|boy|boys|girl|girls)\b",
    re.IGNORECASE,
)


def _validate_generated_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是非空字符串")
    if any(character in value for character in ('"', "\\", "\t", "\n", "\r")):
        raise ValueError(f"{field}包含JSON安全规则禁止的字符")
    if CJK.search(value):
        raise ValueError(f"{field}必须只使用英文")
    if FORBIDDEN_AGE_WORDS.search(value):
        raise ValueError(f"{field}包含提示词禁止的年龄或品类词")
    return value.strip()


def validate(source: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    status = parsed.get("status")
    if status == "fail":
        if list(parsed) != FAIL_FIELDS:
            raise ValueError("fail响应必须且只能按顺序包含status、message")
        message = _validate_generated_text(parsed["message"], "message")
        return {"status": "fail", "message": message}

    if status != "success":
        raise ValueError("status只能为success或fail")
    if list(parsed) != SUCCESS_FIELDS:
        raise ValueError("success响应字段名称或顺序不符合提示词要求")

    paragraphs = parsed["product_description"]
    if not isinstance(paragraphs, list) or len(paragraphs) != 3:
        raise ValueError("product_description必须恰好包含3个段落字符串")
    clean_paragraphs = [
        _validate_generated_text(value, f"product_description[{index}]")
        for index, value in enumerate(paragraphs, start=1)
    ]
    word_count = sum(len(ENGLISH_WORD.findall(value)) for value in clean_paragraphs)
    if not 150 <= word_count <= 300:
        raise ValueError(f"product_description英文词数必须为150到300，当前为{word_count}")

    result: dict[str, Any] = {
        "status": "success",
        "product_description": "\n\n".join(clean_paragraphs),
    }
    for field in FEATURE_FIELDS:
        result[field] = _validate_generated_text(parsed[field], field)
    return result
