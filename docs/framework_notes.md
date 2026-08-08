# 后续扩展注意事项

## 业务任务目录

所有业务任务都放到项目根目录的 `subtasks/` 下。一个业务任务一个文件夹，例如：

```text
subtasks/walmart_image_prompt/
subtasks/<next_business_task>/
```

每个业务任务都应该自带，并且都放在该业务任务目录下：

- 入参文件。
- 提示词模板。
- 启动脚本。
- 阶段配置。
- 阶段说明。
- 输入输出路径。
- 业务说明文档。

## 阶段目录

业务任务内部按阶段拆分：

```text
stages/<stage_name>/config.json
stages/<stage_name>/README.md
stages/<stage_name>/output/
```

阶段之间通过文件或数据库记录衔接。当前用 JSONL 文件衔接，后续可切换为数据库表。

## 模型和中转站

每个阶段自己声明模型和中转站，不要假设所有业务任务共用一个模型。

通用中转站能力放在 `src/ai_gateway/clients/` 和 `src/ai_gateway/gateways/`，业务配置写在业务任务自己的 `config.json`。

## 失败重试

批量任务必须保留每条记录的状态。失败记录不需要手工改 Excel 或数据库状态，后续应增加按批次、按失败状态重跑的脚本，放在对应业务任务的 `scripts/` 目录。

## 结果校验

每个模型调用阶段都应该有自己的结果模板和校验规则。校验失败时保留原始返回，同时写入校验状态，方便定位是模型输出问题、提示词问题还是接口问题。

## 输出文件

业务输出应写在业务任务目录内部，不要散放到项目根目录。临时测试结果如果只服务某个业务，也应放到该业务任务目录的 `output/` 或 `scripts/` 下。

## OSS 上传阶段

OSS 上传属于业务阶段，不属于通用图片下载脚本。平台级配置如 AK、Secret、Endpoint、Bucket 放环境变量或 `configs/local.env`；本地上传目录、批次目录、SKU、图片命名和 OSS key 规则由业务任务配置决定。

实现时注意：

- 不在代码中硬编码本地图片目录。
- 不在代码中硬编码 AK/SK。
- 每张图片独立 checkpoint，支持断点续跑。
- 上传结果按批次写到 `batches/<批次名>/05_upload_oss/`。
- 默认支持 `--dry-run`，先预览上传数量和目标 OSS 路径。
- 总流程中默认关闭真实上传，避免误操作。




## 并发调用配置

业务任务支持多线程同时调用模型，配置仍然只放在业务总配置：

```json
"execution": {
  "max_records": 10,
  "concurrency": 1,
  "preflight_model": true
}
```

- `concurrency: 1`：单线程，最稳，适合测试。
- `concurrency: 2` 或 `3`：并发调用，提高批量速度。
- 不建议一开始开太大，避免触发 BUZZ 或上游模型限流。

实现规则：

- 多线程只负责 API 调用。
- JSONL 和 Excel 结果由主线程统一合并写回。
- 历史成功记录仍会跳过，不会重复调用。
- 控制台会打印每条开始和结束；并发时结束顺序可能和开始顺序不同，但最终结果会按原任务顺序合并。

## 批量日志瘦身

为支持几百到几千条批量处理，主日志 `model_results.jsonl` 已改为轻量索引日志，只保存：

- 任务 ID、SKU、源 Excel 行号
- 状态、模型、网关、request id
- 耗时、重试、错误摘要
- JSON 校验状态
- 完整结果文件路径

主日志不再重复保存：

- 长提示词
- 源任务完整内容
- 模型完整返回正文
- raw response

完整模型返回仍按 SKU 单独保存在：

```text
stages/call_prompt_model/output/full_outputs/
```

Excel 需要完整结果时，会根据 `full_output_path` 读取对应文件再写入结果表。断点续跑仍然读取轻量日志判断成功记录并跳过。
