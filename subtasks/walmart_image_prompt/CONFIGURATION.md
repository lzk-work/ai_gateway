# Walmart 图片生成：配置归属

更新：2026-09-04。主图、副图阶段配置仍然有效；本轮删除的是未读取或被覆盖的字段，不是删除整个阶段。

## 应该改哪里

| 需要修改的内容 | 唯一配置位置 |
|---|---|
| 主图、副图统一平台 | [业务总配置](config.json) 的 image_provider |
| 源 Excel、源 Sheet | 总配置 input |
| 阶段开关、BUZZ 参考副图数量 | 总配置 workflow |
| SKU 上限、BUZZ/生图/OSS 并发 | 总配置 execution |
| 整轮重试开关、间隔、轮数上限 | 总配置 scheduler |
| 副图类型顺序、目标数量 | 总配置 image_selection |
| OSS 相对对象路径 | 总配置 oss.key_template |
| 平台域名、密钥变量、HTTP 超时 | [gateways.yaml](../../configs/gateways.yaml) |
| 密钥、OSS Bucket/Endpoint、公共前缀 | configs/local.env 或进程环境；参照 [示例](../../configs/local.env.example) |
| 主图模型、质量、比例、分辨率/尺寸 | [主图阶段](stages/generate_main_image/config.json) execution.model |
| 副图模型、质量、比例、分辨率/尺寸 | [副图阶段](stages/generate_sub_images/config.json) execution.model |
| BUZZ/兔子/MXAPI 请求额外重试次数 | gateways.yaml 各平台 max_retries |
| 单次查询/下载重试、重试间隔、续跑 | 主图/副图阶段 limits、retry、resume |
| BUZZ 模型、候选、采样、重试、续跑 | [BUZZ 阶段](stages/call_prompt_model/config.json) |
| 提示词模板、Excel 列映射、预检限制 | [提示词阶段](stages/get_pic_prompt/config.json) |
| 主图固定提示词文件、模板及列映射 | [主图入参阶段](stages/build_main_image_input/config.json) |
| 副图模板及列映射 | [副图入参阶段](stages/build_sub_image_download_input/config.json) |
| OSS 覆盖行为、Sheet、列映射、续跑、上传分批 | [主图上传](stages/upload_main_image/config.json)、[副图上传](stages/upload_oss/config.json) |

批次名由总配置输入 Excel 文件名派生。所有中间产物、下载目录、checkpoint、最终输出路径由 workflow_common.batch_paths 生成，不再在各阶段重复填写绝对路径。

## 为什么主图和副图还要分别配置

两者使用同一平台，但提示词来源和列映射不同，且可以分别设置模型参数、等待时间、下载重试。主图使用固定提示词，副图使用 BUZZ 的 image_plan，因此不合并为一个阶段。

对兔子，execution.model.size 可显式指定输出尺寸；没有 size 时，由 aspect_ratio 与 resolution=1K 映射。对 MXAPI，仍使用 aspect_ratio、quality、resolution，模型由端点体现。具体差异见 [兔子](../../gateways/TUZI/README.md) 和 [MXAPI](../../gateways/MXAPI/README.md)。

## 已删除的歧义配置

- 主/副图 execution.gateway：平台改由总配置选择，协议端点由 image_gateway_contract 定义，不能在两个阶段分别选择平台。
- 各阶段重复的源文件、阶段输入路径、output、测试 batch_id：统一在运行前派生。
- execution.type、上传 execution.provider、空 gateway/model：既有执行器没有读取。
- BUZZ 阶段重复的 base_url、api_key_env、auth_header、endpoint、model.provider/api_style：实际并非这些字段控制请求。
- BUZZ validation、context_policy、retryable_http_status：未被该阶段加载；删除不代表关闭校验。当前 JSON/image_plan 校验及 6 项方案约束仍在代码中。
- 提示词阶段 context_policy 与 limits.image_detail：原来仅进入任务元数据，不能控制后续历史消息或图像细节。真正的 image_detail 在 BUZZ 阶段 execution.model。
- 主图 prompt_column：未被工作行读取器使用；实际提示词列由 columns.prompt 控制。
- OSS 阶段 prefix/key_template、limits.max_workers：被业务总配置覆盖。
- 总配置 oss.prefix：未参与对象 key 拼接。实际路径由 ALIYUN_OSS_DEFAULT_PREFIX 与 oss.key_template 组成，本次保留 key_template 的原值。
- BUZZ 阶段 retry.max_retries、主/副图阶段 retry.max_submit_retries 已删除。三个平台统一读取 gateways.yaml 对应平台的 max_retries。

### 有条件生效的参数不是无用配置

- 三个平台 max_retries 都表示额外重试次数：0 表示仅首次，2 表示含首次最多 3 次。公共模块 ai_gateway.retry_policy.gateway_max_attempts 负责解释与校验，执行器和确认预览共用；阶段再配置旧字段会报错。未取得任务 ID 的重试可能重复扣费。

重试次数统一，不代表所有错误都强制重试或三个协议返回相同。BUZZ 保留错误分类及协议兼容回退，图片生成保留任务 ID 续查。上限按执行器的一次调用周期计算；用户重新续跑会重新获得预算，BUZZ 一轮内的协议兼容回退不属于新增重试轮次。图片下载、OSS 上传和已确认任务失败后的业务重提不与 API 提交重试混为一谈。
- 副图入参 image_count 在没有启用 image_selection 时作为全量模式数量；启用选图时按类型候选及目标数处理。
- 上传 limits.batch_size 仍有效；可选的总配置 execution.oss_batch_size 会统一覆盖两个阶段。
- configs/models.yaml 是共享模型注册表，不是本业务生图参数入口，不应为本业务清理而删除其他调用方需要的注册信息。

## 运行与兼容

使用业务编号入口：00 总流程，或 01、02、03b、03、05b、05 单阶段。它们先通过 load_stage_data/load_stage_config 组装有效配置，再调用共享执行器。执行前确认也读取相同的有效配置。

TUZI 使用延迟异步模式：第一轮批量提交并保存 task_id，不原地轮询；之后按 `scheduler.interval_seconds`（默认 10800 秒）从 01 开始完整续跑，查询并下载已有任务、补交明确失败或缺失的任务，再增量上传和重建结果。`scheduler.max_cycles` 为 null 时不限轮数，命令行 `--once` 可临时只执行一轮。

主/副图阶段的 `retry.retry_delay_seconds` 控制同一轮内接口或下载重试的等待；`scheduler.interval_seconds` 控制两次完整业务轮次之间的等待。TUZI 延迟异步模式不使用 `poll_interval_seconds/max_wait_seconds` 原地等待，这两个字段仍保留给 MXAPI 即时轮询备用模式。

`retry.query_attempts_per_cycle` 是每一轮中、每个已有 task_id 的查询总次数上限，当前主图和副图均为 3。首次查询仍在排队、返回 expired/410/503 或发生临时网络错误时，等待 `query_retry_delay_seconds`（当前 5 秒）再查询，最多追加两次查询、额外等待 10 秒。其目的只是吸收查询接口和网络抖动，不在本轮等待异步生图完成。达到上限后保留 task_id，等待下一轮。该上限不与 gateways.max_retries 相乘。

    python subtasks/walmart_image_prompt/00_full_workflow.py --dry-run
    python -m unittest discover -s tests -p "test_*.py" -q

精简后的阶段 JSON 不是可直接传给共享模块 CLI 的独立任务配置；不要绕过业务入口。入参构建脚本自己的 main 也已改为使用业务配置。

共享加载器仅新增可选 config_data 参数，不改变旧格式读取方式；图片替换业务的配置和业务文件未修改。旧批次平台保护仍有效，切换兔子需要新批次，不能删除旧 checkpoint 来规避。
