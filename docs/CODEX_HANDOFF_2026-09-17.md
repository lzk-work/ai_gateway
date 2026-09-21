# Codex 阶段交接报告（2026-09-17）

## 1. 核查依据与 Git 状态

本报告依据当前工作区的 `git status --short`、`git diff`、关键模块和实际测试结果，不把聊天计划当作已实现功能。本次仅新增交接文档，未修改业务代码、配置或批次数据，未调用收费 API。

- 工作区：`E:/WorkSpace/ai_gateway`；分支：`master`。
- HEAD：`c3adaa0`（exprot_review 预览审核分段处理）。前序提交：`87d3efe`（图片复刻流程）、`e8d09b2`、`c840790`（文本平台切换相关）。
- 有未提交业务改动，不能 reset、覆盖、自动提交或把配置恢复为聊天中的旧值。
- 下述修改清单是相对 HEAD 的可核查差异；不代表所有配置差异都是 Codex 修改，用户有手动调整。
- 未发现工作区内的 AGENTS.md。

## 2. 当前执行基线与本阶段完成内容

技术基线是最新 `subtasks/walmart_image_prompt`，不是历史 `walmart_image_replace`。

主入口 `00_full_workflow.py` 每轮从 01 开始，依次生成提示词任务、调用文本模型、主图生成/查询、副图生成/查询、主图和副图 OSS 上传、最终结果组装。单阶段异常记录后继续后续阶段；`--once` 单轮；`--dry-run` 预览；轮间 Ctrl+C 友好退出。审核预览另有入口，不在上述阶段列表内。

当前代码已完成：

1. 图片下载及历史成功文件轻量校验，拒绝 HTML/JSON 假图片、明显截断数据；URL/Base64 使用 `.part` 后原子替换。
2. 本地成功判定同时检查状态、文件存在、大小和文件签名。SKU 已完成数量不再只按历史 success 字符串计数，统计成功数按目标封顶。
3. 明确失效输出的重新生成次数使用 `max_regenerations_per_image`，不再硬编码一次。
4. 主图/副图阶段分别明确设置启用标记，避免阶段范围混淆。
5. 03b 主图任务 Excel 已存在直接复用；删除该任务 Excel 后自动重建，不删除 04b checkpoint、task_id 或下载结果。
6. 提交、查询、下载及相应重试共用每次图片引擎 run 内的全局启动限速器；响应继续并发等待。间隔使用已有 `submit_delay_seconds`，不再各线程独立睡眠后同时提交。
7. 下载 429 仅停止该图片本轮尝试，不换备用 URL，不触发全局冷却；保留 task_id 为 pending，下一轮查询下载。其他图片继续处理。
8. 普通下载网络故障按下载重试配置尝试，耗尽后记 pending，打印“下载未完成”，不重新提交生图。明确图片失效仍走既有重新生成规则。
9. OSS 上传拒绝无效本地图片；历史上传跳过判断校验当前本地有效性及已记录大小，便于不同大小的重新生成图片重新上传。

## 3. 验证情况

本次实际执行：

`python -m pytest tests/test_image_request_limiter.py tests/test_walmart_configuration.py tests/test_image_providers.py -q`

结果：**59 passed，1 failed**。失败为 `ProviderTests.test_legacy_batch`，用无 provider 的 `{}` 历史 checkpoint 期待跨平台冲突，但当前 image_batch 只认明确 provider，未抛异常。此前同一失败已出现，不应声称全套通过。

前次排除此项的同组测试：**59 passed，1 deselected**。测试包括全局混合提交/查询/下载启动间隔、下载 429 一次即停止且其他图片可继续、HTML 假图片拒绝、真实 PNG Base64 保存、平台协议和配置集成等。配置集成测试为 17 项；此前 03b 脚本 py_compile 通过。

测试主要为本地单元/模拟测试；本次未进行生产批次运行、真实平台生图/下载、真实 OSS 或 Walmart Feed 验证。限速器时序测试为短间隔本地测试，非平台限额认证。

## 4. 实际修改文件与用途

| 相对项目根目录路径 | 当前改动目的 |
| --- | --- |
| `src/ai_gateway/clients/mxapi_image_client.py` | 图片字节/本地文件轻量校验，下载 `.part` 原子写入 |
| `src/ai_gateway/subtasks/mxapi_generate_images.py` | 成功统计及有效文件判断、失效重新生成上限、共享启动限速、下载 pending/429 分类 |
| `src/ai_gateway/subtasks/oss_upload_images.py` | 上传前图片校验；历史上传成功结合本地有效性和大小判断 |
| `subtasks/walmart_image_prompt/03b_generate_main_images.py` | 已有主图任务 Excel 复用，删除后重建 |
| `subtasks/walmart_image_prompt/workflow_common.py` | 主图/副图阶段启用范围明确化 |
| `subtasks/walmart_image_prompt/README.md` | Excel 重建、限速、下载 429 行为说明 |
| `tests/test_image_providers.py` | HTML 假图片测试、Base64 测试改用真实 PNG、重新生成上限测试适配 |
| `tests/test_image_request_limiter.py`（未跟踪） | 混合请求共享限速和单图片 429 行为测试 |
| `subtasks/walmart_image_prompt/config.json` | 本地当前源表、OSS develop 路径、重新生成上限、并发值变化；归属不能仅凭 diff 判断，按用户配置保留 |
| `subtasks/walmart_image_replication/config.json` | 本地输入改为 develop_flow_260914-replication.xlsx；按用户配置保留 |
| `temporary_patches/tuzi_download_mirror.py`（未跟踪） | 临时启动器；仅运行它时 monkey-patch：apioss5 下载 429 改试 apioss8，最多 5 次、间隔至少 3 秒。普通入口不引用它 |
| `scripts/output/tuzi_protocol_benchmark/tuzi_protocol_benchmark.xlsx`（未跟踪） | 遗留测试产物，不是运行所需代码；本次未分析表内结果 |
| `docs/CODEX_HANDOFF_2026-09-17.md` | 本次新增交接报告 |

`temporary_patches` 还含未跟踪 `__pycache__`。本次没有清理，不能视为正式已验证协议。

## 5. 已确定的接口、状态与配置

### 平台与接口

- 图片按整批绑定一个 provider，MXAPI 是整体切换备选，不做同批不同图自动平台降级。
- `clients/image_batch.py` 用批次 `image_provider.json` 及明确 provider 的图片生成记录识别平台；缺失 provider 不直接推断 MXAPI。
- TUZI 正式适配器是 `clients/image_providers.py::TuziImageAdapter`：POST `/v1/videos`，multipart：model、prompt、size、重复 input_reference（URL 或文件，多图顺序保留）；返回 id/task_id。
- 查询 GET `/v1/videos/{task_id}`；completed 从 `video_url` 取图片地址；queued/not_start/submitted/in_progress/expired 转 pending。不是 get-async，也不是 request_id 查询。
- 当前适配器不提交 quality/n/response_format 字段；不要因聊天示例假定已经提交。
- MXAPI 使用独立解析器和配置端点。公共文件仍含 mxapi 命名，不意味着只能调用 MXAPI。
- 文本使用 tuzi_text，图片使用 tuzi；两个 Key 独立。`configs/gateways.yaml`：TUZI_API_KEY 图片超时 300 秒；TUZI_TEXT_API_KEY 文本超时 120 秒；BUZZ_API_KEY（buzzai.cc）和 MXAPI_API_KEY 超时 300 秒；各 max_retries=2，公共含首次最多 3 次。
- 文本阶段当前 luna、stream=false、temperature=null、max_tokens=12000；候选 terra、gpt-5.4。不能把预检通过等同实际请求成功。

### 记录与状态

- 没有为本需求新增数据库、数据库表或事件总线。图片持久化为批次 JSONL checkpoint/results 和 Excel、本地图片。
- 图片记录主键为 SKU + image_name；主要字段：row_number、sku、image_name、image_type、image_number、status、task_id、reference_image、generated_image_url、downloaded_path、file_size、error_message、retryable、submit_latency_ms、poll_count、total_wait_seconds、attempts、created_at、provider。
- submitted：已取得 task_id；pending：查询/下载未确定，保留 task_id；success：本地文件有效；failed：失败记录；failed_permanent、failed_exhausted：停止条件；blocked：依赖条件；skipped：目标已满足等跳过；submission_unknown：提交意图未确认。
- submitted/pending 占用目标名额，避免未确定时继续候补过度提交；本地成功数不含已提交任务。历史 task_id 续跑查询，不以 429/查询 expired/连接波动判为任务生成失败。
- attempts 用于既有尝试/重新生成判断，不应仅看到字段名就推定它是所有 HTTP 请求次数。
- 主图与副图在 04b/04 分别保存记录。OSS 记录有 local_path、oss_key、oss_url、file_size 等，当前没有内容 hash 断点字段。

### 当前实际数值（不是建议值）

- prompt 总配置输入 develop_flow_260917-ge.xlsx；OSS 模板 develop/{sku}/{image_name}.png。
- 6 种副图候选，统一 desired_count=5；max_regenerations_per_image=6。
- max_records=3500（SKU 上限）；文本并发 10、图片 SKU 并发 5、OSS 并发 15。
- scheduler.enabled=true、interval_seconds=600、stop_when_complete=true、max_cycles=null；不是三小时。
- 主图/副图 submit_delay_seconds 均 0.5，当前含下载共享限速。
- 主图下载超时 120 秒、副图 60 秒；两者 max_download_retries=5（实际循环最多 5 次，非 5 次额外重试）。
- 每任务每轮 query_attempts_per_cycle=3、query_retry_delay_seconds=5；retry_delay 主图 10、副图 5 秒。
- max_wait_seconds=600、poll_interval 主图 8、副图 10 秒；deferred 模式查询已有任务用每轮 3 次逻辑，不能把 600 秒当成所有查询路径都持续等待。
- 主图固定提示词；副图读取有效 image_plan；主图与副图不强制互相依赖。审核预览每 Excel 最多 1000 SKU，两个项目已有相应实现。

## 6. 未完成、问题与风险

1. **新替换需求尚未实现，也未最终设计**：每 SKU 入参指定副图生成张数，可能 2/3/其他；用户接下来详细描述。当前 prompt 仍统一 desired_count=5，不具备该新业务的完整流程。
2. `walmart_image_replace` 是历史代码，只读取了总入口、动态入参构建、结果组装和配置等，未做完整可运行性认证。仍描述 BUZZ/MXAPI，默认 store_us 与配置 stores 的 store_rlx/store_nm 不一致；不能原样认为可用，更不能直接执行总入口（包括真实 Feed 写入）。
3. test_legacy_batch 与已实现平台识别语义不一致，待决定如何更新测试，不应为让测试通过擅自恢复旧推断。
4. 图片校验是签名/头尾轻量检查，不是 PIL 完整解码；不能保证所有内部损坏都识别。
5. OSS 上传跳过基于文件大小不是内容 hash；同大小不同内容、OSS key 模板变化的历史跳过需进一步检查。未实现 ETag/hash 对比。
6. 限速器只作用于单次 run 的同一客户端，不能协调多个进程/机器，也不覆盖文本/OSS；间隔 0.5 秒不代表符合平台限额。
7. 临时镜像脚本会在 429 后重试镜像，与正式“该图片留到下一轮”不同，只有显式运行它才启用；其来源、平台授权及真实效果本次未验证。
8. 下载成功前不会执行该位置之后的 save_raw_response；下载失败时不能假定原始成功查询结果已经完整保存。
9. save_image_result 支持 Base64，但当前 TUZI /v1/videos 解析只接受 completed+video_url；Base64 通用能力不是当前 TUZI 接口的 Base64 自动解析保证。Base64 校验 RuntimeError 的包装路径也需留意，未全面故障注入验证。
10. 未取得 task_id 的提交重试存在重复计费风险，代码已有 SubmissionUnknown 语义/警告，不能承诺绝无重复提交。
11. 复用任务 Excel 意味着源表/固定提示词变化不会自动反映；需删指定任务 Excel 重建，checkpoint 不会因此重置；不要误删 04/04b 数据。

## 7. 不能随意改变的约束

- 新替换任务以最新 walmart_image_prompt 为技术基线，历史 replace 只是待重构对象，不作为技术行为权威。
- 用户尚未详细描述替换规则，先接收需求，再确定设计，不提前沿用上一轮提出的架构方案。
- 不随意修改用户配置；修改配置前说明并取得确认；用户手动改动必须保留。
- 不动正在运行的数据，不擅自删 checkpoint/task_id，不把下载临时故障当重新生图理由。
- 单批次在一台机器执行；平台整体切换；文本与图片 Key 隔离。
- 生成与复刻均在使用，共享代码改动须评估两个流程；复刻模板尽量隔离，主图先、副图后。
- 任何 Walmart Feed 提交是外部写入，未得到新需求明确授权前不执行。
- 阶段结束不大范围修改，不自行清理未跟踪文件或提交 Git。

## 8. 下一阶段起点

第一步再次运行 git status/diff，确认这些未提交修改和用户当前配置是否发生变化；阅读本报告及 prompt 总入口、workflow_common、图片公共引擎、平台适配器、上传及最终结果组装的当前代码。然后等待/收集用户完整新需求，明确数量含义、主图规则、参考图、提示词生成方式、目标替换位置、旧图保留方式、SKU 不完整时处理和交付方式。此处是待确认事项，不是新架构方案。

对 replace 逐阶段做差距核查：历史入口/路径/配置/列映射、BUZZ/MXAPI 遗留绑定、平台鉴权、任务主键及断点、结果位置和 Feed；避免因为文件同名/有旧代码就直接复用。先做只读检查和 dry-run 安全性审核，不能直接跑真实总入口。

## 9. 下一次 Codex 启动提示词

你正在 E:/WorkSpace/ai_gateway 工作。请先完整阅读 docs/CODEX_HANDOFF_2026-09-17.md，并重新检查实际 git status、git diff 和当前代码，不要仅按聊天记录实现。下一阶段主要处理 walmart_image_replace，基本相当于重构：它是历史代码，可能不能运行；以最新 walmart_image_prompt 的平台调用、异步批量提交/分轮查询、下载限速及429单图延后、断点续跑、OSS和结果流程为技术基线。新业务是每个SKU由入参给出不同副图生成张数，用于图片替换；详细业务规则由我继续补充。先理解我的完整描述，再给出设计方案，得到实施要求后才修改。不要提前沿用历史replace的架构，也不要把当前统一desired_count=5当成新需求已经支持。保留全部未提交改动和用户手动配置，任何配置修改先说明并询问；不删历史任务数据，不执行付费测试或Walmart Feed提交，不大范围改代码。注意当前相关测试59通过1失败（legacy_batch），未跟踪temporary_patches镜像脚本只在显式启动时生效。先说明你核查到的当前状态及还需确认的业务规则。
