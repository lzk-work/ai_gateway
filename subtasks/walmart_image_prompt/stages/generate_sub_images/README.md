# generate_sub_images 阶段

所属业务任务：`walmart_image_prompt`。

本阶段调用 MXAPI `gpt-image-2` 生成副图，属于图片生成阶段。

## 输入

```text
stages/build_sub_image_download_input/output/walmart_sub_image_input_result.xlsx
stages/call_prompt_model/output/model_results.jsonl
stages/call_prompt_model/output/full_outputs/
```

## 输出

```text
stages/generate_sub_images/output/walmart_sub_image_generation_result.xlsx
stages/generate_sub_images/output/image_generation_results.jsonl
stages/generate_sub_images/output/downloaded_images/
stages/generate_sub_images/output/raw_responses/
```

## Key 配置

设置环境变量：

```text
MXAPI_API_KEY=你的MXAPI密钥
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
- 无 `task_id` 的行会重新提交生成任务。
- 每行下载一张生成图。

## 实时 Checkpoint 与断点续跑

图片生成阶段已加入实时 checkpoint：

```text
stages/generate_sub_images/output/image_generation_checkpoint.jsonl
```

关键节点会立即落盘：

- 提交成功拿到 `task_id`：立即写入 `status=submitted`。
- 轮询完成并下载成功：更新为 `status=success`。
- 失败：写入 `status=failed` 和错误摘要。

这样即使手动中断，已经提交到 MXAPI 的 `task_id` 也不会丢。下次运行会读取 checkpoint：

- `success` 跳过。
- `submitted` 或带 `task_id` 的失败记录会继续轮询。
- 没有 `task_id` 的失败记录会重新提交。

Excel 仍然最后统一写回，避免并发频繁打开 Excel 导致锁文件或写乱。
