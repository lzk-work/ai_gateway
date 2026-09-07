# generate_images 阶段

所属业务任务：`walmart_image_replace`。

**复用共享模块**（与 `walmart_image_prompt` 03 同一逻辑）：`src/ai_gateway/subtasks/mxapi_generate_images.py`，含行级 checkpoint 续跑、提交即落盘 task_id、轮询超时保留 task_id 待续跑、永久失败不再重提。

**动态行数**：不按固定 image_count 全量展开，而是按阶段 01 算出的「缺失位置」逐位置一行（每个 OSS 目录 = 一个图片任务组，SKU 列 = OSS路径）。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/generate_images/config.json`

- 03-1：`batches/<批次>/01_query_existing_images/image_inventory.jsonl` → 动态展开 `batches/<批次>/03_generate_images/image_input.xlsx`
- 03-2：image_input.xlsx + `batches/<批次>/02_generate_prompts/model_results.jsonl`（提示词，load_prompt_map 消费）
- 命名模板：`naming.image_name_template` = `new_sub{position}_{dev_sku}`（不含扩展名，下载/上传自动补 .png）

## 输出

```text
batches/<批次>/03_generate_images/image_input.xlsx
batches/<批次>/03_generate_images/image_generation_results.jsonl   # 行级：sku=OSS路径
batches/<批次>/03_generate_images/image_generation_result.xlsx
batches/<批次>/03_generate_images/downloaded_images/
batches/<批次>/03_generate_images/image_generation_checkpoint.jsonl
batches/<批次>/03_generate_images/raw_responses/
```

## 断点续跑

- 提交 MXAPI 即落盘 `task_id`（checkpoint），中断后复用原任务不重复扣费
- 轮询超时标记 pending，保留 task_id 下次续查
- 内容安全等永久失败不再重提

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 03_generate_images.py            # 正式（真实调 MXAPI）
python 03_generate_images.py --dry-run  # 预览
```
