"""Configuration loading for gateway and model settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class GatewayConfig:
    name: str
    type: str
    base_url: str
    api_key_env: str | None = None
    api_key_value: str | None = None
    auth_header: str = "Authorization"
    timeout_seconds: int = 120
    max_retries: int = 3
    extra: dict[str, Any] = field(default_factory=dict)

    def api_key(self) -> str:
        value = self.api_key_value or ""
        if not value and self.api_key_env:
            value = os.environ.get(self.api_key_env, "")
        if not value:
            source = self.api_key_env or "api_key"
            raise RuntimeError(f"Missing API key config: {source}")
        return value


@dataclass(slots=True)
class AppConfig:
    default_gateway: str
    gateways: dict[str, GatewayConfig]
    default_model: str | None = None
    models: dict[str, dict[str, Any]] = field(default_factory=dict)


def load_mapping(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install PyYAML or use JSON config files.") from exc
    data = yaml.safe_load(text)
    return data or {}


def load_local_env(path: str | Path) -> dict[str, str]:
    path = Path(path)
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_app_config(
    gateways_path: str | Path,
    models_path: str | Path | None = None,
    local_env_path: str | Path | None = None,
) -> AppConfig:
    gateways_path = Path(gateways_path)
    if local_env_path is None:
        local_env_path = gateways_path.parent / "local.env"
    local_env = load_local_env(local_env_path)
    for key, value in local_env.items():
        os.environ.setdefault(key, value)

    gateway_data = load_mapping(gateways_path)
    model_data = load_mapping(models_path) if models_path else {}
    gateways: dict[str, GatewayConfig] = {}
    for name, item in gateway_data.get("gateways", {}).items():
        known = {
            "name": name,
            "type": item.get("type", "anthropic_compatible"),
            "base_url": item["base_url"],
            "api_key_env": item.get("api_key_env"),
            "api_key_value": item.get("api_key"),
            "auth_header": item.get("auth_header", "Authorization"),
            "timeout_seconds": int(item.get("timeout_seconds", 120)),
            "max_retries": int(item.get("max_retries", 3)),
        }
        extra = {k: v for k, v in item.items() if k not in known}
        gateways[name] = GatewayConfig(**known, extra=extra)
    return AppConfig(
        default_gateway=gateway_data.get("default_gateway", "buzz"),
        gateways=gateways,
        default_model=model_data.get("default_model"),
        models=model_data.get("models", {}),
    )
