# description_optimization

根据产品标题和五点描述，批量生成 Walmart 英文 Product Description。

## 输入文件

默认输入文件：

```text
input/source.xlsx
```

提示词使用以下Excel表头作为占位符：

- `标题`
- `五点`

`平台SKU`保留在输入和结果中，但不会作为唯一记录键。程序默认使用Excel行号作为内部记录键。

## 预检

```powershell
python .\subtasks\text_to_text\run.py --task description_optimization --dry-run
```

## 小批量测试

```powershell
python .\subtasks\text_to_text\run.py --task description_optimization --max-records 3
```

## 续跑同一批次

```powershell
python .\subtasks\text_to_text\run.py --task description_optimization --latest
```

## 重试失败记录

```powershell
python .\subtasks\text_to_text\run.py --task description_optimization --latest --retry-failed
```

提示词是受保护资产。未经用户明确批准，不得修改 `prompt.txt`。
