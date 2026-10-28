# patent_review

Walmart 北美商品专利与版权合规审核任务。

## 输入文件

将 Excel 放在：

```text
input/source.xlsx
```

Excel 表头：

- `SKU`
- `Product Title`
- `Bullet Points`
- `Description`
- `1688 Title`
- `Main Image URL`
- `Additional Image URLs`

`主图url` 必须填写有效的主图链接；为空、空白或 `0` 时，该行会在调用API前标记为输入无效，不会执行审核。`副图url1` 至 `副图url6` 允许留空。

## 预检

```powershell
python .\subtasks\text_to_text\run.py --task patent_review --dry-run
```

## 正式运行

```powershell
python .\subtasks\text_to_text\run.py --task patent_review
```

## 续跑

```powershell
python .\subtasks\text_to_text\run.py --task patent_review --latest
```

## 重试全部失败记录

```powershell
python .\subtasks\text_to_text\run.py --task patent_review --latest --retry-failed
```

提示词是受保护资产。未经用户明确批准，不得修改 `prompt.txt`。
