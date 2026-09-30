# Walmart 图片替换单条离线模拟报告

日期：2026-09-22

## 模拟边界

本次只验证“输入分析 → 新模板请求 → 模型结果校验 → 生图Excel入参”链路。文字模型返回由本地 Mock 提供；测试夹具禁止 `requests` 和 `urllib` 网络访问。未调用真实文字模型，未提交生图任务，未查询或下载图片，未调用 OSS，也未调用 Walmart API。

## 单条输入

| 字段 | 模拟值 |
| --- | --- |
| 来源 SKU | SOURCE |
| 结果 SKU | RESULT |
| 店铺 | store |
| 标题 | Bottle |
| 五点 | Steel；Portable |
| 参考图片 | 1张Walmart主图＋1张Walmart副图 |
| 已有主图 | 1张，原样保留 |
| 已有新副图 | 2张 |
| 动态计划 | 缺2张新副图 |

## 实际验证过程

1. `prepare()` 将该行识别为主图补0张、副图补2张，并创建两个稳定的新副图名称。
2. `prompt_stage()` 读取新的 `walmart_image_replace_template.txt`，将标题、五点和数量2填入模板，并按主图在前、副图在后的顺序附加两张Walmart参考图。
3. Mock文字模型返回完整JSON：包含产品分析、两个不同副图类型、两个连续编号的 `image_plan`、六组公共限制以及全部通过的最终检查项。
4. `validate_prompt()` 确认JSON对象、动态数量、连续编号、允许且不重复的设计类型、必需字段、提示词有效长度、公共限制及最终检查项。
5. `build_image_input()` 生成两行待生图入参。每行“生成提示词”由该图片的差异化 `ai_image_generation_prompt` 和完整 `Global Prompt Restrictions` 组成。
6. 测试在生图引擎运行前结束，没有创建平台图片任务和OSS对象。

## 验证结果

- 新模板确实进入文字模型请求，动态占位符被替换为2。
- 返回2条方案，结构校验通过。
- 参考主副图都进入文字模型图片输入。
- 生图Excel中的最终提示词包含公共限制。
- 旧版仅含 `image_number` 和 `ai_image_generation_prompt` 的简化结果会被拒绝。
- 缺少任一必需公共限制的结果会被拒绝。
- replace专项测试：56项通过。

执行命令：

```powershell
python -m pytest tests/test_walmart_image_replace.py -q -p no:cacheprovider --basetemp=.pytest_tmp_replace_full
```
