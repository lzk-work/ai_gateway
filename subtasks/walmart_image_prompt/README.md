# walmart_image_prompt 业务任务

这是一个完整业务任务，不是单独的技术子函数。当前用途是：从 Walmart Excel 读取 SKU 数据，结合提示词模板生成图片方案请求，再调用 BUZZ/OpenAI 兼容接口返回 JSON 结果，并写入结果文件与 Excel。

## 目录规划

```text
subtasks/walmart_image_prompt/
  README.md                         业务任务说明
  input/                            本业务任务入参文件
    walmart_flow_test.xlsx          当前测试 Excel
  prompts/                          本业务任务提示词模板
    walmart_image_prompt_template.txt
  00_full_workflow.py               总流程入口，可按配置开关执行阶段
  01_generate_prompt_tasks.py       第一步：Excel 生成 BUZZ 提示词任务
  02_call_buzz_model.py             第二步：调用 BUZZ 生成图片方案 JSON
  03_generate_and_download_images.py 第三步：生成图片入参并调用 MXAPI 下载图片
  05_upload_oss.py                  第五步：上传当前批次图片到阿里云 OSS
  stages/
    get_pic_prompt/
      config.json                   第一阶段配置：Excel、模板、列映射、输出任务文件
      README.md                     第一阶段说明
      output/generated_prompt_tasks.jsonl
    call_prompt_model/
      config.json                   第二阶段配置：中转站、模型、输入任务、输出文件、校验规则
      README.md                     第二阶段说明
      output/model_results.jsonl
      output/walmart_results.xlsx
      output/full_outputs/
  scripts/                          该业务任务专用辅助脚本，当前预留
```


## 业务级配置

业务任务根配置文件：

```text
subtasks/walmart_image_prompt/config.json
```

当前用于控制整条业务链路的批量处理数量：

```json
{
  "input": {
    "excel_path": "E:/WorkSpace/ai_gateway/subtasks/walmart_image_prompt/input/walmart_flow.xlsx",
    "sheet_name": "Sheet1"
  },
  "execution": {
    "max_records": 1
  }
}
```

- `input.excel_path`：本批入参 Excel，批次名也由这个文件名决定。
- `input.sheet_name`：读取的 Sheet。
- `max_records: 1`：测试模式，只处理 1 行源数据（1 个 SKU）。
- `max_records: 100`：批量处理 100 行源数据（100 个 SKU）。
- `max_records: null`：不限制，处理全部源数据。

阶段配置里不再设置 `max_records`，也不再改业务入参 Excel，避免每个子任务都要单独改。

`max_records` 统一按**源数据行数（SKU 数）**计数，各阶段在此基础上展开各自的任务量：

| 阶段 | 任务量（max_records=150） |
|------|--------------------------|
| 01 生成提示词 | 150 条提示词任务（1 行源数据 = 1 条） |
| 02 调 BUZZ 模型 | 150 条模型调用（1 条 = 1 个 SKU） |
| 03 生成图片 | 150 个 SKU × 6 张 = 900 个图片任务 |
| 05 上传 OSS | 900 个图片上传任务 |

图片类阶段按 SKU 整体截断：同一个 SKU 的 6 张副图要么全部处理、要么全部不处理，不会只生成/上传部分副图。

## 批次目录

批次由入参 Excel 文件名决定，不按启动时间决定。

例如当前入参：

```text
input/walmart_flow_test.xlsx
```

对应批次目录：

```text
subtasks/walmart_image_prompt/batches/walmart_flow_test/
```

同一个入参文件中断后重跑，仍然进入同一个批次目录，继续断点续跑。想重新跑一版独立结果，就把入参 Excel 改成可区分的文件名，例如：

```text
walmart_flow_test_v2.xlsx
walmart_flow_test_20260807.xlsx
```

批次内部目录：

```text
batches/<入参文件名>/
  01_get_pic_prompt/generated_prompt_tasks.jsonl
  02_call_buzz_model/model_results.jsonl
  02_call_buzz_model/full_outputs/
  02_call_buzz_model/walmart_results.xlsx
  03_build_image_input/walmart_sub_image_input_result.xlsx
  04_generate_images/image_generation_checkpoint.jsonl
  04_generate_images/image_generation_results.jsonl
  04_generate_images/walmart_sub_image_generation_result.xlsx
  04_generate_images/downloaded_images/
  04_generate_images/raw_responses/
  05_upload_oss/oss_upload_checkpoint.jsonl
  05_upload_oss/oss_upload_results.jsonl
  05_upload_oss/walmart_sub_image_oss_result.xlsx
```

`batches/` 已加入 `.gitignore`，不会进入 Git。
## 当前阶段

1. `get_pic_prompt`
   - 读取 Excel。
   - 从每行读取 SKU、标题、五点、图片链接。
   - 读取提示词模板。
   - 按占位符替换生成每个 SKU 的模型输入任务。
   - 输出 `generated_prompt_tasks.jsonl`。

2. `call_prompt_model`
   - 读取第一阶段生成的任务。
   - 每个 SKU 单独请求模型，不带跨 SKU 记忆。
   - 当前模型配置在本阶段自己的 `config.json` 中，默认 `gpt-5.4`，开启 `stream`。
   - 校验返回内容是否为合法 JSON，并检查 `image_plan` 是否为 6 个。
   - 保存完整返回 JSON 到 `full_outputs/`。
   - 写出结构化运行记录到 `model_results.jsonl`。
   - 将结果写回 Excel：完整保留 `image_plan`，其他结构保留字段但不写入大段内容，避免 Excel 单元格过长。

## 如何运行

### 总流程

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

默认 `generate_and_download_images=false`，避免一跑总流程就消耗 MXAPI 图片额度。确认要生成图片时再改为 `true`。

### 分步执行

第一步，只从 Excel 生成提示词任务，不调用模型：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\01_generate_prompt_tasks.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\01_generate_prompt_tasks.py --dry-run
```

第二步，调用 BUZZ 文本模型，生成并校验图片方案 JSON：

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

第六步，根据 OSS 上传结果生成最终图片结果表：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\06_build_final_image_result.py --dry-run
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\06_build_final_image_result.py
```

输出位置：

```text
batches/<批次名>/05_upload_oss/最终图片结果_由sub生成.xlsx
```

查看当前批次统计，不调用接口、不改文件：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\99_batch_stats.py
```

总流程 `00_full_workflow.py` 结束时会自动打印同样的批次统计。

历史批次可手动指定批次名：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --dry-run --batch-name walmart_flow_1
```

`--dry-run` 规则：

- 不调用 BUZZ。
- 不调用 MXAPI。
- 不连接 OSS、不上传文件。
- 不生成或覆盖 JSONL、Excel、图片文件。
- 只显示输入文件、任务总数、已成功跳过数、本次将处理数、并发、模型和前几条样例。

## OSS 上传配置

阿里云平台级配置放在 `configs/local.env`：

```text
ALIYUN_OSS_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_BUCKET=zlx-oss-db
ALIYUN_OSS_DEFAULT_PREFIX=images
```

上传哪些图片、从哪个批次目录读取、OSS key 如何生成，由 `stages/upload_oss/config.json` 和当前批次结果决定。

## 文件归属规则

本业务任务相关文件都放在 subtasks/walmart_image_prompt/ 内：

- 入参文件放 input/。
- 提示词模板放 prompts/。
- 阶段配置放 stages/<stage_name>/config.json。
- 阶段出参放 stages/<stage_name>/output/。
- 业务专用辅助脚本放 scripts/。

不要再把业务入参、提示词模板、启动脚本散放到桌面或项目根目录。

## 配置文件

第一阶段配置：

```text
E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\stages\get_pic_prompt\config.json
```

主要配置：

- 业务入参 Excel 来自业务总配置 `config.json` 的 `input.excel_path`，运行时会覆盖本阶段配置。
- 业务 Sheet 来自业务总配置 `config.json` 的 `input.sheet_name`。
- `input.prompt_template_path`：提示词模板文件。
- `columns`：Excel 列名映射。
- `placeholder_mapping`：模板占位符与 Excel 列名的对应关系。
- `output.prompt_tasks_path`：第一阶段输出任务文件。

第二阶段配置：

```text
E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\stages\call_prompt_model\config.json
```

主要配置：

- `execution.gateway`：本阶段使用的中转站。
- `execution.model`：本阶段使用的模型、是否流式、输出 token 上限。
- `input.prompt_tasks_path`：第一阶段输出文件。
- 写回结果时使用的源 Excel 来自业务总配置 `config.json` 的 `input.excel_path`。
- 处理数量不在阶段配置里设置，统一由业务任务根配置 `config.json` 的 `execution.max_records` 控制。
- `output.model_results_path`：模型调用记录。
- `output.full_outputs_dir`：完整模型返回内容。
- `output.excel_result_path`：写回后的 Excel 文件。
- `validation`：JSON 和 `image_plan` 校验规则。
- `retry`：失败重试规则。

## 新增业务任务规范

后续新增业务任务时，不要把启动脚本散放在项目根目录。按下面结构新增：

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

公共能力仍放在 `src/ai_gateway/`，例如中转站客户端、批处理、日志、结果校验、Excel 写入等；业务任务目录只放该业务专属的配置、启动入口、阶段说明和输出文件。






## 查询 BUZZ 当前可用模型

如果运行时报：`model_not_found` 或 `Model "xxx" is not supported by any configured account in this group`，说明当前 BUZZ Key 所属账号组不支持该模型。先用下面脚本查询真实可用模型：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\scripts\list_buzz_models.py
```

查询结果会保存到：

```text
subtasks/walmart_image_prompt/scripts/output/available_buzz_models.json
```

然后把 `stages/call_prompt_model/config.json` 里的 `execution.model.name` 或 `execution.model.candidates` 改成列表中真实存在的模型。


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
buzz_key_env=BUZZ_API_KEY
buzz_key_fingerprint=xxxxxxxxxxxx
available_model_count=7
model_preflight=passed model=gpt-5.4
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

## BUZZ 模型候选池

BUZZ 模型列表可能随当前 Key、账号组和上游通道变化。第二阶段支持维护候选模型列表：

```json
"model": {
  "name": "gpt-5.4",
  "candidates": [
    "gpt-5.4",
    "gpt-5.6-terra",
    "gpt-5.6-sol",
    "gpt-5.5"
  ],
  "refresh_on_error": true
}
```

执行规则：

- `name` 是首选模型。
- `candidates` 是允许自动切换的模型池，顺序就是优先级。
- 启动时会用 BUZZ `/v1/models` 过滤候选池，只保留当前 Key 可用模型。
- 执行过程中如果遇到 `model_not_found` 或 `No available channel for model`，会刷新模型列表并切换到下一个可用候选模型。
- 控制台出现 `model_switch from=... to=...` 表示本次运行已经自动换模型。

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
- 业务级 `max_records` 表示“本次最多处理多少个 SKU（源数据行）”，已成功记录不会占用名额。图片/上传阶段按 SKU 展开，每个 SKU 的全部副图作为一个整体处理。
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
[2/10] 完成 SKU=XJ-yyy 状态=失败 错误=HTTP 520 Cloudflare HTML 错误页，上游/中转站异常
```

字段说明：

- `开始`：某条任务开始调用模型。
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

## 成功 SKU 生成副图下载模板

第三步入口会自动先生成副图下载模板，再调用 MXAPI。如果只想单独生成下载模板，可以运行辅助脚本：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\scripts\build_sub_image_download_input.py
```

输出：

```text
subtasks/walmart_image_prompt/stages/build_sub_image_download_input/output/walmart_sub_image_input_result.xlsx
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

## MXAPI 生成副图阶段

运行：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\03_generate_and_download_images.py
```

设计说明：

```text
docs/mxapi_image_generation_design.md
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
