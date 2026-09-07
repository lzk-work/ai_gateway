# build_report 阶段

所属业务任务：`walmart_image_replace`。

纯派生阶段，无外部副作用；每次重跑覆盖写，报告始终反映批次最新状态。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/build_report/config.json`

- 阶段 05 的 `replace_payload.jsonl`（图片链接、GTIN、complete 标志）
- 阶段 04 的 `oss_upload_results.jsonl`（真实 OSS 上传结果，用于核对）
- 阶段 07 的 `reconcile_results.jsonl`（可选；存在时合并出「沃尔玛上架状态」列）

## 输出

```text
batches/<批次>/08_build_report/result_report.jsonl
batches/<批次>/08_build_report/result_report.xlsx
```

报告列（中文表头）：店铺 | 平台SKU | GTIN | 上传的图片链接 | 是否成功 | 失败原因 | 沃尔玛上架状态 | 沃尔玛失败原因

## 状态优先级

`是否成功` = 替换结果 complete（全部副图已生成并上传 OSS）；失败原因仅未完整时输出缺失位置。
`沃尔玛上架状态` 来自 07 对账（成功/失败/处理中）；未运行 06/07 时显示「未提交」。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 08_build_report.py            # 正式
python 08_build_report.py --dry-run  # 预览
```
