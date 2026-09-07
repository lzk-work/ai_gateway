# generate_sub_images 阶段

所属业务任务：`walmart_image_prompt`。

本阶段使用总配置 image_provider 选定的平台生成副图。阶段仅保留 execution.model、Sheet、列映射、limits/retry/resume；网关和输入输出路径已删除，由业务入口统一组装。详见 [配置归属](../../CONFIGURATION.md)。

## 输入

```text
batches/<批次名>/03_build_image_input/walmart_sub_image_input_result.xlsx
batches/<批次名>/02_call_buzz_model/model_results.jsonl
batches/<批次名>/02_call_buzz_model/full_outputs/
```

## 输出

```text
batches/<批次名>/04_generate_images/walmart_sub_image_generation_result.xlsx
batches/<批次名>/04_generate_images/image_generation_results.jsonl
batches/<批次名>/04_generate_images/downloaded_images/
batches/<批次名>/04_generate_images/raw_responses/
```

## Key 配置

设置环境变量：

```text
TUZI_API_KEY=你的兔子密钥
MXAPI_API_KEY=你的MXAPI备用密钥
```

也可以写入项目本地文件：

```text
configs/local.env
```

## 运行

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\03_generate_and_download_images.py
```

## 规则

- 只处理未成功的行。
- 已成功行会跳过。
- 有 `task_id` 的失败行会优先继续轮询。
- 无 task_id 的行按平台提交上限尝试；兔子从网关 max_retries 读取额外重试次数，submission_unknown 续跑会告警并再尝试，可能重复扣费。
- 每行下载一张生成图。

## 实时 Checkpoint 与断点续跑

图片生成阶段已加入实时 checkpoint：

```text
batches/<批次名>/04_generate_images/image_generation_checkpoint.jsonl
```

关键节点会立即落盘：

- 提交成功拿到 `task_id`：立即写入 `status=submitted`。
- 轮询完成并下载成功：更新为 `status=success`。
- 失败：写入 `status=failed` 和错误摘要。

已成功持久化的 task_id 可用于断点恢复；写盘失败不能保证 ID 已保存。兔子会停止执行，MXAPI 保留旧告警行为。下次运行会读取 checkpoint：

- `success` 跳过。
- `submitted` 或带 `task_id` 的失败记录会继续轮询。
- 没有 task_id 的失败或 submission_unknown 记录可按有限重试策略重新提交。

Excel 仍然最后统一写回，避免并发频繁打开 Excel 导致锁文件或写乱。
