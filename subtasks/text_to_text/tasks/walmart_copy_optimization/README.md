# Walmart文案优化任务

本任务读取 `input/source.xlsx` 的 `五点入参` 工作表。提示词按 Excel 表头占位符逐行渲染，保存的提示词模板不会被程序修改。

## 预检

```powershell
python .\subtasks\text_to_text\run.py --task walmart_copy_optimization --dry-run
```

## 首次正式运行

```powershell
python .\subtasks\text_to_text\run.py --task walmart_copy_optimization
```

一次启动最多自动执行3轮。后续轮次只处理本轮配置允许自动重试的失败记录，成功记录不会重跑。

## 暂停与续跑

运行时按 `Ctrl+C`。程序停止提交新记录，等待当前调用结束并保存结果，然后返回带有 `interrupted: true` 的摘要。

继续最近批次：

```powershell
python .\subtasks\text_to_text\run.py --task walmart_copy_optimization --latest
```

继续指定批次：

```powershell
python .\subtasks\text_to_text\run.py --task walmart_copy_optimization --batch-id <批次ID>
```

人工要求重试包括永久失败在内的全部失败记录：

```powershell
python .\subtasks\text_to_text\run.py --task walmart_copy_optimization --latest --retry-failed
```

同一批次会重新读取清单中的原始输入路径。已经持久化成功且请求指纹未变化的记录会跳过；某行输入或请求配置变化后，该行请求指纹变化并自动重跑。
