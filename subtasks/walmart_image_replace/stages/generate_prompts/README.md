# generate_prompts 阶段

所属业务任务：`walmart_image_replace`。

**真实链路**：按缺失位置调用 BUZZ（OpenAI 兼容接口 `https://buzzai.cc/v1/chat/completions`，model `gpt-5.4`），用 `prompts/walmart_image_replace_template.txt` 渲染后的标题/五点作 user 提示词，生成副图提示词。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/generate_prompts/config.json`

- 上游：`batches/<批次>/01_query_existing_images/image_inventory.jsonl`
- 提示词入参：主图链接 + 已有副图 + 标题 + 五点（单单元格，五条卖点合并）

## 输出

与 `walmart_image_prompt` 的 02 阶段同构，供共享模块 `mxapi_generate_images.load_prompt_map` 直接消费：

```text
batches/<批次>/02_generate_prompts/model_results.jsonl
batches/<批次>/02_generate_prompts/full_outputs/<sku>.json
```

- `model_results.jsonl` 每行：sku（=OSS路径，按目录去重） / status / validation_status / full_output_path / platform_skus
- `full_outputs/<sku>.json`：`{global_prompt_restrictions, image_plan: [{image_number=缺失位置, ai_image_generation_prompt}]}`

## 校验

image_plan 条数必须 = 该目录的 `to_generate`（缺失位置数）。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 02_generate_prompts.py            # 正式
python 02_generate_prompts.py --dry-run  # 预览
```
