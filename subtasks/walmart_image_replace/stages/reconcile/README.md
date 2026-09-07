# reconcile 阶段

所属业务任务：`walmart_image_replace`。

真实外部调用阶段（只读）：对账 06 提交的沃尔玛 Feed，确认图片替换是否真实生效。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/reconcile/config.json`

- 阶段 06 的 `submit_results.jsonl`（按 (store, feed_id) 分组，feed_id 为空的 error 行不参与）

## 处理

1. 轮询 `GET /v3/feeds/{feedId}` 直到 `feedStatus=PROCESSED`（每 30 秒一次，最多 20 次，见 config.json `feed.poll`）
2. 拉取 `GET /v3/feeds/{feedId}/items`（分页），取每 SKU 的 `ingestionStatus` 与错误明细
3. 按 SKU 映射本地状态：SUCCESS/ACCEPTED→success；DATA_ERROR/SYSTEM_ERROR/PARTIAL_SUCCESS→failed；其余→in_progress

## 输出

```text
batches/<批次>/07_reconcile/reconcile_results.jsonl
```

字段：store | sku | gtin | feed_id | feed_status | status | walmart_status | errors | reconciled_at

08 报告会合并本结果，输出「沃尔玛上架状态」列。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 07_reconcile.py --dry-run   # 离线列出待对账 feed 与轮询参数，不触网
python 07_reconcile.py             # 真实轮询沃尔玛并写出对账结果
```

## 提示

- `in_progress` 的 SKU 稍后重跑 07 即可（对账幂等，只读）。
- `failed` 的 SKU 查看 errors 字段内的沃尔玛侧拒绝原因（如图片 URL 不可达）。
