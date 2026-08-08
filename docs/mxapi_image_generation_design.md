# MXAPI gpt-image-2 图片生成接入设计

## 可行性结论

可行。MXAPI `gpt-image-2` 是异步图片生成接口，流程与当前系统的阶段化批处理模型匹配：

1. 提交生成任务。
2. 获取 `task_id`。
3. 轮询任务状态。
4. 任务完成后读取图片 URL。
5. 下载图片并写回结果。

官方文档：

- API 指南：https://open.mxapi.org/api-guide
- gpt-image-2 调试页：https://open.mxapi.org/api-test?id=v2-gpt-image-2

## 官方接口要点

提交接口：

```text
POST https://open.mxapi.org/api/v2/gpt-image-2
Authorization: Bearer <MXAPI_API_KEY>
Content-Type: application/json
```

核心入参：

```json
{
  "prompt": "图片生成提示词",
  "aspect_ratio": "1:1",
  "quality": "low",
  "resolution": "1K",
  "reference_images": ["参考图片URL"]
}
```

查询接口：

```text
GET https://open.mxapi.org/api/v2/gpt-image/task?task_id=<task_id>
Authorization: Bearer <MXAPI_API_KEY>
```

完成后优先读取：

```text
source_images
proxy_images
images
```

## 当前系统接入方式

新增全局网关：

```text
configs/gateways.yaml -> mxapi
```

使用环境变量：

```text
MXAPI_API_KEY
```

不要在代码里硬编码密钥。

新增业务阶段：

```text
subtasks/walmart_image_prompt/stages/generate_sub_images/
```

新增阶段实现：

```text
src/ai_gateway/subtasks/mxapi_generate_images.py
```

新增业务入口脚本：

```text
subtasks/walmart_image_prompt/03_generate_and_download_images.py
```

## 数据来源

输入 Excel：

```text
stages/build_sub_image_download_input/output/walmart_sub_image_input_result.xlsx
```

Prompt 来源：

```text
stages/call_prompt_model/output/model_results.jsonl
stages/call_prompt_model/output/full_outputs/
```

系统会根据：

- SKU
- 图片命名里的 `sub1` 到 `sub6`

自动匹配对应 `image_plan` 中的图片生成提示词。

## 输出

结果 Excel：

```text
stages/generate_sub_images/output/walmart_sub_image_generation_result.xlsx
```

轻量结果日志：

```text
stages/generate_sub_images/output/image_generation_results.jsonl
```

下载图片目录：

```text
stages/generate_sub_images/output/downloaded_images/
```

原始查询响应：

```text
stages/generate_sub_images/output/raw_responses/
```

## 批量与断点续跑

- 成功记录会跳过。
- 失败记录会重试。
- 如果 Excel 中已有 `task_id`，会优先继续轮询已有任务。
- 图片生成并发由业务总配置 `image_concurrency` 控制。
- 写 Excel 和 JSONL 在主线程统一完成，避免并发写乱。

## 运行命令

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\03_generate_and_download_images.py
```

## 实时 Checkpoint 与断点续跑

图片生成阶段已加入实时 checkpoint：

```text
stages/generate_sub_images/output/image_generation_checkpoint.jsonl
```

关键节点会立即落盘：

- 提交成功拿到 `task_id`：立即写入 `status=submitted`。
- 轮询完成并下载成功：更新为 `status=success`。
- 失败：写入 `status=failed` 和错误摘要。

这样即使手动中断，已经提交到 MXAPI 的 `task_id` 也不会丢。下次运行会读取 checkpoint：

- `success` 跳过。
- `submitted` 或带 `task_id` 的失败记录会继续轮询。
- 没有 `task_id` 的失败记录会重新提交。

Excel 仍然最后统一写回，避免并发频繁打开 Excel 导致锁文件或写乱。
