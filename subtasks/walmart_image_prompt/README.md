# Walmart 图片生成任务

本目录是一条已落地的 Walmart 商品图片生成流水线。本文以当前代码和配置为准；`walmart_image_replace` 是另一条尚未完成的业务，不属于本流程。

## 生图平台切换

根配置 `config.json` 的 `image_provider` 统一控制主图与副图：`tuzi` 为主用，`mxapi` 为手动备用。不会自动回退，也不会在同一批次混用平台。

兔子使用 `POST /v1/videos` multipart 异步提交和 `GET /v1/videos/{task_id}` 查询，需要配置 TUZI_API_KEY。URL/文件参考图与重复字段多图均受适配器支持；2026-09-08 已用 `gpt-image-2-1k`、URL 参考图完成 5 并发 10/10 实测。切换平台须使用新输入批次，MXAPI 与 TUZI 不会在同一批次混用。

接口、异常恢复及验收边界见 [生图平台设计](../../docs/image_provider_design.md)。主图、副图阶段仅保留有效参数，网关与重复路径已删除；各项应该在哪里修改见 [配置归属](CONFIGURATION.md)。

## 实际流程

```text
商品 Excel
  ├─ 01 组装每个 SKU 的多模态提示词任务
  ├─ 02 调用所选文本模型平台，生成并校验 6 张副图方案
  ├─ 03b 用固定提示词调用选定生图平台，生成 1 张优化主图
  ├─ 03 根据 BUZZ 方案调用选定生图平台，生成 6 张副图
  ├─ 05b 上传生成主图到阿里云 OSS
  ├─ 05 上传生成副图到阿里云 OSS
  └─ 06 生成副图结果表

可选：07 导出包含主图、副图、标题、五点和 OSS 链接的审核预览 Excel
```

主图和副图彼此独立提交、查询和下载；副图不等待同一 SKU 的主图完成。历史 `blocked` 副图记录不是终态，下次运行会自动重新参与处理。

## 入口文件

| 文件 | 作用 | 是否包含在总流程 |
| --- | --- | --- |
| `00_full_workflow.py` | 按根配置开关串联各阶段，并按 scheduler 周期续跑 | 是 |
| `01_generate_prompt_tasks.py` | Excel 转 BUZZ 任务 JSONL | 是 |
| `02_call_prompt_model.py` | 调用所选文本平台并校验 6 项 `image_plan` | 是 |
| `03b_generate_main_images.py` | 构造并生成优化主图 | 是 |
| `03_generate_and_download_images.py` | 构造并生成 6 张副图 | 是 |
| `05b_upload_main_oss.py` | 上传生成主图 | 是 |
| `05_upload_oss.py` | 上传生成副图 | 是 |
| `06_build_final_image_result.py` | 由副图日志生成最终副图表 | 是 |
| `07_export_review.py` | 导出主图+副图审核预览 | 否，手动执行 |
| `99_batch_stats.py` | 查看当前批次统计 | 否，手动执行；总流程末尾也会打印 |

注意：代码编号沿用历史阶段编号，因此存在 `03b`、`04b`、`05b`，没有独立的 `04_*.py`。实际生成结果目录仍使用 `04_generate_images` / `04b_generate_main_images`。

## 当前配置基线

业务根配置：`subtasks/walmart_image_prompt/config.json`。

当前代码读取的关键项：

- `input.excel_path`、`input.sheet_name`：本批输入；Excel 文件名决定批次名。
- `execution.max_records`：每次最多处理的未成功 SKU 数。
- `execution.concurrency`：BUZZ 并发。
- `execution.image_concurrency`：MXAPI 主图和副图并发。
- `execution.oss_concurrency`：OSS 上传并发。
- `execution.preflight_model`：正式调用文本模型前查询所选网关的 `/v1/models`。
- `workflow.buzz_sub_image_count`：除主图外，最多带给 BUZZ 的副图参考数量；当前为 4。
- `image_selection.desired_count`：最终副图目标数；当前为 5。
- `scheduler.interval_seconds`：整轮重试间隔；当前 10800 秒（3 小时）。
- `scheduler.enabled`：是否在一轮结束后自动等待并从 01 重新开始；`max_cycles=null` 表示不限制轮数。
- oss.key_template：主图和副图共用的 OSS 对象 key 规则；无效的 oss.prefix 已删除。

模型参数以阶段配置为准：

- BUZZ 首选模型：`gpt-5.6-luna`；候选模型：`gpt-5.4`；`stream=false`；`max_tokens=12000`。
- MXAPI 模型：`gpt-image-2`；`1:1`、`low`、`1K`。

根配置中的所有流程开关当前均为 true。正式运行会调用所选文本平台、生图平台和 OSS，消耗额度/产生上传；执行前应先运行 --dry-run。

## 输入 Excel

默认 Sheet 为 `Sheet1`。01 阶段至少需要：

- `SKU`
- `标题`
- `五点`
- `主图`

还支持 `副图参考1` 到 `副图参考10`。实际最多取多少张由 `workflow.buzz_sub_image_count` 控制；当前取 4 张，加上主图后每个 BUZZ 任务最多携带 5 张图片。阶段限制 `max_images_per_task=11` 为主图加最多 10 张副图参考预留。

## 批次与输出

批次名由输入 Excel 文件名决定。例如 `develop_flow_260827.xlsx` 对应：

```text
subtasks/walmart_image_prompt/batches/develop_flow_260827/
```

关键产物：

```text
batches/<批次名>/
  01_get_pic_prompt/
    generated_prompt_tasks.jsonl
  02_call_prompt_model/
    model_results.jsonl
    full_outputs/
    walmart_results.xlsx
  03b_build_main_image_input/
    walmart_main_image_input_result.xlsx
  04b_generate_main_images/
    image_generation_checkpoint.jsonl
    image_generation_results.jsonl
    walmart_main_image_generation_result.xlsx
    downloaded_images/
    raw_responses/
  03_build_image_input/
    walmart_sub_image_input_result.xlsx
  04_generate_images/
    image_generation_checkpoint.jsonl
    image_generation_results.jsonl
    walmart_sub_image_generation_result.xlsx
    downloaded_images/
    raw_responses/
  05b_upload_main_oss/
    oss_upload_checkpoint.jsonl
    oss_upload_results.jsonl
    walmart_main_image_oss_result.xlsx
  05_upload_oss/
    oss_upload_checkpoint.jsonl
    oss_upload_results.jsonl
    walmart_sub_image_oss_result.xlsx
    最终图片结果_由sub生成.xlsx
  07_review/
    审核预览.xlsx
```

同名输入文件重跑会复用同一批次目录和 checkpoint。需要完全独立的一版时，应复制并修改输入 Excel 文件名。`batches/` 已被 Git 忽略。

## 运行方式

建议使用当前环境的 Python；以下命令从项目根目录执行：

```powershell
python subtasks/walmart_image_prompt/00_full_workflow.py --dry-run
python subtasks/walmart_image_prompt/00_full_workflow.py
python subtasks/walmart_image_prompt/00_full_workflow.py --once
```

正式总流程启动后会显示执行前确认；直接回车才继续，输入任意内容会取消。默认每 3 小时重新执行一轮；`--once` 只跑一轮。

某个阶段遇到临时网络/SSL 异常时，本轮会记录错误并继续执行后面的图片查询、上传和结果构建；下一轮仍从 01 重试，且带阶段错误的轮次不会触发自动完成退出。

分步运行：

```powershell
python subtasks/walmart_image_prompt/01_generate_prompt_tasks.py --dry-run
python subtasks/walmart_image_prompt/02_call_prompt_model.py --dry-run
python subtasks/walmart_image_prompt/03b_generate_main_images.py --dry-run
python subtasks/walmart_image_prompt/03_generate_and_download_images.py --dry-run
python subtasks/walmart_image_prompt/05b_upload_main_oss.py --dry-run
python subtasks/walmart_image_prompt/05_upload_oss.py --dry-run
python subtasks/walmart_image_prompt/06_build_final_image_result.py --dry-run
```

审核与统计：

```powershell
python subtasks/walmart_image_prompt/07_export_review.py
python subtasks/walmart_image_prompt/99_batch_stats.py
```

05、05b、06 支持 `--batch-name <批次名>`；07 使用 `--batch <批次名>`。

## 断点续跑

### BUZZ

`model_results.jsonl` 中同时满足 `status=success` 和 `validation_status=passed` 的任务会跳过。失败、未调用或校验失败的任务会重跑。完整返回保存在 `full_outputs/`，主 JSONL 只保存轻量索引。

### MXAPI

- 提交成功拿到 `task_id` 后立即写 checkpoint。
- `success` 记录跳过。
- TUZI 新任务批量提交并立即保存 `task_id`，本轮不等待生成完成。
- 下一轮查询 `submitted`/`pending` 的原任务；完成后立即下载，暂未完成或查询临时异常继续保留 ID。
- 控制台按“下载成功 / 新提交 / 查询未确定 / 明确失败 / 目标已满足跳过”分别统计；查询未确定不再显示为失败。
- 控制台将“候选输入行数”和“最终目标张数”分开显示；例如 10 个 SKU × 6 个候选为 60 行，但 desired_count=5 时最终目标明确显示为 50 张。
- SKU 并发日志通过统一输出锁整行打印，避免多个线程产生粘行或异常空行；副图目标始终读取完整目标数，不会按本轮剩余候选数缩小。
- 平台明确返回生成失败时，每张图片最多按 `image_generation.max_regenerations_per_image` 重新提交；当前为2次，耗尽后终止该候选的自动生成。
- 确认上游任务永久失败后才重新提交。
- 没有 `task_id` 的失败记录可重新提交。

### OSS

主图和副图使用独立 checkpoint。已成功上传的 `(SKU, image_name)` 会跳过；对象 key 按配置生成，当前 `overwrite=true`。

`max_records` 按 SKU 数控制，而不是图片行数。每个 SKU 当前展开为 1 个主图任务和 6 个副图任务。

## 结果口径

- `06_build_final_image_result.py` 只汇总副图 OSS 结果；“处理后主图”列沿用副图生成时的参考主图，输出名也明确为 `最终图片结果_由sub生成.xlsx`。
- 新生成并上传的主图结果在 `05b_upload_main_oss/`。
- `07_export_review.py` 才会把成功生成的主图和副图合并到同一审核表，并且链接只取 OSS 上传成功结果。

## 密钥

密钥放在 `configs/local.env` 或当前进程环境变量中，不写入业务配置：

```text
BUZZ_API_KEY=...
TUZI_TEXT_API_KEY=...
TUZI_API_KEY=...
MXAPI_API_KEY=...
ALIYUN_OSS_BUCKET=...
ALIYUN_OSS_ENDPOINT=...
ALIYUN_OSS_ACCESS_KEY_ID=...
ALIYUN_OSS_ACCESS_KEY_SECRET=...
ALIYUN_OSS_DEFAULT_PREFIX=images
```

`TUZI_TEXT_API_KEY` 仅用于步骤 02 文本提示词，`TUZI_API_KEY` 仅用于主图和副图生成。两者必须分别配置。BUZZ 可用模型可用以下命令刷新查看：

```powershell
python subtasks/walmart_image_prompt/scripts/list_buzz_models.py
```

结果保存到 `scripts/output/available_buzz_models.json`。正式运行 02 时，若开启模型预检，系统会在首选模型不可用时从候选列表选择当前 Key 可用的模型；全部不可用则在正式业务调用前停止。

## Dry-run 保证

总流程 `--dry-run` 会读取 Excel 和已有批次产物用于统计，但不会：

- 调用文本模型或图片生成平台；
- 下载图片；
- 连接或上传 OSS；
- 生成或覆盖业务 JSONL、Excel、图片文件。

正式执行前应先检查 dry-run 输出中的批次名、SKU 数、已成功跳过数、待处理数、阶段开关和并发参数。
