# 兔子 TUZI：异步图片生成

更新：2026-09-04。本文区分项目实现、真实测试和未验证能力，以免将文生图成功当作完整业务验收。

## 配置和代码

- Base URL：`https://api.tu-zi.com`，网关名：`tuzi`。
- [网关配置](../../configs/gateways.yaml)：当前 HTTP 超时 120 秒；密钥变量 `TUZI_API_KEY`，在 `configs/local.env` 或进程环境配置。
- 鉴权：`Authorization: Bearer <API_KEY>`；不要将密钥放入 URL、文档或日志。
- [业务总配置](../../subtasks/walmart_image_prompt/config.json)：`"image_provider": "tuzi"`。
- [解析器](../../src/ai_gateway/clients/image_providers.py)：`TuziImageAdapter.build_payload / parse_submit / query / parse_query`。
- [主图](../../subtasks/walmart_image_prompt/stages/generate_main_image/config.json)与[副图](../../subtasks/walmart_image_prompt/stages/generate_sub_images/config.json)的 `execution.model` 控制模型和图片参数；端点由业务入口覆盖。

## 当前采用的协议

提交：`POST /async/v1/images/generations`，JSON 示例：

```json
{
  "model": "gpt-image-2",
  "prompt": "保持参考商品外观，生成干净背景的产品摄影",
  "image": ["https://example.com/reference.png"],
  "size": "1024x1024",
  "quality": "low",
  "n": 1,
  "output_format": "png",
  "response_format": "url"
}
```

这是当前业务适配器构造的请求。`image` 参考图效果尚未真实验证；本次接口测试只发送文本提示词，未带参考图。

实测提交返回 HTTP 202：

```json
{"id": "task_example", "status": "queued"}
```

查询：`GET /get-async?id=task_example`，使用相同平台鉴权。成功响应的关键结构如下（已精简，任务 ID 和 URL 为占位符）：

```json
{
  "id": "task_example",
  "status": "completed",
  "status_code": 200,
  "content_type": "application/json; charset=utf-8",
  "result": {
    "created": 1788514634,
    "data": [{"revised_prompt": "...", "url": "https://example.com/result.png"}],
    "usage": {}
  }
}
```

## 解析和恢复规则

| 字段/状态 | 当前代码处理 |
|---|---|
| 提交 `id` | 必须是非空字符串；缺失视为提交结果未知 |
| `queued / not_start / submitted / in_progress` | 等待，继续查询 |
| `failure / failed` | 明确任务失败 |
| `expired` 或未知状态 | 报错，不假定成功，保留已获得的任务 ID |
| `completed` | 检查 `status_code` 和 `result.data` 后才能成功 |
| `status_code` | 存在时须是 2xx 整数；当前实现缺失时默认 200 |
| 图片结果 | `result` 须为无 error 的对象，`data` 恰好一项，`url` 须为 HTTP(S) URL |
| Base64 | 当前业务不支持，报错而不是误记成功 |

提交前先落盘 submission_unknown 意图，获得任务 ID 后写入 submitted。兔子提交重试只读取 configs/gateways.yaml 的 gateways.tuzi.max_retries：2 表示首次失败后再重试两次，共最多三次；0 表示只提交一次，不读取阶段 retry.max_submit_retries。重试间隔仍由阶段 retry.retry_delay_seconds 控制。

提交异常或未取得 ID 时有限重试，耗尽后记为可续跑的 failed，继续处理其他图片。进程中断留下的 submission_unknown 在下次运行时告警并重新尝试。不清理旧记录。此策略优先推进流程，可能重复生成、重复扣费；目前未按鉴权、余额、参数等错误进一步区分提交重试资格。

查询超时不等于任务失败：保留 ID，续跑继续查询。明确失败的任务可能按共享执行器既有规则重提，但不会切换到 MXAPI。平台与批次保护见 [目录说明](../README.md)。

## 参数范围（当前适配器）

- 固定 `n=1`、`output_format=png`、`response_format=url`，不支持通过阶段配置改变这三个值。
- `quality`：`auto / low / medium / high`。
- 可在 `execution.model.size` 显式设置 `auto / 1024x1024 / 1536x1024 / 1024x1536`。
- 未设置 size 时，仅允许 `resolution=1K`，按 `aspect_ratio` 映射：`1:1 → 1024x1024`、`3:2 → 1536x1024`、`2:3 → 1024x1536`。
- 不支持的比例、尺寸组合会在提交前报错，不静默降级。

## 两套异步接口实测

2026-09-04 使用用户授权的临时 Token，各提交一次 `gpt-image-2` 文生图；相同提示词，均指定 `size=1024x1024`、`quality=low`、`n=1`、PNG、URL 输出。Token 未写入项目。

| 对比 | 当前图片异步接口 | 原生 `/v1/videos` 接口 |
|---|---|---|
| 提交 | `/async/v1/images/generations` | `/v1/videos` |
| 提交 HTTP | 202 | 200 |
| 查询 | `/get-async?id=<id>` | `/v1/videos/<id>` |
| 最终状态 | completed | completed |
| 结果字段 | `result.data[0].url` | `video_url` |
| 图片实际格式与尺寸 | PNG，1024×1024 | PNG，1254×1254 |
| 实际字节数 | 1,137,508 | 1,318,921 |
| 图片读取与完整性校验 | 通过 | 通过 |

结论：两者本次均可生图。继续采用图片异步接口：与现有解析器兼容，且本次遵循请求尺寸。`/v1/videos` 虽返回 `object=video` 和 `video_url`，实际内容是 PNG，但本次尺寸与请求不一致；它没有接入当前运行配置，不能仅改端点就复用当前解析器。

这不是稳定性、性能或价格评测。未验证：参考图遵循程度、多图、高质量、其他尺寸、长期成功率和最终账单。下一步应验证带参考图的单张 Walmart 主图，不能据此直接认定整条业务已线上验收。

## 官方资料

- [异步创建图像](https://tuzi-api.apifox.cn/478893088e0)
- [查询异步任务](https://tuzi-api.apifox.cn/372533615e0)
- [统一异步任务协议](https://api.tu-zi.com/docs/use-cases/async-tasks)
- [原生视频任务协议](https://api.tu-zi.com/docs/api/video)

官方示例与实际渠道可能存在差异，以上解析说明以当前项目代码和此次实测为准。
