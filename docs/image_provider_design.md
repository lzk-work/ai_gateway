# 生图平台切换设计

## 边界

- Walmart 图片生成根配置 `image_provider` 是唯一平台选择：`tuzi` 主用，`mxapi` 备用。
- 主图与副图使用同一平台；不并行启用、不自动回退、不逐图切换。
- 业务提示词、输入 Excel、图片命名、OSS 上传和审核输出保持不变。
- 公共执行器负责并发、checkpoint、轮询与下载；平台适配器负责请求构造、查询及响应解析。
- 保留原模块导入入口，避免影响尚未完成的图片替换任务。

## 异步接口

兔子：`POST /async/v1/images/generations`，`GET /get-async?id=...`。
参数采用 `model/prompt/image/size/quality/n/response_format`；首版固定单图、URL 输出。
MXAPI：保留现有请求、`data.task_id`、`data.status` 和图片地址解析。

兔子文档的示例不完整，按其通用异步约定实现 `id/status/result/status_code`；未知或不完整响应必须报错，不能猜测为成功。2026-09-04 已验证真实 gpt-image-2 文生图响应与当前解析器兼容；参考图支持仍需小样本验收。两套异步接口对比见 [兔子平台文档](../gateways/TUZI/README.md)。

## 批次保护

每批保存 `image_provider.json`，首次生图前绑定平台。历史生图产物没有标记时视为 MXAPI。
跨平台续跑必须拒绝，要求使用新批次；旧 checkpoint 不改写、不清理。
平台检查在总流程开始和单独生图入口构建模板前执行，dry-run 只检查不写标记。

## 可靠性

兔子未取得任务 ID 时按 gateways.tuzi.max_retries 有限重试；当前为 2 次重试，加首次共最多 3 次。提交前记录意图，重试耗尽记为可续跑失败，不阻塞其他图片。接受重复生成/扣费风险。查询失败或超时保留 task_id，仍回原平台查询。
新平台只接受明确成功且包含可下载图片地址的响应。每次下载完成后继续使用既有结果格式，供 OSS 阶段消费。

## 使用与验收

1. 在本地环境配置 TUZI_API_KEY；MXAPI_API_KEY 保留用于手动切回，勿提交真实密钥。
2. 在 subtasks/walmart_image_prompt/config.json 设置 image_provider 为 tuzi 或 mxapi，主图、副图一起切换。阶段网关字段已删除，由业务入口注入平台协议；配置归属见 [配置说明](../subtasks/walmart_image_prompt/CONFIGURATION.md)。
3. 切换平台必须使用新批次（新的输入 Excel 文件名）；不要删除旧 checkpoint 或旧产物来绕过保护。
4. 先运行 python subtasks/walmart_image_prompt/00_full_workflow.py --dry-run，检查配置，再进行人工授权的小样本真实验收。

当前 develop_flow_260903 已有 MXAPI 产物；选 tuzi 时预览会提前拒绝，这是预期保护，不是接口失败。实现未自动更名输入文件或迁移旧批次。

submission_unknown 表示进程在提交期间中断等未确认状态；再次运行会告警并按有限重试策略推进，可能重复创建任务。不要删除 checkpoint，已有 task_id 的任务继续按原 ID 查询。

首版固定 n=1、PNG 和 URL 结果；Base64 或文档未定义的结构会报错并保留已获得的任务 ID。gpt-image-2 文生图真实异步返回已验证；参考图 image 参数仍需渠道实测，单次接口通过不等于整条业务线上验收通过。

## 验证

离线测试覆盖两平台请求/解析、失败/未知状态、批次平台冲突、历史兼容和不触网预览；不使用真实 Key、不产生付费任务。

运行：python -m unittest discover -s tests -p test_image_providers.py -v。
已通过 17 项协议/执行器测试，并在禁止网络请求的条件下完成 MXAPI 旧批次与兔子空白批次的完整 dry-run；兔子预览未创建批次目录。

来源：
- https://tuzi-api.apifox.cn/478893088e0
- https://tuzi-api.apifox.cn/372533615e0
- https://api.tu-zi.com/docs/use-cases/async-tasks
