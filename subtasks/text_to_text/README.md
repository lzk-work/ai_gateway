# 通用文本批处理

完整操作步骤参见 [使用说明.md](使用说明.md)。

`text_to_text` 将表格中的每一行渲染为一条完整提示词，随后以单条 `user` 消息独立调用兔子文本 API。框架不理解具体业务字段；Excel 表头通过 `{{ 表头 }}` 直接成为提示词占位符。

## 目录职责

- `src/ai_gateway/text_to_text/`：通用输入、模板、调用、状态和导出引擎。
- `tasks/<任务名>/`：一个完整子任务，包含任务配置、提示词、输入目录、批次输出和可选业务校验器。

每个子任务的结构固定为：

```text
tasks/<任务名>/
  task.json
  prompt.txt
  validator.py          可选
  input/
    source.xlsx
  batches/
    <批次ID>/
      manifest.json
      state.sqlite3
      snapshots/
      raw_outputs/
      results.jsonl
      result.xlsx
```

不同子任务的输入、状态和输出不会混放。

## 运行1688任务

```powershell
python subtasks\text_to_text\run.py --task keyword_1688 --dry-run
python subtasks\text_to_text\run.py --task keyword_1688
```

以上命令默认读取 `tasks/keyword_1688/input/source.xlsx`。也可以通过 `--input` 临时指定该任务的其他源文件。

首次正式运行会返回 `batch_id`。修改原始输入文件后，用同一批次续跑：

```powershell
python subtasks\text_to_text\run.py --task keyword_1688 --batch-id <批次ID>
```

也可以使用 `--latest` 续跑最近批次。续跑会重新读取清单中的原始输入路径。默认以 Excel 行号作为内部记录键，不假设 SKU 或其他业务字段唯一。完整请求指纹未变化的成功记录会跳过；原始单元格、提示词、模型或响应契约发生变化时会自动重跑。

如需重试同一批次中的全部失败记录（包括接口失败和结果校验失败），使用：

```powershell
python .\subtasks\text_to_text\run.py --task keyword_1688 --latest --retry-failed
```

该参数不会重跑请求指纹未变化的成功记录。

任务也可以选择性读取多个图片链接列，并将文字和图片放在同一个 `user` 消息中发送。未配置图片列的任务仍按原来的纯文本格式发送。

在新任务的 `task.json` 的 `input` 中声明图片列：

```json
"image_url_columns": ["主图链接", "附图链接"]
```

每个配置列可以存放一个链接，也可以在同一单元格中每行填写一个链接。重复链接会按首次出现顺序去重。可在 `gateway` 中设置 `"image_detail": "auto"`、`"low"` 或 `"high"`。图片链接及 detail 会进入请求指纹，图片变化后该行会自动重新处理。

如某些图片列为必填，可在 `input` 中增加 `"required_image_url_columns": ["主图url"]`。必填图片为空、空白或 `0` 时，该行会标记为 `input_invalid`，不会调用API；非必填图片列允许缺失。

## 新增任务

在 `tasks/` 下创建目录，至少提供 `task.json` 和 `prompt.txt`。模板中可直接使用任意 Excel 表头，例如 `{{ 标题 }}`、`{{ Product Description }}`。任务可选择 `raw_text`、`fixed_fields` 或 `json` 响应类型，并可提供独立 `validator.py`。

输入文件只读，模型结果只写入当前子任务 `batches/<批次ID>/result.xlsx`；`state.sqlite3` 是唯一运行状态源。

通用引擎只读取提示词中实际存在的 `{{ 表头 }}` 占位符，不预设表头名称、必填字段或人工控制列。表头修改后，如果提示词占位符没有同步匹配，dry-run 会停止并列出缺失占位符，不会自动猜测或修改提示词。业务唯一键、必填字段和控制列只有在用户主动写入 `task.json` 后才启用。
