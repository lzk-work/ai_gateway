# build_replace_result 阶段

所属业务任务：`walmart_image_replace`。

纯本地组装，无外部副作用，重跑覆盖写。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/build_replace_result/config.json`

- 阶段 01 的 `image_inventory.jsonl`（已有图、target_upload、主图链接）
- 阶段 04 的 `oss_upload_results.jsonl`（新上传 URL）

## 组装规则

- **主图**：取自入参「主图链接」列 → `mainImageUrl`（独立，不进副图数组）
- **副图**：位置 `1..target_upload`，每个位置 = 已有 OSS URL 或新图 OSS URL
- 校验缺失位置数 = 0 → `complete=true`；否则该 SKU 不可提交

## 输出

```text
batches/<批次>/05_build_replace_result/replace_payload.jsonl
```

每行：platform_sku / store / gtin / main_image_url / secondary_urls[] / final_images[] / missing_positions / complete。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 05_build_replace_result.py            # 正式
python 05_build_replace_result.py --dry-run  # 预览
```
