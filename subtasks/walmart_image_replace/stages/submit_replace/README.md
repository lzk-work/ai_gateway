# submit_replace 阶段

所属业务任务：`walmart_image_replace`。

真实外部调用阶段：把 05 组装好的完整图片集提交到沃尔玛 Marketplace，替换商品图片。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/submit_replace/config.json`

- 阶段 05 的 `replace_payload.jsonl`（platform_sku / gtin / main_image_url / secondary_urls）
- 店铺凭证：`configs/local.env` 中 `WALMART_STORE_RLX_CLIENT_ID` 等（见 config.json `walmart_api.stores`）

## 处理

1. 过滤：仅提交 `complete=True` 且店铺在配置内的 SKU（沃尔玛图片属性为**全量替换**，不完整集合会丢已有副图）
2. 分组：按店铺分组，每店铺一个 MPItemFeed XML（`AdditionalProductAttributes/ImageUrls`：主图 + 顺序副图）
3. 提交：`POST /v3/feeds?feedType=item`（先 `POST /v3/token` 换 access_token）
4. 记录：每个 SKU 一行写入 `submit_results.jsonl`（含 feedId），checkpoint 键为 (store, sku)

## 输出

```text
batches/<批次>/06_submit_replace/submit_results.jsonl
```

字段：store | sku | gtin | feed_id | status(submitted/error) | error | submitted_at

## 续跑

已成功提交（submitted/success/processed）的 SKU 跳过；error 行重跑时会重新提交。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 06_submit_replace.py --dry-run   # 离线预览将发送的 Feed XML，不触网
python 06_submit_replace.py             # 真实提交到沃尔玛
```

## 逻辑测试（不真实改动）

`--dry-run` 使用真实批次数据构造并打印 Feed XML，可肉眼核对 SKU、GTIN、主图、副图顺序与数量；不调用任何沃尔玛接口、不写文件。
