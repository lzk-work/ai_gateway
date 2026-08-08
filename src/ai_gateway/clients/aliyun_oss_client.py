"""Aliyun OSS client wrapper."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_gateway.config.loader import load_local_env


@dataclass(slots=True)
class AliyunOssConfig:
    access_key_id: str
    access_key_secret: str
    endpoint: str
    bucket: str
    default_prefix: str = "images"
    max_retries: int = 3
    connect_timeout: int = 30


class AliyunOssClient:
    def __init__(self, config: AliyunOssConfig) -> None:
        try:
            import oss2  # type: ignore
        except ImportError as exc:
            raise RuntimeError("缺少 oss2 依赖，请先安装：pip install oss2") from exc

        self.config = config
        self.default_prefix = config.default_prefix.strip("/")
        auth = oss2.Auth(config.access_key_id, config.access_key_secret)
        self.bucket = oss2.Bucket(
            auth,
            config.endpoint,
            config.bucket,
            connect_timeout=config.connect_timeout,
        )

    def object_key(self, key: str) -> str:
        key = key.replace("\\", "/").lstrip("/")
        if self.default_prefix:
            return f"{self.default_prefix}/{key}"
        return key

    def exists(self, key: str) -> bool:
        return bool(self.bucket.object_exists(self.object_key(key)))

    def upload_file(self, local_path: str | Path, key: str, overwrite: bool = True) -> dict[str, Any]:
        local_path = Path(local_path)
        full_key = self.object_key(key)
        if not local_path.is_file():
            return {"success": False, "error": "file not found", "oss_key": full_key}
        if not overwrite and self.bucket.object_exists(full_key):
            return {
                "success": True,
                "skipped": True,
                "oss_key": full_key,
                "size": local_path.stat().st_size,
            }

        last_error: str | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                self.bucket.put_object_from_file(full_key, str(local_path))
                return {
                    "success": True,
                    "skipped": False,
                    "oss_key": full_key,
                    "size": local_path.stat().st_size,
                    "attempt": attempt,
                }
            except Exception as exc:
                last_error = str(exc)
                if attempt < self.config.max_retries:
                    time.sleep(attempt)
        return {"success": False, "error": last_error, "oss_key": full_key}

    def public_url(self, key: str) -> str:
        endpoint = self.config.endpoint.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{self.config.bucket}.{endpoint}/{self.object_key(key)}"


def load_aliyun_oss_config(project_root: str | Path) -> AliyunOssConfig:
    project_root = Path(project_root)
    local_env = load_local_env(project_root / "configs" / "local.env")
    for key, value in local_env.items():
        os.environ.setdefault(key, value)

    def env(name: str, default: str = "") -> str:
        return os.environ.get(name, default).strip()

    access_key_id = env("ALIYUN_OSS_ACCESS_KEY_ID")
    access_key_secret = env("ALIYUN_OSS_ACCESS_KEY_SECRET")
    endpoint = env("ALIYUN_OSS_ENDPOINT")
    bucket = env("ALIYUN_OSS_BUCKET")
    missing = [
        name
        for name, value in {
            "ALIYUN_OSS_ACCESS_KEY_ID": access_key_id,
            "ALIYUN_OSS_ACCESS_KEY_SECRET": access_key_secret,
            "ALIYUN_OSS_ENDPOINT": endpoint,
            "ALIYUN_OSS_BUCKET": bucket,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("缺少 OSS 环境配置：" + ", ".join(missing))

    return AliyunOssConfig(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint=endpoint,
        bucket=bucket,
        default_prefix=env("ALIYUN_OSS_DEFAULT_PREFIX", "images"),
        max_retries=int(env("ALIYUN_OSS_MAX_RETRIES", "3")),
        connect_timeout=int(env("ALIYUN_OSS_CONNECT_TIMEOUT", "30")),
    )


def build_public_url_without_client(bucket: str, endpoint: str, default_prefix: str, key: str) -> str:
    endpoint = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
    default_prefix = default_prefix.strip("/")
    key = key.replace("\\", "/").lstrip("/")
    full_key = f"{default_prefix}/{key}" if default_prefix else key
    return f"https://{bucket}.{endpoint}/{full_key}"
