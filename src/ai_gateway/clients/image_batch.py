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
        # Uploads and final workbooks do not identify the image provider. Only
        # generation records carrying an explicit provider are authoritative.
        detected = set()
        for dirname in ("04_generate_images", "04b_generate_main_images"):
            folder = root / dirname
            for filename in ("image_generation_checkpoint.jsonl", "image_generation_results.jsonl"):
                path = folder / filename
                if not path.exists():
                    continue
                with path.open("r", encoding="utf-8-sig") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        row_provider = json.loads(line).get("provider")
                        if row_provider:
                            detected.add(str(row_provider))
        if len(detected) > 1:
            raise RuntimeError(f"批次平台记录冲突: {root.name} 包含 {sorted(detected)}")
        if detected:
            previous = next(iter(detected))
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
