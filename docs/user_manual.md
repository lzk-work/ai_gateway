# 使用说明书

## 1. 准备 API Key

当前 BUZZ 配置读取系统环境变量 `BUZZ_API_KEY`。

PowerShell 临时设置：

```powershell
$env:BUZZ_API_KEY="你的BUZZ_API_KEY"
```

这个设置只对当前 PowerShell 窗口有效。关闭窗口后需要重新设置。

## 2. 修改业务配置

当前业务任务目录：

```text
E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt
```

业务文件位置：

- Excel 入参：subtasks/walmart_image_prompt/input/walmart_flow_test.xlsx。
- 提示词模板：subtasks/walmart_image_prompt/prompts/walmart_image_prompt_template.txt。
- 阶段出参：各阶段自己的 output/。

常改字段：

- 业务总配置 `input.excel_path`：Excel 文件路径。
- 业务总配置 `input.sheet_name`：Sheet 名。
- 第一阶段配置 `input.prompt_template_path`：提示词模板路径。
- 第一阶段配置 `columns`：Excel 列名映射。

业务总配置：

```text
subtasks/walmart_image_prompt/config.json
```

常改字段：

- `input.excel_path`：本批入参 Excel，批次名也由这个文件名决定。
- `input.sheet_name`：读取的 Sheet。
- `execution.max_records`：本次最多处理多少条未成功记录。
- `execution.concurrency`：BUZZ 文本模型并发数。
- `execution.image_concurrency`：MXAPI 图片生成并发数。
- `execution.preflight_model`：启动前是否检查 BUZZ 可用模型。
- `workflow`：总流程阶段开关。

第二阶段模型配置：

```text
subtasks/walmart_image_prompt/stages/call_prompt_model/config.json
```

常改字段：

- `execution.gateway.name`：中转站。
- `execution.model.name`：首选模型，当前为 `gpt-5.4`。
- `execution.model.candidates`：允许自动切换的候选模型池。
- `execution.model.stream`：是否开启流式响应，当前为 `true`。
- `execution.model.max_tokens`：最大输出 token，当前为 `12000`。
- `output.excel_result_path`：写回后的 Excel 路径。


## 2.1 业务级处理数量

处理数量只改业务任务根配置：

```text
subtasks/walmart_image_prompt/config.json
```

```json
{
  "execution": {
    "max_records": 1
  }
}
```

测试时设为 `1`，批量 100 条设为 `100`，不限制则设为 `null`。阶段配置里不再设置处理数量。

入参文件也只改业务任务根配置：

```json
{
  "input": {
    "excel_path": "E:/WorkSpace/ai_gateway/subtasks/walmart_image_prompt/input/walmart_flow.xlsx",
    "sheet_name": "Sheet1"
  }
}
```

阶段配置里的 Excel 路径只作为兼容字段，运行时会被业务根配置覆盖。

## 2.2 批次规则

批次由入参 Excel 文件名决定，不按启动时间决定。

例如：

```text
input/walmart_flow_test.xlsx
```

输出会放到：

```text
subtasks/walmart_image_prompt/batches/walmart_flow_test/
```

同一个文件中断后重跑，会继续使用同一个批次目录。需要重新跑一版独立结果时，先把入参文件名改成可区分的名字，例如 `walmart_flow_test_v2.xlsx`。

批次目录已加入 `.gitignore`，不会进入 Git。
## 3. 运行总流程

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\00_full_workflow.py
```

试运行，只看将要处理的数据，不调用接口、不写输出：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\00_full_workflow.py --dry-run
```

总流程是否执行图片生成下载，由业务总配置控制：

```json
"workflow": {
  "generate_prompt_tasks": true,
  "call_buzz_model": true,
  "generate_and_download_images": false
}
```

默认不执行图片生成下载，避免误消耗 MXAPI 额度。

## 4. 分步执行

第一步，只生成提示词任务，不调用模型、不消耗费用：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\01_generate_prompt_tasks.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\01_generate_prompt_tasks.py --dry-run
```

第二步，调用 BUZZ 文本模型：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\02_call_buzz_model.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\02_call_buzz_model.py --dry-run
```

第三步，生成图片下载入参，并调用 MXAPI 生成/下载图片：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\03_generate_and_download_images.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\03_generate_and_download_images.py --dry-run
```

第五步，上传当前批次图片到阿里云 OSS：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --dry-run
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py
```

如果要处理手动归档的历史批次，例如 `walmart_flow_1`：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --dry-run --batch-name walmart_flow_1
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --batch-name walmart_flow_1
```

`--dry-run` 不会调用 BUZZ/MXAPI，也不会写 JSONL、Excel 或图片文件，只打印本次将要处理的数据概览。

OSS 上传所需平台配置放在：

```text
configs/local.env
```

字段：

```text
ALIYUN_OSS_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_BUCKET=zlx-oss-db
ALIYUN_OSS_DEFAULT_PREFIX=images
```

## 5. 查看结果

第一阶段输出：

```text
subtasks/walmart_image_prompt/stages/get_pic_prompt/output/generated_prompt_tasks.jsonl
```

模型调用记录：

```text
subtasks/walmart_image_prompt/stages/call_prompt_model/output/model_results.jsonl
```

完整模型返回：

```text
subtasks/walmart_image_prompt/stages/call_prompt_model/output/full_outputs/
```

写回 Excel：

```text
subtasks/walmart_image_prompt/stages/call_prompt_model/output/walmart_results.xlsx
```

## 6. 批量处理

在业务任务根配置里修改：

```json
"execution": { "max_records": 100 }
```

如果 100 条返回 90 条成功，剩余失败记录会保存在 `model_results.jsonl` 中，包含状态、错误、是否可重试、请求耗时等信息。

## 7. 结果校验

第二阶段会检查：

- 是否能解析为合法 JSON。
- 是否包含 `product_analysis`。
- `image_plan` 是否为 6 个对象。

校验结果会保存在调用记录中。原始返回会保留到 `full_outputs/`，便于排查模型输出问题。

## 8. 后续新增业务任务

不要在项目根目录新增启动脚本。按下面结构新增：

```text
subtasks/<business_task_name>/
  README.md
  00_full_workflow.py
  01_<step_name>.py
  02_<step_name>.py
  03_<step_name>.py
  workflow_common.py
  stages/
    <stage_name>/
      config.json
      README.md
      output/
  scripts/
```







## 查询 BUZZ 当前可用模型

如果运行时报：`model_not_found` 或 `Model "xxx" is not supported by any configured account in this group`，说明当前 BUZZ Key 所属账号组不支持该模型。先用下面脚本查询真实可用模型：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\scripts\list_buzz_models.py
```

查询结果会保存到：

```text
subtasks/walmart_image_prompt/scripts/output/available_buzz_models.json
```

然后把 `stages/call_prompt_model/config.json` 里的 `execution.model.name` 改成列表中真实存在的模型。


## BUZZ Key 与模型预检查

BUZZ Key 读取顺序：

1. 当前进程环境变量 `BUZZ_API_KEY`。
2. 如果环境变量没有设置，则尝试读取项目内 `configs/local.env`。

`configs/local.env` 已加入 `.gitignore`，可以放本机密钥，例如：

```text
BUZZ_API_KEY=你的BUZZ密钥
```

业务启动时会先执行模型预检查，并打印：

```text
=== 启动检查 ===
BUZZ Key: BUZZ_API_KEY (xxxxxxxxxxxx)
可用模型数: 7
模型预检: 通过 (gpt-5.4)
```

`buzz_key_fingerprint` 是 Key 的安全指纹，不会泄露原始 Key。查询模型脚本和业务启动脚本打印的指纹应该一致；如果不一致，说明两个进程用的不是同一个 Key。

如果不想每次启动前查询 `/v1/models`，可在业务任务根配置中关闭：

```json
"execution": {
  "preflight_model": false
}
```

## 启动前模型验证

业务任务默认每次启动都会先调用 BUZZ `/v1/models` 验证当前 Key 是否支持阶段配置里的模型。验证在任何业务阶段执行之前发生：

1. 读取 `BUZZ_API_KEY`。
2. 查询当前 Key 可用模型。
3. 保存可用模型列表到 `subtasks/walmart_image_prompt/scripts/output/available_buzz_models.json`。
4. 如果主模型不可用，会从候选模型里选择第一个当前可用模型。
5. 如果主模型和候选模型都不可用，立即停止，不生成提示词、不调用正式接口。

保留默认配置即可：

```json
"execution": {
  "preflight_model": true
}
```

只有在明确不需要预检时才改为 `false`。

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
- 业务级 `max_records` 表示“本次最多处理多少条未成功记录”，已成功记录不会占用名额。
- 新结果会和历史结果合并写回，不会清空已经成功的记录。

例如：第一批 100 条，90 条成功、10 条失败；下次启动会跳过 90 条，只处理剩下 10 条失败/未成功记录。

## 控制台调用过程输出

模型调用阶段会逐条打印进度，便于观察批量任务是否还在工作：

```text
=== BUZZ 文本模型阶段 ===
任务总数: 100 | 已成功跳过: 90 | 本次待处理: 10
调用并发: 2
[1/10] 开始 | SKU=XJ-xxx | 模型=gpt-5.4 | 网关=buzz
[1/10] 完成 SKU=XJ-xxx 状态=成功 耗时=68.3s 校验=通过
```

字段说明：

- `开始`：某条任务真正开始调用模型。
- `index=1/10`：当前是本次待处理任务中的第几条。
- `sku`：当前处理的业务记录。
- `status`：接口调用是否成功。
- `validation`：返回 JSON 是否符合模板校验。
- `耗时`：本条请求耗时。
- `error`：失败时的错误摘要。

全部处理完后还会打印：

```text
结果日志: ...
结果Excel: ...
```


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

## Excel 结果表字段

Excel 结果表只保留业务查看需要的核心字段：

- `ai_status`
- `ai_validation_status`
- `ai_image_plan_json`
- `ai_error_message`
- `ai_processed_at`

模型、网关、request id、完整原始返回、校验细节等调试信息不写入 Excel，统一保存在：

```text
stages/call_prompt_model/output/model_results.jsonl
stages/call_prompt_model/output/full_outputs/
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
stages/call_prompt_model/output/full_outputs/
```

Excel 需要完整结果时，会根据 `full_output_path` 读取对应文件再写入结果表。断点续跑仍然读取轻量日志判断成功记录并跳过。
