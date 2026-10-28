from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TaskDefinition:
    name: str
    version: str
    root: Path
    data: dict[str, Any]
    prompt: str

    @property
    def input(self) -> dict[str, Any]:
        return self.data.get("input", {})

    @property
    def gateway(self) -> dict[str, Any]:
        return self.data.get("gateway", {})

    @property
    def execution(self) -> dict[str, Any]:
        return self.data.get("execution", {})

    @property
    def response(self) -> dict[str, Any]:
        return self.data.get("response", {"type": "raw_text"})


def load_task(tasks_root: Path, name: str) -> TaskDefinition:
    root = tasks_root / name
    path = root / "task.json"
    if not path.exists():
        available = ", ".join(sorted(item.name for item in tasks_root.iterdir() if item.is_dir())) if tasks_root.exists() else "无"
        raise FileNotFoundError(f"任务不存在: {name}；可用任务: {available}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    task = data.get("task", {})
    actual_name = str(task.get("name") or name)
    if actual_name != name:
        raise ValueError(f"任务目录名与 task.name 不一致: {name} != {actual_name}")
    prompt_path = root / data.get("prompt", {}).get("template", "prompt.txt")
    prompt = prompt_path.read_text(encoding="utf-8-sig").strip()
    return TaskDefinition(actual_name, str(task.get("version") or "1.0.0"), root, data, prompt)
