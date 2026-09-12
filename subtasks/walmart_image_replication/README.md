# Walmart 图片复刻

该子任务与 `walmart_image_prompt` 同级且批次隔离。它不调用文本模型。主图和副图在同一任务表、同一生成阶段处理：

1. 主图任务使用本项目的 `prompts/main_image_optimization_prompt.txt`，只提交原主图一张参考图。
2. 副图任务把标题、五点、描述渲染进复刻模板，同时提交原主图和对应原副图两张参考图。

## 输入列

默认读取 `config.json` 指定的 Excel 和工作表，列名均可在 `input.columns` 修改：

- `SKU`
- `标题`
- `五点`
- `描述`
- `主图`
- `副图参考1` 至 `副图参考6`

主图为空时整个 SKU 不创建任务；某个副图为空时只跳过该位置。每个 SKU 创建 `new_main_{SKU}`，并按已有副图创建 `new_sub1_{SKU}` 至 `new_sub6_{SKU}`。

`image_generation.max_sub_images` 控制每个 SKU 最多复刻多少张副图，默认5。程序按副图参考列顺序选择前N个非空值：不足上限时全部复刻，超过上限时忽略排在后面的参考副图。主图不计入该上限。

`image_generation.generate_main_images` 和 `image_generation.generate_sub_images` 分别控制是否处理主图和副图。关闭某一类只停止该类图片的查询和新提交，不删除已有图片、task_id、checkpoint 或 OSS 结果。

`image_generation.max_regenerations_per_image` 控制单张图片明确失败后的重新生成上限。历史记录达到旧上限后，可以提高该值继续续跑；程序会比较历史 `attempts` 与当前上限，只补足新增的尝试次数。

## 运行

先在 `config.json` 设置输入 Excel，再确认 `configs/local.env` 中存在当前图片平台和 OSS 所需密钥。

```powershell
python subtasks/walmart_image_replication/00_replication_workflow.py --dry-run
python subtasks/walmart_image_replication/00_replication_workflow.py
```

`--dry-run` 会读取并校验源 Excel，显示主图/副图任务数量、双参考图样例，以及已有批次中的待提交和待查询数量；不会生成任务文件、调用 API、下载图片或上传 OSS。

只执行一轮：

```powershell
python subtasks/walmart_image_replication/00_replication_workflow.py --once
```

## 批次目录

批次名取输入 Excel 文件名，输出位于 `batches/{批次名}`：

- `01_build_replication_input`：已渲染提示词及双参考图任务（由 `01_build_replication_tasks.py` 生成）。
- `02_generate_images`：task_id、查询结果和下载图片（由 `02_generate_replication_images.py` 处理）。
- `03_upload_oss`：OSS 上传结果（由 `03_upload_replication_images.py` 处理）。
- `04_build_final_result`：最终图片表，副图会连续填充且不留中间空列（由 `04_build_replication_result.py` 生成）。
- `05_review`：主图和副图缩略图、标题、五点、描述及 OSS 链接审核表（由 `05_export_replication_review.py` 手动生成）。

审核预览与正式循环分离，图片生成及 OSS 上传完成后执行：

```bash
python subtasks/walmart_image_replication/05_export_replication_review.py
```

也可以明确指定历史批次：

```bash
python subtasks/walmart_image_replication/05_export_replication_review.py --batch develop_flow_260911_re
```

TUZI 使用 `/v1/videos` 异步提交与查询。新提交取得 task_id 后结束本轮；后续轮次查询并下载完成结果。已有成功图片不会重复生成。

复刻项目拥有独立的总配置、阶段配置、主图提示词、副图提示词和批次目录。修改 `walmart_image_prompt` 的业务文件不会改变本项目行为；两个项目只共享底层网关、图片客户端、断点续跑和 OSS 通用代码。
