"""Prompt template rendering helpers for subtasks."""

from __future__ import annotations

import re
from typing import Any

PLACEHOLDER_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


def render_template(
    template: str,
    row: dict[str, Any],
    placeholder_mapping: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Render `{{placeholder}}` values from one source row.

    `placeholder_mapping` maps template placeholder names to row field names.
    When a placeholder is not in the mapping, the placeholder name itself is
    treated as the source row field name.
    """
    missing: list[str] = []
    mapping = placeholder_mapping or {}

    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip()
        field_name = mapping.get(placeholder, placeholder)
        value = row.get(field_name)
        if value is None or value == "":
            missing.append(placeholder)
            return ""
        return str(value)

    return PLACEHOLDER_RE.sub(replace, template), missing


def list_placeholders(template: str) -> list[str]:
    return sorted({match.group(1).strip() for match in PLACEHOLDER_RE.finditer(template)})
