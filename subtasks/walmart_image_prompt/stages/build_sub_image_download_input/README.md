# build_sub_image_download_input 阶段

所属业务任务：`walmart_image_prompt`。

本阶段根据模型结果中已经成功并通过校验的 SKU，生成副图下载/上传入参模板。

## 输入

配置文件：

```text
subtasks/walmart_image_prompt/stages/build_sub_image_download_input/config.json
```

读取：

- 源 Excel：`input.source_excel_path`
- 模型结果：`input.model_results_path`
- 下载模板：`input.template_path`

下载模板文件放在业务目录：

```text
subtasks/walmart_image_prompt/templates/sub_image_download_template.xlsx
```

## 生成规则

- 只处理 `model_results.jsonl` 中 `status=success` 且 `validation_status=passed` 的 SKU。
- 每个成功 SKU 生成 6 行。
- `参考图片链接` 使用源 Excel 的 `主图`。
- `图片命名` 使用 `new_sub{序号}_{SKU}`。
- 不再提前生成 `OSS上传结果` 和 `结果确认`；OSS 目标地址由 05 上传阶段按当前配置实时生成。

## 运行

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\scripts\build_sub_image_download_input.py
```

## 输出

```text
subtasks/walmart_image_prompt/stages/build_sub_image_download_input/output/walmart_sub_image_input_result.xlsx
```
