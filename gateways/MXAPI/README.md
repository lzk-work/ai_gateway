# MXAPI：图片生成手动备用平台

更新：2026-09-04。本文描述项目保留的既有 MXAPI 实现，不声称覆盖平台全部能力；本轮未使用 MXAPI 密钥重新发起付费测试。

## 配置和代码

- Base URL：`https://open.mxapi.org`，网关名：`mxapi`。
- [网关配置](../../configs/gateways.yaml)：HTTP 超时以 timeout_seconds 为准；密钥变量 MXAPI_API_KEY，在 configs/local.env 或进程环境配置。
- 鉴权：`Authorization: Bearer <API_KEY>`。
- [业务总配置](../../subtasks/walmart_image_prompt/config.json)：`"image_provider": "mxapi"`，主图、副图一起切回；不影响 BUZZ。
- [解析器](../../src/ai_gateway/clients/image_providers.py)：`MxapiImageAdapter`。
- [HTTP 客户端](../../src/ai_gateway/clients/mxapi_image_client.py)：提交、按 task_id 查询、下载。
- [主图参数](../../subtasks/walmart_image_prompt/stages/generate_main_image/config.json)、[副图参数](../../subtasks/walmart_image_prompt/stages/generate_sub_images/config.json)：execution.model 保留有效模型参数；execution.gateway 已移除，MXAPI 端点由业务配置组装层按总开关注入。

## 异步协议

提交：`POST /api/v2/gpt-image-2`，当前请求结构：

```json
{
  "prompt": "保持参考商品外观，生成干净背景的产品摄影",
  "aspect_ratio": "1:1",
  "quality": "low",
  "resolution": "1K",
  "reference_images": ["https://example.com/reference.png"]
}
```

模型由提交端点体现；当前 MXAPI 请求体不包含 `model`，不要照搬兔子的 `model/image/size` 请求结构。

提交解析要求业务 `code == 200`，从 `data.task_id` 获取任务 ID。查询使用 `GET /api/v2/gpt-image/task?task_id=<id>`，不是兔子的 `id` 查询参数。

以下是代码要求的关键结构示例，不是本轮新实测记录：

```json
{"code": 200, "data": {"task_id": "example_task"}}
```

```json
{
  "code": 200,
  "data": {
    "status": "completed",
    "result": {"source_images": ["https://example.com/result.png"]}
  }
}
```

## 解析和恢复

- 提交与查询均检查业务 `code`；HTTP 成功不代表业务成功。
- `data.status=failed`：明确失败，优先读 `error_msg`，其次读 `error`。
- `data.status=completed`：从 `data.result` 提取图片地址。
- 其他状态保持既有行为：视为等待，直到本地轮询截止时间；这与兔子对未知状态报错的策略不同。
- 地址按 `source_images → proxy_images → images` 顺序收集，列表项转为字符串并去重，下载器依次尝试。
- 提交重试次数统一读取 gateways.mxapi.max_retries，2 表示首次失败后再重试两次；不再读取阶段 max_submit_retries。确认失败后的重提和超时保留 task_id 行为保留。MXAPI 未采用兔子的提交意图记录，两者均可能因未取得 ID 后重试产生重复任务。
- MXAPI checkpoint 写入失败仍按旧逻辑告警；兔子则停止执行，以免重复提交。

## 手动切回边界

不支持任务内按图片回退。切回 MXAPI 后，可恢复原 MXAPI 批次；若是将兔子业务重新交给 MXAPI 生成，应使用新输入批次，不能沿用兔子的任务 ID、checkpoint 或平台标记。

操作入口与预览命令见 [平台目录说明](../README.md)。不要仅改 `gateways.yaml` 的地址：两套协议的请求字段和结果结构不同，必须通过业务总配置选择适配器。

## 验证范围

现有离线测试覆盖 MXAPI 原请求构造、任务 ID 解析、结果地址顺序、失败解析和原提交重试；完整旧批次 dry-run 已在禁止网络请求的条件下通过。

```powershell
python -m unittest discover -s tests -p test_image_providers.py -v
```

更多背景见 [平台切换设计](../../docs/image_provider_design.md) 和 [既有 MXAPI 生成说明](../../docs/mxapi_image_generation_design.md)。
