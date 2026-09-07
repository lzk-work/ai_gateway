"""Bind a whole image batch to exactly one platform, without migrating tasks."""
import json
from pathlib import Path


def check_batch_provider(root, provider, *, bind=False):
    if provider not in {"tuzi", "mxapi"}:
        raise ValueError(f"Unsupported image_provider: {provider}")
    root = Path(root)
    marker = root / "image_provider.json"
    previous = None
    if marker.exists():
        previous = json.loads(marker.read_text(encoding="utf-8"))["provider"]
    else:
        # Empty directories created by a preview are not evidence of a platform.
        for dirname in ("04_generate_images", "04b_generate_main_images", "05_upload_oss", "05b_upload_main_oss"):
            folder = root / dirname
            if folder.exists() and any(p.is_file() and p.stat().st_size for p in folder.rglob("*")):
                previous = "mxapi"
                break
    if previous and previous != provider:
        raise RuntimeError(f"批次平台冲突: {root.name} 属于 {previous}，当前选择 {provider}。请使用新批次，或切回原平台续跑。")
    if bind and not marker.exists():
        root.mkdir(parents=True, exist_ok=True)
        try:
            with marker.open("x", encoding="utf-8") as handle:
                json.dump({"version": 1, "provider": provider}, handle)
        except FileExistsError:
            check_batch_provider(root, provider)
    return previous or provider
