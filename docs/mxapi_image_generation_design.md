# MXAPI 图片生成实现说明

当前 `walmart_image_prompt` 已使用 MXAPI `gpt-image-2` 同时生成主图和副图。

## 接口

```text
POST https://open.mxapi.org/api/v2/gpt-image-2
GET  https://open.mxapi.org/api/v2/gpt-image/task?task_id=<task_id>
Authorization: Bearer <MXAPI_API_KEY>
```

当前阶段参数：

```json
{
  "model": "gpt-image-2",
  "aspect_ratio": "1:1",
  "quality": "low",
  "resolution": "1K"
}
```

接口地址和模型参数分别来自 `configs/gateways.yaml` 与两个生成阶段的 `config.json`，不在 Python 代码中硬编码密钥。

## 两条生成支路

### 主图

`03b_generate_main_images.py` 先读取源 Excel 的 SKU 和原主图，通过 `scripts/build_main_image_input.py` 生成一行一个 SKU 的入参。提示词来自 `prompts/main_image_optimization_prompt.txt`，阶段使用 `prompt_mode=fixed`，不依赖 BUZZ 的 `image_plan`。

批次产物位于：

```text
03b_build_main_image_input/
04b_generate_main_images/
```

### 副图

`03_generate_and_download_images.py` 先从 BUZZ 校验通过的 `image_plan` 构造每 SKU 6 行入参，再按 `sub1` 至 `sub6` 匹配对应提示词并调用 MXAPI。

Walmart 主图与副图独立执行，副图不再依赖同一 SKU 的主图成功；两类任务可在同一轮分别提交和续跑。

批次产物位于：

```text
03_build_image_input/
04_generate_images/
```

## 异步调用与 checkpoint

共享实现：`src/ai_gateway/subtasks/mxapi_generate_images.py`。

处理过程：

1. 提交任务并取得 `task_id`。
2. 立即写入 checkpoint，状态为 `submitted`。
3. 轮询已有任务直至成功、永久失败或本次超时。
4. 成功后下载图片，保存原始响应并写结果。

续跑规则：

- `success` 跳过。
- `submitted` 或带 `task_id` 的非永久失败继续轮询原任务。
- 轮询超时保留原 `task_id`，下次继续。
- 确认任务永久失败后允许重新提交。
- 没有 `task_id` 的失败记录重新提交。

主图和副图使用独立 checkpoint、结果日志、下载目录和原始响应目录。Excel 和最终结果 JSONL 由主线程合并写入，实时恢复依据是 checkpoint。

## 并发与数量口径

- 并发来自根配置 `execution.image_concurrency`。
- `execution.max_records` 按 SKU 控制。
- 每个 SKU 当前最多展开 1 个主图任务和 6 个副图任务。
- 图片任务的完成顺序可能与 Excel 顺序不同，合并结果按源任务关系处理。

## 验证

不调用接口的检查命令：

```powershell
python subtasks/walmart_image_prompt/03b_generate_main_images.py --dry-run
python subtasks/walmart_image_prompt/03_generate_and_download_images.py --dry-run
```

dry-run 会读取现有入参和 checkpoint，打印任务总量、成功跳过量、blocked 数量及本次待处理量，不生成模板、不提交任务、不下载图片。
