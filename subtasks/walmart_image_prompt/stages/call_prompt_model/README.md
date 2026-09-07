# call_prompt_model 阶段

所属业务任务：`walmart_image_prompt`。

本阶段读取第一阶段生成的任务，逐个 SKU 调用 BUZZ/OpenAI 兼容接口，并保存校验结果。

## 输入

配置文件：

```text
subtasks/walmart_image_prompt/stages/call_prompt_model/config.json
```

关键输入：

- 第一阶段输出的 JSONL：由批次路径派生，不在本阶段重复配置。
- 用于写回结果的源 Excel：只在业务总配置 input.excel_path 设置。

本阶段已删除不生效的 validation、context_policy、retryable_http_status 与重复网关信息。代码中的 JSON 与 6 项 image_plan 校验仍生效。完整说明见 [配置归属](../../CONFIGURATION.md)。

## 模型与中转站

本阶段自己的模型和中转站配置写在 `execution` 内，不依赖其他业务任务：

- `execution.gateway.name`：当前为 `buzz`。
- `execution.model.name`：当前首选 `gpt-5.6-luna`。
- `execution.model.candidates`：当前候选为 `gpt-5.4`。
- `execution.model.stream`：当前为 `true`。`gpt-*` 模型走 `/v1/responses` SSE；其他模型走 `/v1/chat/completions` SSE。改为 `false` 时保持相同协议，只切换为完整 JSON 响应。
- `execution.model.max_tokens`：当前为 `12000`。

## 输出

```text
batches/<批次名>/02_call_buzz_model/model_results.jsonl
batches/<批次名>/02_call_buzz_model/full_outputs/
batches/<批次名>/02_call_buzz_model/walmart_results.xlsx
```

保存策略：

- 完整模型原文保存到 `full_outputs/<SKU>__<MODEL>.json`。
- JSONL 保存调用状态、耗时、错误、校验结果、完整输出路径。
- Excel 写入 `image_plan` 完整信息；其他大字段只保留结构，不写入大段内容。
- 如果 Excel 单元格无法完整容纳，会标注过长。

## 重试

失败记录会写入 `model_results.jsonl`。同一批次重跑时会自动跳过已成功且校验通过的 SKU，并继续处理失败、未处理或校验失败记录。




## 断点续跑与跳过成功记录

模型调用阶段默认开启断点续跑：

```json
"resume": {
  "skip_success": true
}
```

规则：

- 历史结果文件 `model_results.jsonl` 中 `status=success` 且 `validation_status=passed` 的任务会跳过。
- 失败、校验失败、没有处理过的任务会继续处理。
- 新结果会和历史结果合并写回，不会清空已经成功的记录。

例如：第一批 100 条，90 条成功、10 条失败；下次启动会跳过 90 条，只处理剩下 10 条失败/未成功记录。


## Excel 结果表字段

Excel 结果表只保留业务查看需要的核心字段：

- `ai_status`
- `ai_validation_status`
- `ai_image_plan_json`
- `ai_error_message`
- `ai_processed_at`

模型、网关、request id、完整原始返回、校验细节等调试信息不写入 Excel，统一保存在：

```text
batches/<批次名>/02_call_buzz_model/model_results.jsonl
batches/<批次名>/02_call_buzz_model/full_outputs/
```

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
batches/<批次名>/02_call_buzz_model/full_outputs/
```

Excel 需要完整结果时，会根据 `full_output_path` 读取对应文件再写入结果表。断点续跑仍然读取轻量日志判断成功记录并跳过。
