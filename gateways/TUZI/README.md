# 兔子 TUZI：异步图片生成

更新：2026-09-08。本文以当前 `/v1/videos` 图片异步协议和实测结果为准。

## 配置和代码

- Base URL：`https://api.tu-zi.com`，网关名：`tuzi`。
- [网关配置](../../configs/gateways.yaml)：当前 HTTP 超时 120 秒；密钥变量 `TUZI_API_KEY`，在 `configs/local.env` 或进程环境配置。
- 鉴权：`Authorization: Bearer <API_KEY>`；不要将密钥放入 URL、文档或日志。
- [业务总配置](../../subtasks/walmart_image_prompt/config.json)：`"image_provider": "tuzi"`。
- [解析器](../../src/ai_gateway/clients/image_providers.py)：`TuziImageAdapter.build_payload / parse_submit / query / parse_query`。
- [主图](../../subtasks/walmart_image_prompt/stages/generate_main_image/config.json)与[副图](../../subtasks/walmart_image_prompt/stages/generate_sub_images/config.json)的 `execution.model` 控制模型和图片参数；端点由业务入口覆盖。

## 当前采用的协议

提交：`POST /v1/videos`，请求体为 `multipart/form-data`。URL 和本地文件都使用同名的 `input_reference` 字段；重复该字段即可传多图。示意：

```text
model=gpt-image-2-1k
prompt=保持参考商品外观，生成干净背景的产品摄影
input_reference=https://example.com/reference-1.png
input_reference=https://example.com/reference-2.png
size=1024x1024
```

当前业务参考图是 URL，因此直接作为 multipart 文本 part 提交，不需要先下载。本地路径则作为文件 part 上传。

实测提交返回 HTTP 200：

```json
{"id": "task_example", "status": "queued"}
```

查询：`GET /v1/videos/task_example`，使用相同平台鉴权。成功响应的关键结构如下：

```json
{
  "id": "task_example",
  "status": "completed",
  "object": "video",
  "model": "gpt-image-2-1k",
  "status": "completed",
  "progress": 100,
  "video_url": "https://example.com/result.png"
}
```

新旧协议的 task_id 外观相同但后台渠道不通用。当前流程不会自动回查 `/get-async`，也不允许在同一批次混用两套协议；新批次的提交与查询始终配套使用 `/v1/videos`。旧接口仅保留为未来人工评估的整体备用方案。

## 解析和恢复规则

| 字段/状态 | 当前代码处理 |
|---|---|
| 提交 `id` | 必须是非空字符串；缺失视为提交结果未知 |
| `queued / not_start / submitted / in_progress` | 保留 task_id，下一轮继续查询 |
| `failure / failed` | 明确任务失败 |
| `expired` | 视为查询端暂时不可用，继续保留原 task_id 到下一轮 |
| 未知状态 | 报协议错误，不假定成功，保留已获得的任务 ID |
| `completed` | 必须包含合法的 HTTP(S) `video_url` |
| 图片结果 | 从 `video_url` 下载并校验非空图片文件 |

提交前先落盘 submission_unknown 意图，获得任务 ID 后写入 submitted。兔子提交重试只读取 configs/gateways.yaml 的 gateways.tuzi.max_retries：2 表示首次失败后再重试两次，共最多三次；0 表示只提交一次，不读取阶段 retry.max_submit_retries。重试间隔仍由阶段 retry.retry_delay_seconds 控制。

提交异常或未取得 ID 时有限重试，耗尽后记为可续跑的 failed，继续处理其他图片。进程中断留下的 submission_unknown 在下次运行时告警并重新尝试。不清理旧记录。此策略优先推进流程，可能重复生成、重复扣费；目前未按鉴权、余额、参数等错误进一步区分提交重试资格。

当前 Walmart 流程采用批量延迟查询：新任务提交并落盘 task_id 后立即处理下一张，不在同一轮等待。后续整轮由业务配置 `scheduler.interval_seconds` 控制（默认 3 小时）；每轮从 01 开始，查询已有任务、下载完成结果、补交缺口，再执行增量上传。HTTP 410/503、网络临时异常以及 HTTP 200 的 `status=expired` 均保留原 task_id，不重新生成；只有平台明确返回 failed 或结果链接确认失效时才允许补交。

每轮对每个 task_id 总共最多查询 3 次。首次查询返回排队、处理中或临时查询异常后等待 `retry.query_retry_delay_seconds`（当前 5 秒），再追加最多两次查询，最长额外等待 10 秒。这里仅用于吸收网络或查询端波动，不在当前轮等待异步生成结束；三次仍未取得明确结果时标记 pending 并保留 task_id，等待下一轮。下载及提交失败仍使用原 `retry_delay_seconds`。

## 参数范围（当前适配器）

- 当前 multipart 请求传递 `model / prompt / input_reference / size`；模型档位由模型名（如 `gpt-image-2-1k`）确定。
- `input_reference` 支持 URL、本地文件和重复字段多图。
- 可在 `execution.model.size` 显式设置 `auto / 1024x1024 / 1536x1024 / 1024x1536 / 2048x2048`。
- 未设置 size 时，仅允许 `resolution=1K`，按 `aspect_ratio` 映射：`1:1 → 1024x1024`、`3:2 → 1536x1024`、`2:3 → 1024x1536`。
- 不支持的比例、尺寸组合会在提交前报错，不静默降级。

## 两套异步接口实测

2026-09-04 使用用户授权的临时 Token，各提交一次 `gpt-image-2` 文生图；相同提示词，均指定 `size=1024x1024`、`quality=low`、`n=1`、PNG、URL 输出。Token 未写入项目。

| 对比 | 旧图片异步接口（仅历史兼容） | 当前 `/v1/videos` 接口 |
|---|---|---|
| 提交 | `/async/v1/images/generations` | `/v1/videos` |
| 提交 HTTP | 202 | 200 |
| 查询 | `/get-async?id=<id>` | `/v1/videos/<id>` |
| 最终状态 | completed | completed |
| 结果字段 | `result.data[0].url` | `video_url` |
| 图片实际格式与尺寸 | PNG，1024×1024 | PNG，1254×1254 |
| 实际字节数 | 1,137,508 | 1,318,921 |
| 图片读取与完整性校验 | 通过 | 通过 |

2026-09-08 使用 `gpt-image-2-1k`、URL 参考图、5 并发完成 10 个真实任务：10/10 提交、查询和 PNG 下载成功，查询错误为 0，单任务端到端耗时 46.4–67.5 秒。因此当前业务切换为 `/v1/videos`；旧接口不再参与运行，也不自动用于历史 task_id 查询。该样本证明当前参数和并发可用，但不等同于长期 SLA。

## 官方资料

- [创建图片任务](https://tuzi-api.apifox.cn/472418522e0)
- [查询图片任务](https://tuzi-api.apifox.cn/472418529e0)
- [统一异步任务协议](https://api.tu-zi.com/docs/use-cases/async-tasks)
- [原生视频任务协议](https://api.tu-zi.com/docs/api/video)

官方示例与实际渠道可能存在差异，以上解析说明以当前项目代码和此次实测为准。
