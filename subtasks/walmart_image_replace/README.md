# Walmart 副图替换

按[最终设计文档](../../docs/walmart_image_replace_design.md)执行：保留原主图，仅补齐新副图并输出结果。本版不更新 Walmart 商品、不移动或删除旧图片。

## 输入与图片规则

每行一个店铺下的结果 SKU。来源 SKU、结果 SKU、店铺及已有主图链接必填；需补副图时提供标题、五点和沃尔玛参考主图。参考副图及已有副图均一列一张，可增加数字后缀列；GTIN、商品类型可选，已有值原样输出；API项目提交前查询补齐或核验。SKU/GTIN 用文本填写以保留前导零。

- 已有主图链接为有效图片对象 URL，允许 OSS 或沃尔玛 URL；原样保留，不按名称识别新旧，不生成、不上传、不替换、不归档。
- 参考主副图为沃尔玛 URL，作为副图模型素材，不计入已有图集。
- 已有副图为目标 OSS URL，按解码后的文件名包含 new_sub 判断新图；副图列含 new_main 或混合标记时阻断。
- 已有新副图全部保留，不足 4 张补齐，超过 4 张不截断。旧副图只列待归档。
- 已有副图按对象键去重，忽略查询参数，保留首次出现的原链接及数字列序。允许跨历史 SKU 目录和文件名复用。
- 同来源 SKU 多个结果 SKU 逐行独立处理，可共用已有图；同店铺结果 SKU 重复行阻断。
- 新副图使用来源 SKU＋UTC 毫秒时间戳＋随机标识，计划创建时固定，续跑不改名。
- 从已有 OSS 链接推导历史 SKU 之前的基座，拼接本次来源 SKU 目录。需补图但基座不唯一或无法推导时阻断；已达标行不要求上传目录、文案或参考图。

## 配置与运行

在项目根目录运行。总配置为本目录 config.json；输入以 input.excel_path 的实际值为准。模板工具默认创建 input/replace_input.xlsx，拒绝覆盖现有文件。

当前测试表为 input/image_replace_jiushi-test.xlsx，当前测试批次为 image_replace_jiushi-test。修改输入或处理范围会触发 input_changed；临时平台失败不用改输入或新建批次。

```powershell
# 仅需要新模板时运行
python subtasks/walmart_image_replace/tools/make_sample_input.py

# 当前测试表预演：只分析，不调用外部接口或写文件
python subtasks/walmart_image_replace/00_replace_workflow.py --dry-run --batch-name image_replace_jiushi-test

# 同一批次单轮续跑
python subtasks/walmart_image_replace/00_replace_workflow.py --once --batch-name image_replace_jiushi-test

# 同一批次周期续跑
python subtasks/walmart_image_replace/00_replace_workflow.py --batch-name image_replace_jiushi-test
```

正式运行会调用模型、下载和上传 OSS。批次名未指定时取输入文件名；续跑已启动批次必须使用原批次名，允许在 Excel 末尾追加新行，或提高 max_records 纳入末尾新任务；已有行内容、行号和顺序必须不变，不能删除、插入或缩小处理范围。旧任务和检查点复用，只为新增行创建计划。不要删除计划、checkpoint 或任务 ID，不同时启动同一批次的多个进程。

scheduler 配置当前为每 600 秒续跑，全部图集准备完成后停止；Ctrl+C 可在轮间等待时暂停。临时文字失败下一轮重试；成功提示词复用，图片 submitted/pending 查询原 task_id，下载 429 单图延后。输入阻断、明确源数据错误和永久失败保留状态，需人工处理，不会自动清空。

主图生成/上传开关保持关闭。Walmart提交/对账入口、Feed客户端及鉴权配置已移除，线上更新只在API项目执行。

## 限速

文字并发由总配置 execution.concurrency 管理，启动间隔由 stages/generate_prompts/config.json 的 limits.request_start_interval_seconds 管理，允许的请求重试等待使用 retry.retry_delay_seconds。

文字启动间隔不是平台配额保证，当前没有所有线程统一 429 冷却，也不协调其他进程；平台还可能按 token 限流。图片提交、查询、下载和重试共享单次图片引擎 run 内的启动间隔；图片和 OSS 并发分别配置。参数以文件当前值为准。

## 单阶段入口

每个有效阶段执行后同步更新结果，可使用 --batch-name 和 --dry-run。

| 入口 | 功能 |
| --- | --- |
| 01_replace_inventory.py | 输入分析及计划 |
| 02_replace_generate_prompts.py | 副图提示词 |
| 03_replace_generate_sub_images.py | 副图提交、查询、下载 |
| 04_replace_upload_sub_oss.py | 副图上传 OSS |
| 05_replace_build_result.py | 图集及图片清单 |
| 08_replace_build_report.py | 三份报告 |
| 09_replace_export_review.py | 独立人工审核预览 |

业务模块为 replace_workflow_common.py。03b_replace_generate_main_images.py、04b_replace_upload_main_oss.py 是禁用的主图入口。

## 输出与追踪

输出目录为 batches/<批次名>/08_reports/，每份含 XLSX 和 JSONL，保留所有商品行：

| 文件名 | URL 内容 |
| --- | --- |
| 最新使用图片URL | 保留原主图＋已有新副图＋本批次成功上传新副图 |
| 本批次新生成图片URL | 整个批次累计成功上传的新副图，主图列空 |
| 待归档旧副图URL | 输入旧 OSS 副图，仅候选，主图列空 |

主图独立一列，副图动态多列，记录来源/结果 SKU、店铺、完整状态、失败原因和计数。提示词 403/429、校验失败及未就绪图片错误会显示在对应商品报告；提示词后续成功或恢复后不再显示旧错误。

05_result/image_set.jsonl 保存当前图集结果。将最新使用图片URL.xlsx交给 E:/WorkSpace/walmart_api 项目，由其匹配店铺ID并核验GTIN及商品类型，只更新副图；主图URL仅用于表示图集和审计。当前项目不输出或维护平台提交状态。complete=true 仅表示原主图和至少 4 张新副图准备完成，不表示 Walmart 已更新。归档候选不表示可以删除，共用图片还需检查其他商品使用关系。

05_result/image_manifest.jsonl 记录图片归属、目录、角色、文件名、URL、对象键、任务及状态。已有图含 input_column/input_order，新图含 ordinal/plan_created_at；generation_recorded_at、upload_recorded_at 是原始记录时间，不是服务端实际完成时间。历史缺失时间留空；指纹一致时仅为派生清单补输入列，不回写旧计划。

## 上传与历史兼容

上传使用完整对象键，客户端默认前缀为空。唯一名称避开历史图片；不检查对象存在性或 bucket 版本控制，不发送禁止覆盖请求头。有成功上传 checkpoint 时跳过；上传成功而记录保存前中断时，允许同一对象键重复上传。已上传图片不会因本地文件丢失而重新生成。

计划布局版本为 3。不兼容的旧批次应使用新批次名，不自动迁移或删除历史数据。当前兼容批次继续原名。临时镜像补丁不参与流程。

## 验证状态

2026-09-18 最近代码验证：全套离线测试 126 项通过。真实测试已执行模型调用和下载，用户已确认 OSS 上传成功；实际整批三份输出尚待完整核对，Walmart 更新和实际归档未执行。

```powershell
python -m pytest tests -q -p no:cacheprovider
```

结果文件使用以上中文名称，分别输出.xlsx与.jsonl。历史英文报告保留，重新组装报告时生成中文文件；计划、checkpoint、批次版本和任务ID不变。


## 两项目边界

ai_gateway仅负责图片分类、生成、下载、OSS上传和最终结果。walmart_api负责读取最新使用图片URL.xlsx、店铺ID及凭据、补齐/核验商品参数、线上副图更新与结果查询；不提交主图。历史英文报告、replace_payload及任务记录保留，新组装结果使用image_set.jsonl。


## 人工审核预览

导出已启动批次的产品和文案信息，并嵌入两组对比图：蓝色为沃尔玛参考图，绿色为最新使用图（保留原主图＋最终副图）。每组区分主副图，各商品两行，缩略图在上、可点击原图URL在下。左侧包含来源/结果SKU、店铺、GTIN、可选商品类型、标题、五点、完整状态、失败原因及人工审核结论/意见。

```powershell
python subtasks/walmart_image_replace/09_replace_export_review.py --batch-name image_replace_jiushi-test
```

默认输出09_review/人工审核预览.xlsx；超过1000个商品按编号分卷。未完成行仍保留，图片加载失败明确标注，不自动替换图片。新增图优先复用本地文件；参考和已有图使用有限并发下载，默认8路，并只在本次导出进程的内存中复用，不保存缩略图缓存。不会调用生成、上传或Walmart API。

```powershell
# 预演：不下载或写文件
python subtasks/walmart_image_replace/09_replace_export_review.py --batch-name image_replace_jiushi-test --dry-run

# 只用本地生成图片，不下载远程图片
python subtasks/walmart_image_replace/09_replace_export_review.py --batch-name image_replace_jiushi-test --offline --output 人工审核预览_离线.xlsx
```

结论默认待审核，人工选择通过/退回并填写意见。导出不表示审核通过；审核确认后交接最新使用图片URL.xlsx，人工审核预览不是API项目输入。已有文件默认禁止覆盖，可指定新路径；只有确定丢弃旧审核意见时才使用--overwrite。缩略图默认240px，可用--thumbnail-size调整；下载并发可用--preview-concurrency调整；分卷上限可用--max-skus-per-file调整。
本次新生成图片在 OSS 上传阶段按总配置 `oss.image_output` 转为高质量 JPEG；上传成功并更新生成断点后删除本地源 PNG、保留 JPG。透明图片保持 PNG，历史 OSS 图片不迁移。
