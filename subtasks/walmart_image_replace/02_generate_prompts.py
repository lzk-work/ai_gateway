"""Step 02: Generate image prompts via BUZZ (real) -> model_results + full_outputs.

输出与 walmart_image_prompt 的 02 阶段同构，供共享模块
ai_gateway.subtasks.mxapi_generate_images.load_prompt_map 直接消费：
  - model_results.jsonl: 每行 {sku, status, validation_status, full_output_path, ...}
  - full_outputs/<sku>.json: {global_prompt_restrictions, image_plan: [{image_number, ai_image_generation_prompt}]}

其中 sku = OSS路径/开发SKU（图片流水线主键：同一图片目录去重生成一次；
OSS 目录结构 {OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png，新图与已有图同目录），
image_number = 缺失位置（与 new_sub{位置}_{开发SKU} 命名一致）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

# 允许从任务目录单独运行：把项目 src 加入导入路径
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from ai_gateway.subtasks.template_renderer import render_template
from workflow_common import batch_paths, ensure_dirs, load_jsonl, load_local_env, print_batch_info

BUZZ_URL = "https://buzzai.cc/v1/chat/completions"
BUZZ_MODEL = "gpt-5.4"
TASK_ROOT = Path(__file__).resolve().parent
PROMPT_TEMPLATE_PATH = TASK_ROOT / "prompts" / "walmart_image_replace_template.txt"

SYSTEM_PROMPT = (
    "You are an expert e-commerce product image prompt engineer for Walmart. "
    "Given a product's title and bullet points, write ONE concise, vivid AI image-generation "
    "prompt for a Walmart secondary/lifestyle product photo: professional e-commerce look, "
    "clean or contextual background, the product clearly visible. "
    "Return ONLY the prompt text, no explanation, no quotation marks."
)


def safe_file_key(oss_path: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "__", oss_path.strip())
    return cleaned.strip("._-") or "unnamed"


def build_user_prompt(title: str, bullets: str) -> str:
    """优先从 prompts/walmart_image_replace_template.txt 渲染（支持 {{产品标题}}/{{产品五点}}）；
    文件缺失时回退内联模板。"""
    if PROMPT_TEMPLATE_PATH.exists():
        template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8-sig")
        rendered, _missing = render_template(
            template,
            {"产品标题": title, "产品五点": bullets},
        )
        return rendered
    return f"Title: {title}\nBullets: {bullets}\n\nWrite the image generation prompt."


def call_buzz_prompt(title: str, bullets: str) -> str:
    """调 BUZZ (OpenAI 兼容) 生成一条副图提示词。失败直接抛异常，由调用方决定如何处理。"""
    key = os.environ.get("BUZZ_API_KEY") or load_local_env().get("BUZZ_API_KEY", "")
    if not key:
        raise RuntimeError("未配置 BUZZ_API_KEY（local.env 或环境变量）")
    payload = {
        "model": BUZZ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(title, bullets)},
        ],
        "temperature": 0.2,
        "max_tokens": 800,
    }
    resp = requests.post(
        BUZZ_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"].strip()
    if not text:
        raise RuntimeError("BUZZ 返回空提示词")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="02 生成提示词")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写输出。")
    parser.add_argument("--batch-name", default=None)
    args = parser.parse_args()

    print("\n=== 02 生成提示词（真实 BUZZ）===")
    print_batch_info(args.batch_name)
    paths = ensure_dirs(args.batch_name)
    inventory = load_jsonl(paths["inventory"])
    if not inventory:
        msg = "未找到 image_inventory.jsonl，请先运行 01"
        if args.dry_run:
            print(msg + "（dry-run 跳过本阶段预览）")
            return
        raise SystemExit(msg)

    # 按 OSS路径/开发SKU 去重：同一图片目录只生成一次提示词
    seen: set[str] = set()
    records = []
    for rec in inventory:
        oss_path = str(rec.get("oss_image_path", "")).strip()
        dev_sku = str(rec.get("dev_sku", "")).strip()
        # 图片流水线主键 = OSS路径/开发SKU（04 上传 key_template {sku}/{image_name}.png 渲染出的
        # 对象路径 = {OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png，与已有图同目录）
        image_key = f"{oss_path.rstrip('/')}/{dev_sku}" if oss_path and dev_sku else oss_path
        if not image_key or image_key in seen:
            continue
        seen.add(image_key)
        copy = " ".join([
            rec.get("title", ""),
            rec.get("bullets", ""),
            rec.get("main_image_url", ""),
        ]).strip()
        # 真实 BUZZ：按 (标题+五点) 生成一条副图提示词，复用到该 SKU 所有缺失位置
        # 失败时直接抛异常（不再静默回退 mock），确保产物真实可信
        buzz_prompt = call_buzz_prompt(rec.get("title", ""), rec.get("bullets", ""))
        source = "buzz"
        image_plan = []
        for p in rec["missing_positions"]:
            image_plan.append({
                "image_number": p,
                "image_type": "",
                "ai_image_generation_prompt": buzz_prompt,
            })
        records.append({
            "sku": image_key,
            "platform_skus": [rec["platform_sku"]],
            "dev_sku": dev_sku,
            "to_generate": rec["to_generate"],
            "copywriting": copy,
            "prompt_source": source,
            "image_plan": image_plan,
        })

    if args.dry_run:
        total = sum(r["to_generate"] for r in records)
        print(f"试运行: 不写 model_results.jsonl；共 {len(records)} 个图片目录（去重后），需生成提示词 {total} 条")
        for rec in records[:10]:
            print(f"  图片目录={rec['sku']} dev_sku={rec['dev_sku']} 提示词={rec['to_generate']} 条")
        return

    now = datetime.now().isoformat(timespec="seconds")
    paths["full_outputs"].mkdir(parents=True, exist_ok=True)
    with open(paths["model_results"], "w", encoding="utf-8") as f:
        for rec in records:
            full_output_path = paths["full_outputs"] / f"{safe_file_key(rec['sku'])}.json"
            full_output_path.write_text(
                json.dumps({
                    "global_prompt_restrictions": "",
                    "image_plan": rec["image_plan"],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            f.write(json.dumps({
                "sku": rec["sku"],
                "status": "success",
                "validation_status": "passed",
                "full_output_path": str(full_output_path),
                "platform_skus": rec["platform_skus"],
                "dev_sku": rec["dev_sku"],
                "to_generate": rec["to_generate"],
                "prompt_source": rec.get("prompt_source", "buzz"),
                "created_at": now,
            }, ensure_ascii=False) + "\n")
    print(f"已写出提示词: {len(records)} 个图片目录 -> {paths['model_results']}（full_outputs 同步生成，全部由真实 BUZZ 生成）")


if __name__ == "__main__":
    main()
