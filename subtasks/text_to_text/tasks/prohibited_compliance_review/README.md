# prohibited_compliance_review

用于批量执行 Walmart US Marketplace 禁售与合规性检测。

## 输入

默认输入文件：

```text
input/source.xlsx
```

必需表头：

- `SKU`
- `标题`
- `描述`
- `五点`
- `主图`

主图为空、空白或 `0` 时，该行会标记为 `input_invalid`，不会调用API。

## 输出

模型必须返回提示词规定的8字段JSON。程序会校验：

- 字段名称和顺序；
- 所有字段值均为字符串；
- 返回SKU与输入SKU一致；
- 风险等级和Yes/No枚举；
- PASS与风险判断一致；
- 核心风险类别包含在涵盖风险中。

## 预检

```powershell
python .\subtasks\text_to_text\run.py --task prohibited_compliance_review --dry-run
```

## 小批量真实测试

```powershell
python .\subtasks\text_to_text\run.py --task prohibited_compliance_review --max-records 3
```

## 续跑

```powershell
python .\subtasks\text_to_text\run.py --task prohibited_compliance_review --latest
```

## 重试全部失败记录

```powershell
python .\subtasks\text_to_text\run.py --task prohibited_compliance_review --latest --retry-failed
```

## 能力边界

该任务会将文字和商品主图发送给模型，但当前一次性Chat Completions调用没有为模型提供Walmart政策网站或美国监管数据库的搜索工具。除非所配置的具体模型和中转渠道明确提供并实际执行联网检索，否则返回内容不能证明提示词要求的官方政策检索已经完成。正式合规决策应核验政策来源和时效。

提示词是受保护资产。未经用户明确批准，不得修改 `prompt.txt`。
