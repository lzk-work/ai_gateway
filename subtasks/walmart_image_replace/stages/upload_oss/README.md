# upload_oss 阶段

所属业务任务：`walmart_image_replace`。

**复用共享模块**（与 `walmart_image_prompt` 05 同一逻辑）：`src/ai_gateway/subtasks/oss_upload_images.py`，行级 checkpoint、并发上传、幂等续跑。

## 输入

配置文件：`subtasks/walmart_image_replace/stages/upload_oss/config.json`

- 上游：`batches/<批次>/03_generate_images/image_generation_results.jsonl`（行级，sku=OSS路径）
- OSS key 模板：`oss.key_template` = `{sku}/{image_name}.png`
  - `{sku}` = 入参「OSS路径」列值（如 `develop/DEV_A001`）——图片落在与已有新附图相同的目录
  - `{image_name}` 为**不含扩展名**的文件名（共享模块传 stem），模板需自带 `.png`

## 输出

```text
batches/<批次>/04_upload_oss/oss_upload_results.jsonl   # 行级：sku=OSS路径
batches/<批次>/04_upload_oss/oss_upload_checkpoint.jsonl
batches/<批次>/04_upload_oss/oss_upload_result.xlsx
```

每行一张图：sku（OSS路径） / image_name / status / oss_key / oss_url。

## 幂等续跑

按 object key（sku::image_name）幂等，已 `success`/`skipped` 的跳过，同 key 覆盖无害。

## 单独运行

```bash
cd E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace
python 04_upload_oss.py            # 正式（真实连 OSS）
python 04_upload_oss.py --dry-run  # 预览
```
