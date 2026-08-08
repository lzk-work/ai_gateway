# upload_oss 阶段

所属业务任务：`walmart_image_prompt`。

本阶段把当前批次已经下载到本地的图片上传到阿里云 OSS。

## 输入

运行时由批次路径自动覆盖：

```text
batches/<批次名>/04_generate_images/walmart_sub_image_generation_result.xlsx
batches/<批次名>/04_generate_images/downloaded_images/
```

## 输出

```text
batches/<批次名>/05_upload_oss/oss_upload_checkpoint.jsonl
batches/<批次名>/05_upload_oss/oss_upload_results.jsonl
batches/<批次名>/05_upload_oss/walmart_sub_image_oss_result.xlsx
```

## Key 配置

OSS 平台级配置放环境变量或项目本地文件：

```text
configs/local.env
```

字段：

```text
ALIYUN_OSS_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_BUCKET=zlx-oss-db
ALIYUN_OSS_DEFAULT_PREFIX=images
```

## 运行

先试运行：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --dry-run
```

确认无误后正式上传：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py
```

## 断点续跑

每张图片按 `SKU + 图片命名` 记录状态：

- `success`：下次跳过。
- `skipped`：OSS 已存在且配置为不覆盖，下次跳过。
- `failed`：下次重试。
- `missing_file`：本地图片不存在，等待图片生成阶段补齐后再重跑。

