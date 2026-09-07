# query_existing_images 阶段

所属业务任务：`walmart_image_replace`。

本阶段只读 Excel，并真实探测 OSS 公网地址判断已有新附图（GET Range 探测，不调模型、不写外部存储）。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/query_existing_images/config.json`

读取内容：
- Excel：`input.excel_path`（任务级 `config.json` 的 `input` 段可覆盖）
- Sheet：`input.sheet_name`
- 表头映射：`columns`（中文表头 → 内部字段）
- 已有图命名正则：`naming.existing_name_pattern`
- 副图计数：`limits.min_sub_images` / `limits.max_sub_images`

## 处理

1. 列举 `OSS路径` 下匹配 `new_sub{位置}_{开发SKU}.png` 的对象，解析位置序号
2. `target_upload = min(max_sub_images, max(E, min_sub_images))`
3. 缺失位置 = `1..target_upload` 中 OSS 不存在者

## 输出

```text
batches/<批次名>/01_query_existing_images/image_inventory.jsonl
```

每行一条 SKU 记录：platform_sku / store / gtin / dev_sku / main_image_url / 标题五点 / target_upload / existing_images / missing_positions / to_generate。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 01_query_existing_images.py            # 正式
python 01_query_existing_images.py --dry-run  # 预览
```
