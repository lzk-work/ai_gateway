# OSS 上传阶段接入设计

## 目标

在 `walmart_image_prompt` 业务任务中新增 OSS 上传阶段，把当前批次已生成并下载成功的图片上传到阿里云 OSS。

核心原则：

- 阿里云账号、Bucket、Endpoint 等平台级配置放到环境变量或 `configs/local.env`。
- 上传哪些文件、从哪个批次目录读取、上传到哪个业务路径，由业务任务配置和批次结果决定。
- 不在 OSS 客户端里硬编码本地目录、业务 SKU 规则、文件名正则或批次名。
- 每张图片独立记录上传状态，支持断点续跑。

## 参考代码提取结论

参考项目中的 `OSSUploader` 可提取为通用 OSS 客户端能力：

- 初始化 OSS bucket。
- 单文件上传。
- 批量并发上传。
- 判断对象是否存在。
- 生成公共访问 URL。
- 失败重试。

参考 `upload.py` 中可借鉴的能力：

- 并发上传。
- 分批处理，避免一次性任务过大。
- dry-run 预览上传路径。
- 上传历史结果表。
- 跳过已成功上传的文件。

不直接沿用的部分：

- 不使用硬编码 `local_dir`。
- 不使用固定 `UPLOAD_SETTINGS`。
- 不通过控制台交互选择真实/模拟上传，统一使用 `--dry-run`。
- 不用长期单一 `upload_result.xlsx` 判断增量，改为当前业务批次内的 checkpoint/jsonl。
- 不把 AK/SK 写在 Python 配置文件中。

## 环境配置

OSS 平台级配置放系统环境变量，或项目本地文件：

```text
E:/WorkSpace/ai_gateway/configs/local.env
```

建议字段：

```text
ALIYUN_OSS_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_OSS_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
ALIYUN_OSS_BUCKET=zlx-oss-db
ALIYUN_OSS_DEFAULT_PREFIX=images
```

可选字段：

```text
ALIYUN_OSS_CONNECT_TIMEOUT=30
ALIYUN_OSS_MAX_RETRIES=3
ALIYUN_OSS_OVERWRITE=true
```

`configs/local.env` 已由 `.gitignore` 忽略，不能提交到 Git。

## 业务批次输入

批次由入参 Excel 文件名决定，例如：

```text
input/walmart_flow.xlsx
```

对应批次：

```text
subtasks/walmart_image_prompt/batches/walmart_flow/
```

OSS 上传阶段读取当前批次的图片生成结果：

```text
batches/walmart_flow/
  03_build_image_input/walmart_sub_image_input_result.xlsx
  04_generate_images/walmart_sub_image_generation_result.xlsx
  04_generate_images/downloaded_images/
```

优先使用 `04_generate_images/walmart_sub_image_generation_result.xlsx` 中的下载状态和 `task_id`。如果该文件不存在，可以回退读取 `03_build_image_input/walmart_sub_image_input_result.xlsx`，但只有本地图片存在的记录才进入上传候选。

## 新增阶段目录

新增阶段：

```text
subtasks/walmart_image_prompt/stages/upload_oss/
  config.json
  README.md
```

批次输出目录：

```text
batches/<批次名>/05_upload_oss/
  oss_upload_checkpoint.jsonl
  oss_upload_results.jsonl
  walmart_sub_image_oss_result.xlsx
```

图片仍保留在：

```text
batches/<批次名>/04_generate_images/downloaded_images/
```

## 阶段配置

阶段配置只描述业务字段和上传规则，不保存密钥：

```json
{
  "name": "upload_oss",
  "description": "上传当前批次已下载图片到阿里云 OSS。",
  "execution": {
    "type": "oss_upload",
    "provider": "aliyun_oss"
  },
  "input": {
    "image_result_excel_path": "",
    "download_dir": ""
  },
  "output": {
    "excel_path": "",
    "results_path": "",
    "checkpoint_path": ""
  },
  "oss": {
    "prefix": "develop",
    "key_template": "develop/{sku}/{image_name}.png",
    "url_template": null,
    "overwrite": true
  },
  "columns": {
    "sku": "SKU",
    "image_name": "图片命名",
    "download_status": "下载结果",
    "task_id": "task_id"
  },
  "limits": {
    "max_workers": 10,
    "batch_size": 500
  },
  "resume": {
    "skip_success": true
  }
}
```

实际运行时，入口脚本会根据当前批次覆盖 `input` 和 `output` 路径。

## OSS Key 规则

当前 Walmart 副图文件名：

```text
new_sub1_<SKU>.png
new_sub2_<SKU>.png
```

上传到 OSS 的 object key 建议为：

```text
images/develop/<SKU>/new_sub1_<SKU>.png
```

其中：

- `images` 来自 `ALIYUN_OSS_DEFAULT_PREFIX`。
- `develop/{sku}/{image_name}.png` 来自业务阶段配置。
- `sku` 和 `image_name` 来自批次 Excel。

上传阶段不再读取 Excel 中预生成的 `OSS上传结果` 或 `结果确认`；目标 URL 始终根据当前 OSS 配置实时生成，避免旧表格残留地址覆盖新配置。

## 断点续跑

每张图独立记录上传状态，唯一键：

```text
SKU + 图片命名
```

checkpoint：

```text
batches/<批次名>/05_upload_oss/oss_upload_checkpoint.jsonl
```

状态规则：

- `success`：已上传成功，下次跳过。
- `skipped`：OSS 已存在且配置为不覆盖，也视为成功。
- `failed`：下次重试。
- `missing_file`：本地图片不存在，不重试，等待图片生成阶段补齐后再运行。

正式结果：

```text
batches/<批次名>/05_upload_oss/oss_upload_results.jsonl
```

Excel 写回：

```text
batches/<批次名>/05_upload_oss/walmart_sub_image_oss_result.xlsx
```

Excel 写回字段建议：

- `OSS上传状态`
- `OSS上传URL`
- `OSS上传错误`
- `OSS上传时间`

保留原有 `SKU`、`参考图片链接`、`图片命名`、`下载结果`、`task_id`。`OSS上传结果` 和 `结果确认` 不再提前生成。

## 控制台输出

试运行：

```text
=== 05 上传 OSS | 试运行 ===
批次名: walmart_flow
图片总数: 654
已成功跳过: 0
本次将上传: 654
并发: 10
样例:
  [1] SKU=ZJ-xxx | 图片=new_sub1_ZJ-xxx.png | OSS=images/develop/ZJ-xxx/new_sub1_ZJ-xxx.png
```

正式运行：

```text
=== 05 上传 OSS ===
批次名: walmart_flow
图片总数: 654 | 已成功跳过: 120 | 本次待上传: 534
[1/534] 开始上传 | SKU=ZJ-xxx | 图片=new_sub1_ZJ-xxx.png
[1/534] 上传成功 | URL=https://...
```

## 总流程接入

业务总配置增加阶段开关：

```json
"workflow": {
  "generate_prompt_tasks": true,
  "call_buzz_model": true,
  "generate_and_download_images": true,
  "upload_oss": false
}
```

新增入口：

```text
05_upload_oss.py
```

总流程 `00_full_workflow.py` 中按开关执行：

```text
01 -> 02 -> 03 -> 05
```

默认 `upload_oss=false`，避免误上传。需要上传时再打开，或单独执行：

```powershell
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py --dry-run
D:\Program\Anaconda\python.exe E:\WorkSpace\ai_gateway\subtasks\walmart_image_prompt\05_upload_oss.py
```

## 实现建议

新增通用客户端：

```text
src/ai_gateway/clients/aliyun_oss_client.py
```

职责：

- 从环境变量或 `configs/local.env` 读取 OSS 配置。
- 初始化 `oss2.Bucket`。
- `upload_file(local_path, object_key, overwrite)`。
- `object_exists(object_key)`。
- `public_url(object_key)`。

新增阶段实现：

```text
src/ai_gateway/subtasks/oss_upload_images.py
```

职责：

- 读取当前批次图片 Excel。
- 根据业务配置构造本地文件路径和 OSS key。
- 读取 checkpoint，跳过已成功记录。
- 并发上传。
- 每张图上传后实时写 checkpoint。
- 最后合并写 JSONL 和 Excel。

依赖：

```text
oss2
openpyxl
```

如果环境中没有 `oss2`，启动时给出明确错误，不在代码里自动安装。
