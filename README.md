# AI Gateway 项目说明

本项目用于批量调用不同中转站和模型接口，支持 Excel/数据库输入、批处理、日志记录、失败重试、JSON 结果校验和结果写回。

当前已落地的业务任务是：

```text
subtasks/walmart_image_prompt/
```

它是一个完整业务任务，不是零散脚本。业务任务内部再按阶段拆分。

## 当前业务任务结构

```text
subtasks/walmart_image_prompt/
  README.md
  input/             业务入参文件
  prompts/           业务提示词模板
  00_full_workflow.py
  01_generate_prompt_tasks.py
  02_call_buzz_model.py
  03_generate_and_download_images.py
  05_upload_oss.py
  workflow_common.py
  stages/
    get_pic_prompt/
      config.json
      README.md
      output/generated_prompt_tasks.jsonl
    call_prompt_model/
      config.json
      README.md
      output/model_results.jsonl
      output/walmart_results.xlsx
      output/full_outputs/
  scripts/
```

## 如何运行

执行总流程：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\00_full_workflow.py
```

总流程按 `subtasks/walmart_image_prompt/config.json` 中的 `workflow` 开关决定执行哪些阶段。默认不会执行图片生成下载，避免误消耗 MXAPI 额度。

分步执行：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\01_generate_prompt_tasks.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\02_call_buzz_model.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\03_generate_and_download_images.py
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --dry-run
```

## 配置位置

业务总配置：

```text
subtasks/walmart_image_prompt/config.json
```

本批入参 Excel 在业务总配置里修改：

```json
"input": {
  "excel_path": "E:/WorkSpace/ai_gateway/subtasks/walmart_image_prompt/input/walmart_flow.xlsx",
  "sheet_name": "Sheet1"
}
```

第二阶段配置：

```text
subtasks/walmart_image_prompt/config.json
```

每个业务任务、每个阶段都应该有自己的配置文件。模型、中转站、输入文件、输出文件都写在阶段配置里，不要散放到项目根目录。

## 输出位置

```text
subtasks/walmart_image_prompt/batches/<入参文件名>/01_get_pic_prompt/generated_prompt_tasks.jsonl
subtasks/walmart_image_prompt/batches/<入参文件名>/02_call_buzz_model/model_results.jsonl
subtasks/walmart_image_prompt/batches/<入参文件名>/02_call_buzz_model/full_outputs/
subtasks/walmart_image_prompt/batches/<入参文件名>/02_call_buzz_model/walmart_results.xlsx
subtasks/walmart_image_prompt/batches/<入参文件名>/04_generate_images/downloaded_images/
subtasks/walmart_image_prompt/batches/<入参文件名>/05_upload_oss/oss_upload_results.jsonl
subtasks/walmart_image_prompt/batches/<入参文件名>/05_upload_oss/walmart_sub_image_oss_result.xlsx
```

批次名由入参 Excel 文件名决定。重跑同一个文件会继续使用同一个批次目录；需要独立重跑一版时，先改入参文件名。

## 代码分层

```text
src/ai_gateway/
  clients/        通用 API 客户端
  config/         配置加载
  gateways/       中转站适配
  validators/     结果校验
  subtasks/       可复用阶段实现代码
subtasks/
  <业务任务>/      业务任务配置、启动脚本、阶段输出、业务说明
configs/
  gateways.yaml   全局中转站基础配置
  models.yaml     全局模型基础配置
```

注意：`src/ai_gateway/subtasks/` 里是可复用代码模块，不等于业务任务目录。真正的业务任务放在项目根目录的 `subtasks/<business_task_name>/` 下。

## 新增业务任务规范

新增业务任务时按下面模板建立：

```text
subtasks/<business_task_name>/
  README.md
  input/             业务入参文件
  prompts/           业务提示词模板
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

公共逻辑写到 `src/ai_gateway/`，业务专属入参、出参、提示词模板、配置和启动脚本都放到自己的业务任务目录。

## 相关文档

- `docs/architecture.md`：项目架构说明
- `docs/user_manual.md`：使用说明书
- `docs/framework_notes.md`：后续扩展注意事项
- `subtasks/walmart_image_prompt/README.md`：当前 Walmart 业务任务说明






