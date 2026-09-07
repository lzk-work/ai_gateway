# 平台接入文档

本目录记录项目实际使用的平台协议、配置与验证情况，不保存真实密钥。运行配置仍在 `configs/` 和各业务目录，修改本目录文档不会改变运行行为。

| 平台 | 用途 | 文档 |
|---|---|---|
| BUZZ | 提示词模型调用 | [BUZZ](BUZZ/README.md) |
| 兔子 TUZI | 当前主用图片生成平台 | [TUZI](TUZI/README.md) |
| MXAPI | 图片生成手动备用平台 | [MXAPI](MXAPI/README.md) |

## 配置入口

- [平台地址、鉴权变量和 HTTP 超时](../configs/gateways.yaml)
- 本地密钥：`configs/local.env`，格式参照 [local.env.example](../configs/local.env.example)，勿提交真实密钥。
- [Walmart 业务总配置](../subtasks/walmart_image_prompt/config.json)：`image_provider` 取 `tuzi` 或 `mxapi`，统一控制主图、副图，不影响 BUZZ。
- [主图模型参数](../subtasks/walmart_image_prompt/stages/generate_main_image/config.json)、[副图模型参数](../subtasks/walmart_image_prompt/stages/generate_sub_images/config.json)：`execution.model`。
- [平台适配器](../src/ai_gateway/clients/image_providers.py)：请求构造、提交解析、查询与结果解析。
- [业务配置组装](../subtasks/walmart_image_prompt/workflow_common.py)：load_stage_data 统一派生路径、注入平台协议，阶段文件不再保留网关或批次路径。
- [共享执行器](../src/ai_gateway/subtasks/mxapi_generate_images.py)：提交、轮询、断点续跑和下载。模块旧名称为兼容保留。

## 整体切换

三个平台的请求重试次数统一读取本平台 max_retries：2 表示首次加两次重试，最多三次。公共模块为 src/ai_gateway/retry_policy.py 的 gateway_max_attempts；Walmart 阶段不再配置重复次数，下载重试及间隔仍独立保留。

完整配置归属与清理说明见 [CONFIGURATION](../subtasks/walmart_image_prompt/CONFIGURATION.md)。

1. 配置目标平台密钥：`TUZI_API_KEY` 或 `MXAPI_API_KEY`。
2. 修改业务总配置的 `image_provider`，主图、副图一起切换，不自动回退。
3. 新平台使用新的输入 Excel 文件名形成新批次；不要删除旧产物或 checkpoint 绕过检查。续跑旧批次需使用其原平台。
4. 在项目根目录运行预览，再确认正式执行：

```powershell
python subtasks/walmart_image_prompt/00_full_workflow.py --dry-run
```

批次平台标记为 `batches/<批次>/image_provider.json`。没有标记但已有生图或上传产物的历史批次按 MXAPI 处理。当前 `develop_flow_260903` 是旧 MXAPI 批次，切兔子时被拒绝属于预期保护。

图片替换业务不在本次平台切换范围。更多设计见 [生图平台设计](../docs/image_provider_design.md)。
