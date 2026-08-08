# get_pic_prompt 阶段

所属业务任务：`walmart_image_prompt`。

本阶段只做本地数据准备，不调用中转站、不消耗模型费用。

## 输入

配置文件：

```text
subtasks/walmart_image_prompt/stages/get_pic_prompt/config.json
```

读取内容：

- Excel 文件：`input.excel_path`
- Sheet：`input.sheet_name`
- 提示词模板：`input.prompt_template_path`
- SKU 列：`columns.task_id`
- 标题列：`columns.title`
- 五点列：`columns.bullets`
- 图片列：`columns.images`

## 输出

```text
subtasks/walmart_image_prompt/stages/get_pic_prompt/output/generated_prompt_tasks.jsonl
```

每一行是一条后续模型调用任务，包含：

- `task_id`
- `sku`
- `prompt_text`
- `images`
- `metadata`
- `precheck_status`

## 单独运行

```powershell
cd E:\WorkSpace\ai_gateway
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\01_generate_prompt_tasks.py
```
