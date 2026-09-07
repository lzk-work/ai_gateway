"""Platform-specific async image contracts; no routing or business rules here."""
from dataclasses import dataclass, field
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


class MxapiImageAdapter(MxapiImageClient):
    provider = "mxapi"

    def build_payload(self, prompt, reference_image, config):
        return {"prompt": prompt, "aspect_ratio": config.aspect_ratio,
                "quality": config.quality, "resolution": config.resolution,
                "reference_images": [reference_image]}

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

    def __init__(self, gateway, submit_endpoint="/async/v1/images/generations", query_endpoint="/get-async"):
        super().__init__(gateway, submit_endpoint, query_endpoint)

    def build_payload(self, prompt, reference_image, config):
        size = config.size or {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}.get(config.aspect_ratio)
        if not size or (not config.size and config.resolution.upper() != "1K"):
            raise ImageProtocolError("Tuzi requires an explicit supported size for this aspect_ratio/resolution")
        if size not in {"auto", "1024x1024", "1536x1024", "1024x1536"}:
            raise ImageProtocolError(f"Unsupported Tuzi size: {size}")
        if config.quality not in {"auto", "low", "medium", "high"}:
            raise ImageProtocolError(f"Unsupported Tuzi quality: {config.quality}")
        return {"model": config.model, "prompt": prompt, "image": [reference_image],
                "size": size, "quality": config.quality, "n": 1,
                "output_format": "png", "response_format": "url"}

    def parse_submit(self, payload):
        task_id = payload.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise SubmissionUnknown("Tuzi submit response missing async id")
        return task_id

    def query(self, task_id):
        import time
        started = time.perf_counter()
        response = requests.get(self.gateway.base_url.rstrip("/") + self.query_endpoint,
                                headers={**self.auth_headers(), "Accept": "application/json"},
                                params={"id": task_id}, timeout=self.gateway.timeout_seconds)
        response.raise_for_status()
        return response.json(), int((time.perf_counter() - started) * 1000)

    def parse_query(self, payload):
        if not isinstance(payload, dict):
            raise ImageProtocolError("Tuzi query response must be an object")
        status = payload.get("status")
        if status in {"queued", "not_start", "submitted", "in_progress"}:
            return ImagePollResult("pending")
        if status in {"failure", "failed"}:
            return ImagePollResult("failed", error=str(payload.get("error") or payload.get("message") or "Tuzi task failed"))
        if status == "expired":
            raise ImageProtocolError("Tuzi result expired; verify upstream before creating another task")
        if status != "completed":
            raise ImageProtocolError(f"Unknown Tuzi async status: {status!r}")
        code = payload.get("status_code", 200)
        if not isinstance(code, int) or not 200 <= code < 300:
            raise ImageProtocolError(f"Tuzi inner HTTP status: {code}; inspect saved task before retry")
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("error"):
            raise ImageProtocolError("Tuzi completed response has invalid/error result")
        data = result.get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise ImageProtocolError("Tuzi n=1 response must contain exactly one result.data item")
        item = data[0]
        url = item.get("url") if isinstance(item, dict) else None
        if not isinstance(url, str) or urlparse(url).scheme not in {"https", "http"} or not urlparse(url).netloc:
            raise ImageProtocolError("Tuzi result missing HTTP image URL (Base64 output is not enabled)")
        return ImagePollResult("completed", [url])


def create_image_adapter(provider, gateway, submit_endpoint, query_endpoint):
    cls = {"mxapi": MxapiImageAdapter, "tuzi": TuziImageAdapter}.get(provider)
    if cls is None:
        raise ValueError(f"Unsupported image provider: {provider}")
    return cls(gateway, submit_endpoint, query_endpoint)
