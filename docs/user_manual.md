# AI Gateway 使用说明

本说明聚焦当前已完善的 `walmart_image_prompt` 图片生成任务。完整字段、批次目录和断点续跑规则见 `subtasks/walmart_image_prompt/README.md`。

## 1. 环境准备

安装依赖：

```powershell
pip install -r requirements.txt
```

在 `configs/local.env` 配置：

```text
BUZZ_API_KEY=...
MXAPI_API_KEY=...
ALIYUN_OSS_BUCKET=...
ALIYUN_OSS_ENDPOINT=...
ALIYUN_OSS_ACCESS_KEY_ID=...
ALIYUN_OSS_ACCESS_KEY_SECRET=...
ALIYUN_OSS_DEFAULT_PREFIX=images
```

密钥也可以放在当前进程环境变量中；环境变量优先于 `local.env`。不要把真实密钥写入阶段 JSON 或提交到 Git。

## 2. 配置本批任务

修改 `subtasks/walmart_image_prompt/config.json`：

- `input.excel_path`：输入 Excel；文件名决定批次名。
- `input.sheet_name`：默认 `Sheet1`。
- `execution.max_records`：本次最多处理的未成功 SKU 数。
- `execution.concurrency`：BUZZ 并发。
- `execution.image_concurrency`：MXAPI 并发。
- `execution.oss_concurrency`：OSS 上传并发。
- `workflow.*`：阶段开关。
- `workflow.buzz_sub_image_count`：给 BUZZ 的副图参考张数。
- `oss.*`：OSS key 规则。

当前阶段配置为：BUZZ 首选 `gpt-5.6-luna`、候选 `gpt-5.4`、非流式；MXAPI 使用 `gpt-image-2`，生成参数为 1:1、low、1K。以后以各阶段 `config.json` 的实际值为准。

输入 Excel 至少应有 `SKU`、`标题`、`五点`、`主图`，可选 `副图参考1` 至 `副图参考10`。

## 3. 先试运行

从项目根目录执行：

```powershell
python subtasks/walmart_image_prompt/00_full_workflow.py --dry-run
```

试运行会显示：

- 批次名和批次目录；
- Excel 有效 SKU 数；
- 各阶段开关；
- 模型、并发和 API 配置；
- 已成功跳过、待处理和本次选择数量；
- 主图与副图 checkpoint 状态。

试运行不会调用文本/图片模型、不会上传 OSS，也不会写业务结果文件。

## 4. 正式运行

```powershell
python subtasks/walmart_image_prompt/00_full_workflow.py
```

总流程实际顺序：

1. 01 生成 BUZZ 提示词任务。
2. 02 调 BUZZ 生成并校验 6 张副图方案。
3. 03b 调 MXAPI 生成优化主图。
4. 03 调 MXAPI 生成 6 张副图；开启主图生成时，只处理主图成功的 SKU。
5. 05b 上传主图 OSS。
6. 05 上传副图 OSS。
7. 06 生成副图结果表。
8. 打印批次统计。

正式执行前会要求确认。当前根配置的所有流程开关均为 `true`，因此会产生模型额度消耗和 OSS 写入。

## 5. 分步运行

```powershell
python subtasks/walmart_image_prompt/01_generate_prompt_tasks.py
python subtasks/walmart_image_prompt/02_call_prompt_model.py
python subtasks/walmart_image_prompt/03b_generate_main_images.py
python subtasks/walmart_image_prompt/03_generate_and_download_images.py
python subtasks/walmart_image_prompt/05b_upload_main_oss.py
python subtasks/walmart_image_prompt/05_upload_oss.py
python subtasks/walmart_image_prompt/06_build_final_image_result.py
```

以上阶段都支持 `--dry-run`。05、05b、06 还支持 `--batch-name`。

审核预览不在总流程内，手动执行：

```powershell
python subtasks/walmart_image_prompt/07_export_review.py
python subtasks/walmart_image_prompt/07_export_review.py --batch <批次名>
```

查看统计：

```powershell
python subtasks/walmart_image_prompt/99_batch_stats.py
```

## 6. 断点续跑

- BUZZ：成功且校验通过的 SKU 跳过；其他记录重跑。
- MXAPI：提交后立即保存 `task_id`；中断后优先继续轮询原任务，避免重复提交和重复扣费。
- OSS：主图、副图各自保存 checkpoint；成功对象跳过。
- `max_records` 按 SKU 计算，不按展开后的图片行数计算。

同一个输入文件会继续使用同一个 `batches/<输入文件名>/`。若要重新建立一套互不影响的结果，请更换输入 Excel 文件名。

## 7. 输出说明

- 文本模型完整输出：`02_call_prompt_model/full_outputs/`。
- 主图生成结果：`04b_generate_main_images/`。
- 副图生成结果：`04_generate_images/`。
- 主图 OSS 结果：`05b_upload_main_oss/`。
- 副图 OSS 结果及最终副图表：`05_upload_oss/`。
- 主图+副图审核预览：`07_review/审核预览.xlsx`。

06 的 `最终图片结果_由sub生成.xlsx` 是副图口径；生成的新主图不会写进该文件。需要查看合并后的生成主图、副图和 OSS 链接时使用 07 审核预览。

## 8. 常见问题

### BUZZ 模型不可用

执行：

```powershell
python subtasks/walmart_image_prompt/scripts/list_buzz_models.py
```

然后检查 `stages/call_prompt_model/config.json` 的首选和候选模型。正式 02 阶段默认会预检 `/v1/models`；没有任何配置模型可用时会在业务调用前停止。

### 图片任务中断

不要删除 checkpoint。重新运行对应 03/03b 阶段，程序会继续轮询已有 `task_id`；只有没有可复用任务或确认永久失败时才重新提交。

### 需要重新跑一整批

复制输入 Excel 并使用新文件名，再修改根配置的 `input.excel_path`。直接删除 checkpoint 会失去已有任务关联，可能导致重复调用。
