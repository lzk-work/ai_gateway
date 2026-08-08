"""MXAPI image-generation client."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from ai_gateway.config.loader import GatewayConfig


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
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json(), latency_ms

    def download(self, url: str, path: str | Path, timeout_seconds: int = 60) -> int:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        content = response.content
        if not content:
            raise RuntimeError("downloaded file is empty")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        size = path.stat().st_size
        if size <= 0:
            raise RuntimeError("saved file is empty")
        return size
