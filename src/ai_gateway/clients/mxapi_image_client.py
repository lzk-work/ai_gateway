"""MXAPI image-generation client."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from ai_gateway.config.loader import GatewayConfig


def validate_image_bytes(content: bytes) -> str:
    """Return the detected raster format or reject HTML/JSON/truncated downloads."""
    if len(content) < 12:
        raise RuntimeError(f"invalid image content: response is too small ({len(content)} bytes)")
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(content) < 24 or int.from_bytes(content[16:20], "big") <= 0 or int.from_bytes(content[20:24], "big") <= 0:
            raise RuntimeError("invalid image content: malformed PNG header")
        if b"IEND" not in content[-32:]:
            raise RuntimeError("invalid image content: truncated PNG")
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        if not content.rstrip().endswith(b"\xff\xd9"):
            raise RuntimeError("invalid image content: truncated JPEG")
        return "jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        if not content.rstrip().endswith(b";"):
            raise RuntimeError("invalid image content: truncated GIF")
        return "gif"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        declared_size = int.from_bytes(content[4:8], "little") + 8
        if declared_size > len(content):
            raise RuntimeError("invalid image content: truncated WebP")
        return "webp"
    if content.startswith(b"BM"):
        return "bmp"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    preview = content[:120].decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
    raise RuntimeError(f"invalid image content: unrecognized file signature; body={preview!r}")


def validate_image_file(path: str | Path) -> bool:
    try:
        image_path = Path(path)
        size = image_path.stat().st_size
        if size < 12:
            return False
        with image_path.open("rb") as handle:
            head = handle.read(32)
            handle.seek(max(size - 32, 0))
            tail = handle.read(32)
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return len(head) >= 24 and int.from_bytes(head[16:20], "big") > 0 \
                and int.from_bytes(head[20:24], "big") > 0 and b"IEND" in tail
        if head.startswith(b"\xff\xd8\xff"):
            return tail.rstrip().endswith(b"\xff\xd9")
        if head.startswith((b"GIF87a", b"GIF89a")):
            return tail.rstrip().endswith(b";")
        if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            return int.from_bytes(head[4:8], "little") + 8 <= size
        return head.startswith((b"BM", b"II*\x00", b"MM\x00*"))
    except (OSError, RuntimeError):
        return False


class MxapiImageClient:
    def __init__(self, gateway: GatewayConfig, submit_endpoint: str, query_endpoint: str) -> None:
        self.gateway = gateway
        self.submit_endpoint = submit_endpoint
        self.query_endpoint = query_endpoint

    def auth_headers(self) -> dict[str, str]:
        header_name = self.gateway.auth_header or "Authorization"
        api_key = self.gateway.api_key()
        if header_name.lower() == "authorization":
            return {header_name: f"Bearer {api_key}"}
        return {header_name: api_key}

    def submit(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        url = self.gateway.base_url.rstrip("/") + self.submit_endpoint
        headers = {
            **self.auth_headers(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ai_gateway_mxapi/1.0",
        }
        started = time.perf_counter()
        response = requests.post(url, headers=headers, json=payload, timeout=self.gateway.timeout_seconds)
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.encoding = "utf-8"
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json(), latency_ms

    def query(self, task_id: str) -> tuple[dict[str, Any], int]:
        url = self.gateway.base_url.rstrip("/") + self.query_endpoint
        headers = {
            **self.auth_headers(),
            "Accept": "application/json",
            "User-Agent": "ai_gateway_mxapi/1.0",
        }
        started = time.perf_counter()
        response = requests.get(url, headers=headers, params={"task_id": task_id}, timeout=self.gateway.timeout_seconds)
        latency_ms = int((time.perf_counter() - started) * 1000)
        response.encoding = "utf-8"
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json(), latency_ms

    def download(self, url: str, path: str | Path, timeout_seconds: int = 60) -> int:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        response.encoding = "utf-8"
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        content = response.content
        if not content:
            raise RuntimeError("downloaded file is empty")
        validate_image_bytes(content)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".part")
        temporary_path.write_bytes(content)
        temporary_path.replace(path)
        size = path.stat().st_size
        if size <= 0:
            raise RuntimeError("saved file is empty")
        return size
