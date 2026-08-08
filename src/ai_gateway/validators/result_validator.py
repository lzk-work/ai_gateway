"""Result validation for structured AI responses."""

from __future__ import annotations

import json
import re
from typing import Any

from ai_gateway.models import AiResult, AiTask

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def validate_result(result: AiResult, task: AiTask) -> AiResult:
    """Validate one result against the task response template.

    The original model text is always kept in `result.text`. Validation details are
    written to `validation_status`, `validation_errors`, and `parsed_json`.
    """
    if not task.response_template:
        result.validation_status = "not_checked"
        return result
    if result.status != "success":
        result.validation_status = "not_checked"
        return result

    parsed, parse_error = extract_json(result.text)
    if parse_error:
        result.validation_status = "failed"
        result.validation_errors = [parse_error]
        return result

    result.parsed_json = parsed
    errors = validate_value(parsed, task.response_template, path="$")
    if errors:
        result.validation_status = "failed"
        result.validation_errors = errors
    else:
        result.validation_status = "passed"
        result.validation_errors = []
    return result


def extract_json(text: str) -> tuple[Any | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, "empty response text"

    candidates = [stripped]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.I)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    first_object = _slice_json_candidate(stripped, "{", "}")
    if first_object:
        candidates.append(first_object)
    first_array = _slice_json_candidate(stripped, "[", "]")
    if first_array:
        candidates.append(first_array)

    for candidate in candidates:
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError:
            continue
    return None, "response is not valid JSON"


def validate_value(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type:
        expected_python_type = TYPE_MAP.get(expected_type)
        if expected_python_type and not isinstance(value, expected_python_type):
            return [f"{path} expected {expected_type}, got {type(value).__name__}"]

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} is required")

        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                errors.extend(validate_value(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_value(item, schema["items"], f"{path}[{index}]"))

    return errors


def _slice_json_candidate(text: str, start_char: str, end_char: str) -> str | None:
    start = text.find(start_char)
    end = text.rfind(end_char)
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
