"""Platform-specific async image contracts; no routing or business rules here."""
from contextlib import ExitStack
from dataclasses import dataclass, field
import mimetypes
from pathlib import Path
import time
from urllib.parse import urlparse

import requests

from ai_gateway.clients.mxapi_image_client import MxapiImageClient


class ImageProtocolError(RuntimeError):
    pass


class SubmissionUnknown(ImageProtocolError):
    """Creation may have reached upstream; retries can create duplicate tasks."""


@dataclass
class ImagePollResult:
    status: str
    urls: list[str] = field(default_factory=list)
    error: str = ""
    b64_images: list[str] = field(default_factory=list)


class MxapiImageAdapter(MxapiImageClient):
    provider = "mxapi"

    def build_payload(self, prompt, reference_image, config):
        references = list(reference_image) if isinstance(reference_image, (list, tuple)) else [reference_image]
        references = [str(item).strip() for item in references if str(item).strip()]
        return {"prompt": prompt, "aspect_ratio": config.aspect_ratio,
                "quality": config.quality, "resolution": config.resolution,
                "reference_images": references}

    def parse_submit(self, payload):
        if payload.get("code") != 200:
            raise ImageProtocolError(str(payload.get("message") or payload)[:1000])
        task_id = (payload.get("data") or {}).get("task_id")
        if not task_id:
            raise ImageProtocolError("No task_id in submit response")
        return str(task_id)

    def parse_query(self, payload):
        if payload.get("code") != 200:
            raise ImageProtocolError(str(payload.get("message") or payload)[:1000])
        data = payload.get("data") or {}
        status = data.get("status")
        if status == "failed":
            return ImagePollResult("failed", error=str(data.get("error_msg") or data.get("error") or "task failed"))
        if status == "completed":
            return ImagePollResult("completed", self.image_urls(payload))
        return ImagePollResult("pending")

    @staticmethod
    def image_urls(payload):
        result = ((payload.get("data") or {}).get("result") or {})
        urls = []
        for key in ("source_images", "proxy_images", "images"):
            values = result.get(key) or []
            if isinstance(values, list):
                urls.extend(str(item) for item in values if item)
        return list(dict.fromkeys(urls))


class TuziImageAdapter(MxapiImageClient):
    provider = "tuzi"

    def __init__(self, gateway, submit_endpoint="/v1/videos", query_endpoint="/v1/videos"):
        super().__init__(gateway, submit_endpoint, query_endpoint)

    def build_payload(self, prompt, reference_image, config):
        size = config.size or {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}.get(config.aspect_ratio)
        if not size or (not config.size and config.resolution.upper() != "1K"):
            raise ImageProtocolError("Tuzi requires an explicit supported size for this aspect_ratio/resolution")
        if size not in {"auto", "1024x1024", "1536x1024", "1024x1536", "2048x2048"}:
            raise ImageProtocolError(f"Unsupported Tuzi size: {size}")
        if config.quality not in {"auto", "low", "medium", "high"}:
            raise ImageProtocolError(f"Unsupported Tuzi quality: {config.quality}")
        references = list(reference_image) if isinstance(reference_image, (list, tuple)) else [reference_image]
        references = [str(item).strip() for item in references if str(item).strip()]
        return {"model": config.model, "prompt": prompt,
                "input_reference": references, "size": size}

    def submit(self, payload):
        """Submit TUZI's multipart image task; repeated input_reference supports multiple URLs/files."""
        parts = [
            ("model", (None, str(payload["model"]))),
            ("prompt", (None, str(payload["prompt"]))),
            ("size", (None, str(payload["size"]))),
        ]
        with ExitStack() as stack:
            for reference in payload.get("input_reference", []):
                parsed = urlparse(reference)
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    parts.append(("input_reference", (None, reference)))
                else:
                    path = Path(reference)
                    handle = stack.enter_context(path.open("rb"))
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    parts.append(("input_reference", (path.name, handle, content_type)))
            started = time.perf_counter()
            response = requests.post(
                self.gateway.base_url.rstrip("/") + self.submit_endpoint,
                headers={**self.auth_headers(), "Accept": "application/json"},
                files=parts,
                timeout=self.gateway.timeout_seconds,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json(), latency_ms

    def parse_submit(self, payload):
        task_id = payload.get("task_id") or payload.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise SubmissionUnknown("Tuzi submit response missing async id")
        return task_id

    def query(self, task_id):
        started = time.perf_counter()
        headers = {**self.auth_headers(), "Accept": "application/json"}
        response = requests.get(
            self.gateway.base_url.rstrip("/") + self.query_endpoint.rstrip("/") + f"/{task_id}",
            headers=headers,
            timeout=self.gateway.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:1000]}")
        return response.json(), int((time.perf_counter() - started) * 1000)

    def parse_query(self, payload):
        if not isinstance(payload, dict):
            raise ImageProtocolError("Tuzi query response must be an object")
        status = payload.get("status")
        if status in {"queued", "not_start", "submitted", "in_progress", "expired"}:
            return ImagePollResult("pending")
        if status in {"failure", "failed"}:
            return ImagePollResult("failed", error=str(payload.get("error") or payload.get("message") or "Tuzi task failed"))
        if status != "completed":
            raise ImageProtocolError(f"Unknown Tuzi async status: {status!r}")
        video_url = payload.get("video_url")
        if isinstance(video_url, str) and urlparse(video_url).scheme in {"https", "http"} and urlparse(video_url).netloc:
            return ImagePollResult("completed", [video_url])
        raise ImageProtocolError("Tuzi /v1/videos completed response has no valid video_url")


def create_image_adapter(provider, gateway, submit_endpoint, query_endpoint):
    cls = {"mxapi": MxapiImageAdapter, "tuzi": TuziImageAdapter}.get(provider)
    if cls is None:
        raise ValueError(f"Unsupported image provider: {provider}")
    if provider == "tuzi":
        # TUZI's active protocol is owned by its adapter.
        return cls(gateway)
    return cls(gateway, submit_endpoint, query_endpoint)
