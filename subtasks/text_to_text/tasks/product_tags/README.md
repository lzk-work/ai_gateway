# 产品标签任务

本任务读取 `input/source.xlsx` 的 `Sheet1`，每一行独立调用一次文本模型，并将提示词要求的21个JSON字段拆分写入结果表。

提示词是用户提供的受保护资产，程序仅在运行时替换 `SKU`、`标题`、`描述`、`五点` 四个占位符，不修改保存的模板。

## 预检

```powershell
python .\subtasks\text_to_text\run.py --task product_tags --dry-run
```

## 正式运行

```powershell
python .\subtasks\text_to_text\run.py --task product_tags
```

## 续跑

```powershell
python .\subtasks\text_to_text\run.py --task product_tags --latest
```

任务最多自动执行3轮，后续轮次仅重试接口瞬时失败和结果校验失败的记录。已成功且请求指纹未变化的记录不会重跑。
