# 沃尔玛图片替换业务任务 · 初版设计文档

> 状态：**初版 / 待评审**。本文件只定义需求拆解、入参、配置、流程、断点续跑与原子性设计，未含实现代码。
> 关联项目：`E:\WorkSpace\ai_gateway`
> 设计依据：
> - `docs/system_design.md`（统一调用框架、错误分层、重试、并发）
> - `docs/architecture.md`（业务任务与代码模块分层）
> - `docs/oss_upload_design.md` / `docs/mxapi_image_generation_design.md`（既有 OSS / MXAPI 阶段）
> - `subtasks/walmart_image_prompt/`（既有 Walmart 图片生成业务，本任务在其上做「替换」扩展）

---

## 1. 需求概述

输入每条任务给出四要素：**平台 SKU、OSS 图片路径、所属店铺、文案信息**。

目标：为指定 SKU 补足副图（副图不足目标数量时，用 AI 生成缺失数量的副图），并把「原有图片 + 新生成副图」组成完整图片集，通过**沃尔玛店铺后台 API** 提交图片替换。

目标数量（副图总数）默认 6，与既有 `walmart_image_prompt` 的 `image_plan` 一致，可配置。

### 1.1 端到端流程（用户描述）

1. 根据 **OSS 图片路径** 查询已有图片，按文件名判断已有副图位置与数量，算出**需要补足的图片数量**。
2. 根据 **文案信息 + 原图**，调用 **BUZZ** 生成图片提示词（数量 = 需补足数量）。
3. 根据图片提示词，调用 **MXAPI** 生成对应数量图片并下载。
4. 新图片上传到 **OSS 指定路径**（按位置命名）。
5. 结合原有图片数量与新生成副图，产出**替换结果**（最终有序图片集）。
6. 根据 **沃尔玛店铺后台 API**，提交图片替换。

---

## 2. 入参设计

### 2.1 单条任务输入（建议 Excel，沿用项目惯例）

> 以下为**真实入参表头**（2026-08-20 用户定稿）。表头为中文列名，内部字段名用于代码与 jsonl 流水线。

| 表头列名 | 内部字段 | 必填 | 说明 |
|----------|----------|------|------|
| 平台SKU | `platform_sku` | 是 | 沃尔玛 feed `Orderable.sku`（锁定商品）+ 批次命名关联键 |
| GTIN | `gtin` | 是 | `Orderable.productIdentifiers.productId`；维护 feed 必须 SKU + GTIN 同时带，缺一不可。**`productIdType` 固定为 `GTIN`（全部商品均为 GTIN，不单列类型列）** |
| 店铺 | `store` | 是 | 决定沃尔玛 API 凭证/端点；也是提交分组键 `(store, mode)` |
| OSS路径 | `oss_image_path` | 是 | 你方阿里云 OSS 暂存目录，用于列举已有副图（非沃尔玛托管路径，见 §11） |
| 开发SKU | `dev_sku` | 是 | OSS 目录/已有图片实际命名所用 SKU（可能与平台SKU 不同），阶段 01 查图定位用 |
| 主图链接 | `main_image_url` | 是 | 图片提示词多模态"原图"之一；因部分商品图未存入 OSS，需显式给定主图链接，避免阶段 01 查不到 |
| 标题 | `title` | 是 | 图片提示词入参（替代原 `copywriting_info` 自由文本，改为结构化） |
| 五点 | `bullets` | 是 | 图片提示词入参。**单个单元格**：五条卖点合并在同一单元格内（换行分隔） |

> **「原图」来源**：阶段 02 的多模态提示词入参 = `主图链接`(显式给定) + 阶段 01 查得的「已有副图」+ `标题` + `五点`（单单元格）。
>
> **`开发SKU` 与 `OSS路径` 的关系**（2026-08-20 已确认）：`OSS路径` 列只是前缀，真正的图片目录 = `{OSS路径}/{开发SKU}/`。阶段 01 按该目录探测已有对象。
>
> **已有图探测实现（2026-08-20 已落地）**：位置有界（1..max_sub_images），无需列举目录——对公共读 OSS 公网 URL（`https://{bucket}.{endpoint}/{prefix}/...`，基座由 `workflow_common.oss_public_base()` 从 local.env 的 `ALIYUN_OSS_*` 拼出）并发发 **GET + `Range: bytes=0-0`** 逐位置探测，200=存在 / 404·403=不存在。**不用 HEAD**（本机代理环境实测 HEAD 会被拒）。无 OSS 配置或 `--mock` 时回退 md5 确定性模拟，inventory 记录 `existing_source` 标明来源（`oss`/`mock`）。
>
> **新附图命名与计数规则（2026-08-20 定稿）**：OSS 已有新附图对象路径为 `{OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png`（位置从 1 开始，文件名后缀为开发SKU）。阶段 01 逐位置探测该路径的对象是否存在，得到已有张数 `E`。**副图张数下限 `min_sub_images=4`、上限 `max_sub_images=6`**（配置项，见 §3.3）：
> - `E < 4`：生成 `4 - E` 张补缺，最终上传 4 张；
> - `4 ≤ E ≤ 6`：不生成，原样上传 `E` 张；
> - `E > 6`：不生成，上传 6 张（封顶，丢弃多余高序号图）。
>
> 即 `target_upload = min(max_sub_images, max(E, min_sub_images))`；需生成位置 = `1..target_upload` 中 OSS 上不存在者。**主图（来自「主图链接」列）不计入此 4~6 张计数**，单独作为 `mainImageUrl`。
>
> **图片生成提示词 / 生成方式与 `walmart_image_prompt` 一致**（2026-08-20 已落地）：03/04 阶段直接复用共享模块 `src/ai_gateway/subtasks/mxapi_generate_images.py`（含行级 checkpoint 续跑、task_id 落盘）与 `src/ai_gateway/subtasks/oss_upload_images.py`（行级 checkpoint、幂等上传）。02 输出 `model_results.jsonl + full_outputs/`（与 `walmart_image_prompt` 02 同构）供共享模块消费。**图片行数动态确定**：不按固定张数全量展开，而按阶段 01 的「缺失位置」逐位置一行。**图片流水线主键 = `OSS路径/开发SKU`**（图片入参 SKU 列，同一图片目录去重生成一次；04 上传 `key_template={sku}/{image_name}.png` 渲染出的对象路径与已有图同目录）。02 仍为 mock BUZZ（占位提示词），03/04 支持 `--mock` 离线验证（不调 MXAPI/OSS，按行级格式模拟成功）。
>
> **`replace_mode` 已移出本表，放入业务总配置 `config.json` 的 `replace` 段**（见 §3.3，默认 `fill`→`PARTIAL_UPDATE`）。

### 2.2 每条任务运行期派生数据

- **主图**：直接来自入参 `主图链接` 列，作为沃尔玛 feed 的 `mainImageUrl`（独立、不进入副图数组）。
- 已有副图清单：位置 1..N → OSS object key / URL（`{oss_image_path}/{dev_sku}/new_sub{position}_{dev_sku}.png`）
- 缺失位置列表：如 `[3, 5, 6]`（目标 6，已有 1/2/4）
- 需生成数量：`len(缺失位置)`（或 `target_upload`，当 `replace_mode=full`）
- 最终副图集（`productSecondaryImageURL[]`）：位置 1..N 的有序列表，每个位置 = 已有 OSS URL 或新图 OSS URL（**不含主图**）

---

## 3. 配置信息设计

配置分三层，沿用既有约定：**全局基础配置** + **业务总配置** + **各阶段 config.json**。

### 3.1 全局基础配置（`configs/`，复用既有）

- `configs/gateways.yaml`：BUZZ 中转站（已存在，复用）
- `configs/models.yaml`：文本模型（已存在，复用）
- `configs/local.env`：BUZZ Key、阿里云 OSS 凭证（已存在，复用）

### 3.2 沃尔玛 Marketplace API 鉴权配置

沃尔玛 Marketplace API 使用 **Client ID + Client Secret** 换取 OAuth Token（`POST /api/v3/token`, `grant_type=client_credentials`），再用 Bearer Token 调 Feed API。每个店铺主体（如 润林轩、娜美）有独立凭证，互不混用——这也是 06 提交按 `(store, mode)` 分组的原因。

**密钥注入方式**：与 BUZZ Key、阿里云 OSS 凭证一致，放 `configs/local.env`（已 `.gitignore`），通过环境变量名映射：

```
# configs/local.env 中添加
WALMART_STORE_RLX_CLIENT_ID=你的_润林轩_店铺_client_id
WALMART_STORE_RLX_CLIENT_SECRET=你的_润林轩_店铺_client_secret

WALMART_STORE_NM_CLIENT_ID=你的_娜美_店铺_client_id
WALMART_STORE_NM_CLIENT_SECRET=你的_娜美_店铺_client_secret
```

`config.json` 中每个 store 用 `api_key_env` / `secret_env` 映射到环境变量名（见 §3.3）。

`workflow_common.py` 提供 `walmart_store_credentials(store_key)` 函数，按 store 从 `configs/local.env` 加载凭证，返回 `{"client_id", "client_secret"}`。06 提交和 07 对账的预检逻辑会检查凭证是否齐全，缺失则跳过该 SKU。

**店铺匹配**：入参 Excel「店铺」列可填 store key（`store_rlx`）或 `business_unit` 可读名（`润林轩-沃尔玛`），阶段 01 通过 `resolve_store_key()` 自动归一为 store key（先按 key 精确匹配，再按 business_unit 反查）。

### 3.3 业务总配置（`subtasks/walmart_image_replace/config.json`）

任务级配置只保留**任务级关注点**（入参、执行上限、店铺、阶段开关）；**阶段参数在 `stages/<stage>/config.json`**（见 §3.4），与 `walmart_image_prompt` 惯例一致：

```json
{
  "name": "walmart_image_replace",
  "input": {
    "excel_path": "E:/WorkSpace/ai_gateway/subtasks/walmart_image_replace/input/sample_replace.xlsx",
    "sheet_name": "Sheet1"
  },
  "execution": {
    "max_records": 1000,
    "concurrency": 5
  },
  "walmart_api": {
    "default_store": "store_rlx",
    "token_endpoint": "/api/v3/token",
    "token_grant_type": "client_credentials",
    "token_cache_seconds": 900,
    "stores": {
      "store_rlx": {
        "business_unit": "润林轩-沃尔玛",
        "base_url": "https://marketplace.walmartapis.com",
        "api_key_env": "WALMART_STORE_RLX_CLIENT_ID",
        "secret_env": "WALMART_STORE_RLX_CLIENT_SECRET"
      },
      "store_nm": {
        "business_unit": "娜美-沃尔玛",
        "base_url": "https://marketplace.walmartapis.com",
        "api_key_env": "WALMART_STORE_NM_CLIENT_ID",
        "secret_env": "WALMART_STORE_NM_CLIENT_SECRET"
      }
    }
  },
  "workflow": {
    "query_existing_images": true,
    "generate_prompts": true,
    "generate_images": true,
    "upload_oss": true,
    "build_replace_result": true,
    "submit_replace": false,
    "reconcile": false,
    "build_report": true
  }
}
```

要点：
- `walmart_api.token_endpoint` / `token_grant_type` / `token_cache_seconds`：OAuth Token 获取参数，所有店铺共用同一 endpoint（`/api/v3/token`），但用各店的 client_id/client_secret 换取独立 token。
- `walmart_api.stores.<store>.{api_key_env, secret_env}`：映射到 `configs/local.env` 中的环境变量名（见 §3.2）。06/07 通过 `workflow_common.walmart_store_credentials(store)` 加载。
- `workflow.submit_replace` **默认 `false`**：替换提交是有外部副作用的不可逆动作，必须由人显式开启，或运行 `06` 时显式加 `--confirm`。
- `workflow.reconcile` **默认 `false`**：对账为独立定时任务，按需开启。
- `walmart_api.stores`：店铺 → businessUnit/base_url 映射，是 06 提交分组与 07 对账路由的依据（凭证待接入时从 `configs/local.env` 注入）。
- 阶段参数（min/max 副图数、OSS key 模板、命名模板、process_mode/batch_size 等）**已全部迁入 §3.4 的各阶段配置**，任务级不再重复。

### 3.4 各阶段 `stages/<stage>/config.json`

沿用既有约定（对齐 `walmart_image_prompt`），每个阶段一个目录，含 `config.json` + `README.md`；阶段配置只写本阶段关心的：输入、输出、执行类型（本地变换/模型调用/图片生成/OSS 上传/feed 提交）、命名模板、校验规则、重试与续跑。处理数量统一由业务总配置 `execution.max_records` 控制。

| 阶段配置 | 关键内容 | 被入口脚本读取的参数 |
|----------|----------|---------------------|
| `stages/query_existing_images/` | 表头映射（五点=单列）、命名正则、计数下限/上限 | `naming.existing_name_pattern`、`limits.min/max_sub_images` |
| `stages/generate_prompts/` | BUZZ 网关/模型（已接真实 `buzzai.cc`，gpt-5.4）、提示词模板路径 `prompts/walmart_image_replace_template.txt`（含 `{{产品标题}}`/`{{产品五点}}` 占位符，经 `template_renderer` 渲染）、校验 | `prompt_template_path`、`prompt_placeholders` |
| `stages/generate_images/` | **共享模块 schema**（MXAPI 网关/模型、列映射、轮询/重试/续跑）+ 命名模板 | `naming.image_name_template`（03-1 用）；其余由共享 `load_config` 读取 |
| `stages/upload_oss/` | **共享模块 schema**（OSS key 模板、并发、幂等续跑） | `oss.key_template`（`{sku}/{image_name}.png`，`{sku}`=OSS路径；共享模块传 stem 所以模板自带 `.png`） |
| `stages/build_replace_result/` | 组装规则（主图独立）、完整性校验 | 真实实现接入时读取 |
| `stages/submit_replace/` | feed 端点、分组参数、预检规则、门控 | `replace.process_mode`、`replace.batch_size`、`replace.gtin_type` |
| `stages/reconcile/` | 对账端点、状态机、范围 | 真实实现接入时读取 |
| `stages/build_report/` | 报告列、状态优先级 | 真实实现接入时读取 |

另有 `scripts/` 辅助脚本（与 `walmart_image_prompt` 惯例一致）：
- `scripts/execution_confirmation.py`：提交前执行确认视图（批次产物状态、06 预检、feed 分组计划），只读。
- `scripts/statistics/batch_stats.py`：批次各阶段进度统计（各 jsonl 条数与状态分布）。

---

## 4. 流程设计

### 4.1 阶段拆分

| 阶段 | 脚本 | 输入 | 输出 | 外部副作用 |
|------|------|------|------|-----------|
| 01 query_existing_images | `01_query_existing_images.py` | Excel + OSS | `image_inventory.jsonl` | 只读 OSS 列举 |
| 02 generate_prompts | `02_generate_prompts.py` | inventory + 文案 + 原图 | `model_results.jsonl` + `full_outputs/` | 调 BUZZ |
| 03 generate_images | `03_generate_images.py`（03-1 `scripts/build_image_input.py` 动态展开入参；03-2 复用共享 `mxapi_generate_images`） | image_input.xlsx + model_results | `image_generation_results.jsonl` + `downloaded_images/` + checkpoint | 调 MXAPI + 下载 |
| 04 upload_oss | `04_upload_oss.py`（复用共享 `oss_upload_images`） | image_results 行级记录 | `oss_upload_results.jsonl` + checkpoint（行级） | 写 OSS |
| 05 build_replace_result | `05_build_replace_result.py` | inventory + oss 结果 | `replace_payload.jsonl` / xlsx | 无（仅组装） |
| 06 submit_replace | `06_submit_replace.py` | replace_payload | `submit_results.jsonl` | **调沃尔玛后台 API** |
| 07 reconcile | `07_reconcile.py` | submit_results | `reconcile_results.jsonl`（回写 submit_results） | **调沃尔玛 Feed 状态 API** |
| 08 build_report | `08_build_report.py` | payload + submit + reconcile | `result_report.jsonl` / `.xlsx` | 无（仅派生） |

总流程 `00_full_workflow.py` 串联，按 `workflow` 开关决定执行哪些阶段。

### 4.2 流程图（mermaid）

```mermaid
flowchart TD
  A[Excel 入参] --> B[01 查已有图片]
  B --> C[算缺失位置/需生成数]
  C --> D[02 BUZZ 生成提示词]
  D --> E[03 MXAPI 生成并下载图片]
  E --> F[04 上传 OSS 指定路径]
  F --> G[05 组装替换结果 payload]
  G --> H{06 提交替换?}
  H -- workflow.submit_replace=false / 无 --confirm --> I[停止, 输出待提交报告]
  H -- 显式开启 --> J[06 调沃尔玛后台 API 提交]
  J --> K[07 定时对账 FeedStatus]
  K --> L{对账结果}
  L -- success --> M[标记成功, 闭环]
  L -- failed --> N[feed_id 置 null, 回流重提]
  N --> J
  G --> O[08 生成结果报告]
  M --> O
```

### 4.3 各阶段关键逻辑

- **01 查已有图片**：对公共读 OSS 公网 URL 并发发 GET + Range 逐位置探测 `oss_image_path/{dev_sku}/new_sub{位置}_{dev_sku}.png`（位置 1..max，有界无需列举；见 §2.1 探测实现）；统计已有位置集合；按 `min_sub_images`/`max_sub_images` 算出缺失位置 / 需生成数量。输出每条 SKU 的 `image_inventory` 记录（含已有清单、缺失列表、需生成数、`existing_source`）。
- **02 生成提示词**：按 `OSS路径/开发SKU`（图片目录）去重，把 `标题` + `五点`（单单元格）+ `主图链接` + 已有副图组装多模态 prompt，调 BUZZ；产出 `需生成数` 条提示词。输出与 `walmart_image_prompt` 的 02 同构（`model_results.jsonl` + `full_outputs/<sku>.json`，sku = OSS路径/开发SKU，`image_plan[].image_number` = 缺失位置），供共享模块 `load_prompt_map` 直接消费。
- **03 生成图片**：03-1 `scripts/build_image_input.py` 按「缺失位置」**动态展开**图片入参 Excel（行数 = 各目录缺失位置数，SKU 列 = OSS路径/开发SKU）；03-2 复用 `src/ai_gateway/subtasks/mxapi_generate_images.py`（行级 checkpoint 续跑、提交即落盘 `task_id`、轮询超时保留 task_id、永久失败不重提）。每个缺失位置一张图，按 `new_sub{position}_{dev_sku}` 命名（不含扩展名，下载自动补 `.png`）。
- **04 上传 OSS**：复用 `src/ai_gateway/subtasks/oss_upload_images.py`（内部用 `aliyun_oss_client`），按 `oss.key_template`（`{sku}/{image_name}.png`，`{sku}` = OSS路径/开发SKU、`{image_name}` 不含扩展名所以模板自带 `.png`）行级并发上传 + checkpoint 幂等续跑；渲染出的对象路径 `{OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png` 与已有新附图同目录。同一 SKU 的副图整体成功/整体不提交（见第 7 节）。
- **05 组装替换结果**：合并原图 URL（已有位置，按 `existing_positions` 精确映射，相对 oss_key 经 `oss_public_base()` 拼成完整公网 URL）+ 新图 OSS URL（按 `(OSS路径/开发SKU, new_sub{p}_{dev_sku})` 查行级上传记录），产出有序 `replace_payload`：主图取自「主图链接」列（独立、不进副图数组），副图为 `new_sub1..sub_N` 的有序列表。校验缺失位置数 = 0 且主图非空则标记 `complete=true`。
- **06 提交替换**：见第 7 节门控设计。按 `(store, processMode)` 分组、按 `batch_size` 切 feed；提交成功即回写 `feed_id` + `replace_status=submitted`。续跑跳过已 `submitted`/`success` 的 SKU。
- **07 对账**：独立定时运行，对 `replace_status=submitted` 的 SKU 按 store 分别调沃尔玛 `FeedStatus`/`FeedItemStatus`/`GetFeedErrorReportAPI`。成功 → `replace_status=success`；失败 → `replace_status=failed` 且 `feed_id` 置回 null（回流重提）。对账结果快照写 `reconcile_results.jsonl`，状态回写 `submit_results.jsonl`。
- **08 生成报告**：由 05 payload + 06 submit + 07 reconcile 派生，每次重跑重新生成（覆盖写）。输出列：店铺 | 平台SKU | GTIN | 上传的图片链接 | 是否成功 | 失败原因。同时输出 `.jsonl` 和 `.xlsx`。

---

## 5. 断点续跑设计

沿用项目既有机制，每个阶段独立写 checkpoint，重跑跳过 `success` 记录：

- **01**：OSS 列举是只读幂等，重跑直接重新列举，无需 checkpoint（或缓存 inventory 加速）。
- **02**：复用既有 `model_results.jsonl` 轻量索引 + `skip_success`，已 `success+passed` 的 SKU 跳过。
- **03**：复用 MXAPI checkpoint（`image_generation_checkpoint.jsonl`），`submitted`/`task_id` 中断后复用原任务，不重复扣费；失败重提新 `task_id`。
- **04**：OSS 上传按 object key 幂等，已 `success` 的 key 跳过（同 key 覆盖无害）。
- **05**：纯组装，依赖前序 checkpoint 是否齐全，无需独立 checkpoint。
- **06**：批量提交，续跑规则见 §7.4——按 `(store, processMode)` 分组、按 `batch_size` 切 feed；提交成功即把 `batch_no` + `feed_id` 回写该 feed 内每条 SKU 记录。**以 `feed_id` 非空为已完成标志**：每次启动只处理 `feed_id == null` 且符合要求的 SKU，已回写 `feed_id` 者跳过，不重复提交、不重复扣费。

`max_records` 统一按**源数据行数（SKU 数）**计数，各阶段在此基础上展开，与既有 `walmart_image_prompt` 一致。

---

## 6. 结果校验设计

- **02 提示词校验**：返回是否合法 JSON、提示词条数是否 = 需生成数（与既有 `image_plan=6` 校验同思路，改为「条数 = 需生成数」）。
- **03 图片校验**：下载文件大小 > 0、图片格式可解析、数量 = 需生成数。
- **04 上传校验**：OSS 回执 status=success、可二次 HEAD 校验 object 存在。
- **05 完整性门控（关键）**：组装替换结果时，校验「最终图片集缺失位置数 = 0」；任一位置缺图则标记该 SKU **不可提交**，整体阻断 06。

---

## 7. 原子性与「替换提交必须最后执行」设计（重点）

### 7.1 原则

> **替换提交（阶段 06）是唯一有不可逆外部副作用的动作。它必须放在所有准备阶段之后，且必须在「信息完整」校验通过后才执行。**

阶段 01–05 都是「准备」：OSS 列举（只读）、BUZZ 调用、MXAPI 生成、OSS 上传（按 key 幂等、可逆）、结果组装（无副作用）。阶段 06 是「执行」。

### 7.2 门控规则

1. **默认不执行**：`workflow.submit_replace=false`；或运行 `06_submit_replace.py` 必须带 `--confirm`（且非 `--dry-run`）。
2. **提交前预检（pre-flight）**，任一不满足则中止并打印待处理报告，绝不提交：
   - 所有 SKU 的 05 阶段 `replace_payload` 已生成；
   - 每个 SKU 最终图片集「缺失位置数 = 0」；
   - 每个最终图片 URL 都来自成功上传的 OSS 回执（URL 可信）；
   - 每个 SKU 的 `store` 在 `walmart_api` 配置中存在且凭证已注入。
3. **批量提交也按 SKU 粒度控制**：单条 SKU 不满足预检 → 该条跳过、不影响其他 SKU；整体统计「可提交 / 跳过 / 失败」。
4. **`--dry-run` 行为**：只做预检 + 打印将要提交的 payload 概要（SKU、店铺、图片数、首条 URL 样例），**不调用沃尔玛 API、不写提交结果**。
5. **提交结果可追溯**：`submit_results.jsonl` 记录每条 SKU 的提交状态、请求 ID、响应摘要、错误，供回归与对账。

### 7.3 为什么「最后完成」

- 避免「图还没生成完 / 上传失败」就先告诉沃尔玛后台「替换了」，导致线上商品图缺失或错乱。
- 避免中途失败留下半成品：只要 06 没跑，所有产物都在 OSS（可逆），可反复重跑直到完整再提交。
- 与既有 `workflow.generate_and_download_images=false`（默认防误耗 MXAPI 额度）同思路：**有外部代价/不可逆的动作默认关，显式开**。

### 7.4 批量请求的分组与续跑（针对多 SKU 场景）

本业务天然是批量（每个 SKU 都需替换），而沃尔玛 `MP_MAINTENANCE` feed 的结构带来三个硬约束：

- **C1 — `processMode` 是 feed 头字段**：同一 feed 内所有 `MPItem` 共用一个 `processMode`（`REPLACE_ALL` / `PARTIAL_UPDATE`）。→ 一个提交批次内的 SKU 必须同 mode。
- **C2 — 凭证是 feed 级 auth**：提交用的 API 凭证（header）由 `store` 决定，不同 `store` 用不同凭证。→ **不同 store 的 SKU 不能混在同一 feed**。
- **C3 — item 粒度成败**：feed 异步处理，一个 feed 内不同 `MPItem`(SKU) 可独立成功/失败。→ 提交结果必须 **按 item(SKU) 粒度**追踪，不能整批一刀切。

**A. 请求格式**：直接以 **JSON** 提交（对齐附录 A.2）—— 一个 feed 的 `MPItem[]` 数组承载多个 SKU，`POST /v3/feeds?feedType=MP_MAINTENANCE`。

**B. 处理顺序（先图片、后提交）**：
1. 先为每个 SKU 完成图片准备：生成缺失图(03) → 上传到「符合沃尔玛上传要求」的存储(04，Q1 待确认是否需传沃尔玛自家托管) → 校验图片已就绪且格式/尺寸符合要求。
2. 图片达标后组装 `replace_payload`(05)。
3. 最后才提交(06)并回写。

**C. 续跑判据：以 `feed_id` 为准**（核心，来自「未修改成功的下次断点续跑」要求）：
- 每条 SKU 记录带 `feed_id`（初始 null）与 `batch_no`（批次序号）。
- **已完成标志 = `feed_id` 非空**。已成功提交（拿到 Walmart 返回的 `feedId`）的 SKU，下次启动直接跳过，绝不重复提交。
- **每次启动只处理满足 `feed_id == null` 且 `符合要求`（图片就绪且校验通过、store 凭证齐全）的 SKU**；其余一律跳过。

**D. 分组、分批与回写**：
- 待处理 SKU 按 **(store, processMode)** 分组；每组按 `batch_size`（建议 100~500，单 feed 上限见 Q6.3）切分为多个 feed，每 feed 分配一个 `batch_no`。
- 每个 feed 提交成功后，立即把 `batch_no` + Walmart 返回的 `feed_id` **回写**到该 feed 内每条 SKU 记录（`submit_results.jsonl`）。

**E. 未成功 SKU 的续跑**：
- 本轮提交异常/被拒的 SKU，`feed_id` 保持 null，下次启动重新进入待处理池重试。
- 进程中断/重启同理：无 `feed_id` 且符合要求者自动续跑，已回写 `feed_id` 者跳过。
- **对账闭环（建议首版即实现，不可省）**：沃尔玛 feed 为异步处理，`feed_id` 仅代表「已接收排队」，**不代表 item 真的替换成功**。提交后须轮询 FeedStatus / FeedItemStatus / GetFeedErrorReportAPI 做最终对账：把沃尔玛侧真正失败的 item 的 `feed_id` 置回 null，使其重新进入待处理池重提；成功的维持。若把对账当可选、仅靠「提交拿到 feedId 即跳过」，会导致**已提交但被沃尔玛拒绝的 SKU 被永久跳过、漏提**。纯「提交成功即视为成功」仅适用于极小批量 + 人工盯盘，不可作为线上默认。

### 7.5 查结果独立为定时对账阶段（提交与对账解耦）

按「处理图片 → 提交沃尔玛 → 最后查结果」的节奏，把**查结果**从主流程剥离，作为独立、可定时运行的阶段：

- **主流程（含 06 提交）不阻塞等结果**：06 只负责组装 payload → 提交 feed → 落 `feed_id` → 把该 SKU 标记 `submitted`，立即进入下一条；拿到 `feedId` ≠ 替换成功，不在此步判定成败。
- **独立对账脚本 `07_reconcile.py`**：定时（cron / 调度）跑一次，对 `replace_status = submitted` 的 SKU 轮询 `FeedStatus` / `FeedItemStatus` / `GetFeedErrorReportAPI`，把沃尔玛侧真实结果回写：
  - 成功 → `replace_status = success`（闭环完成，后续启动自动跳过）；
  - 失败 → `replace_status = failed` 且把 `feed_id` 置回 null（重新变为待处理，下轮主流程重提）。
- **状态机**：`pending`（待提交）→ `submitted`（已提交待对账）→ `success`（沃尔玛确认）/ `failed`（需重提，回到 `pending` 池）。
- **续跑口径统一为 `replace_status`**：每次主流程启动只处理 `replace_status in (pending, failed)` 且符合要求的 SKU（与 §7.4 C 的 feed_id 判据一致，但用状态机区分更精确，避免把「已提交待对账」误当「已完成」）。

> 这样「提交」与「查结果」解耦：提交快、不卡顿；结果由独立定时任务兜底，失败自动回流重提，形成闭环。

---

## 8. 与既有项目架构的复用

| 复用点 | 来源 | 说明 |
|--------|------|------|
| BUZZ 适配器 / 模型候选池 / 预检 | `src/ai_gateway/adapters/buzz.py`、`clients/gateway_client.py` | 阶段 02 直接复用 |
| MXAPI 图片生成 + checkpoint | `src/ai_gateway/subtasks/mxapi_generate_images.py`、`clients/mxapi_image_client.py` | 阶段 03 复用 |
| 阿里云 OSS 上传 | `src/ai_gateway/clients/aliyun_oss_client.py` | 阶段 04 复用 |
| 配置加载 / 重试 / 日志 | `src/ai_gateway/config`、`retry_policy.py`、`logging` | 全局复用 |
| JSON 模板校验 | `src/ai_gateway/validators` | 阶段 02/05 复用 |
| 业务任务目录规范 | `subtasks/walmart_image_prompt` | 本任务照搬结构 |

**新增代码**：
- `src/ai_gateway/clients/walmart_api_client.py`：沃尔玛店铺后台 API 客户端（含按 store 选凭证、提交图片替换、错误标准化）。
- `src/ai_gateway/subtasks/image_replace_*.py`（可选）：可复用的「查询 OSS 已有图 / 组装替换结果」逻辑，供未来同类替换任务复用。
- `subtasks/walmart_image_replace/`：本业务任务的配置、入口脚本、阶段输出、README。

---

## 9. 目录结构规划

```text
subtasks/walmart_image_replace/
  README.md
  config.json
  input/walmart_replace.xlsx
  prompts/                      # 若提示词模板独立于文案，可放此处
  workflow_common.py
  00_full_workflow.py
  01_query_existing_images.py
  02_generate_prompts.py
  03_generate_images.py
  04_upload_oss.py
  05_build_replace_result.py
  06_submit_replace.py
  07_reconcile.py                # 独立对账：定时查沃尔玛 FeedStatus，回写 success/failed，失败回灌重提
  08_build_report.py              # 由中间 jsonl 派生「本次上传结果报告」（每次重跑重新生成）
  scripts/                        # 辅助脚本（与 walmart_image_prompt 惯例一致）
    build_image_input.py          # 03-1 按「缺失位置」动态展开图片入参 Excel（SKU列=OSS路径）
    execution_confirmation.py     # 提交前执行确认视图（只读：批次产物状态、06 预检、feed 分组计划）
    statistics/batch_stats.py     # 批次各阶段进度统计
  stages/                         # 各阶段配置 + README（入口脚本读这里取阶段参数）
    query_existing_images/config.json   # 命名正则 + min/max_sub_images + 表头映射（五点=单列）
    generate_prompts/config.json        # BUZZ 网关/模型（mock）、提示词入参、校验
    generate_images/config.json         # 共享模块 schema：MXAPI 网关/模型、命名模板、轮询/重试/续跑
    upload_oss/config.json              # 共享模块 schema：OSS key 模板（{sku}/{image_name}.png）、并发、幂等续跑
    build_replace_result/config.json    # 组装规则（主图独立）、完整性校验
    submit_replace/config.json          # feed 端点、process_mode/batch_size/gtin_type、预检、门控
    reconcile/config.json               # 对账端点、状态机、范围（仅 submitted）
    build_report/config.json            # 报告列、状态优先级
  tools/
    make_sample_input.py          # 生成中文表头示例入参 Excel（五点为单单元格）
  batches/<入参文件名>/
    01_query_existing_images/image_inventory.jsonl
    02_generate_prompts/model_results.jsonl  # 与 walmart_image_prompt 02 同构，sku=OSS路径
    02_generate_prompts/full_outputs/
    03_generate_images/image_input.xlsx           # 动态行数图片入参（03-1 生成）
    03_generate_images/image_generation_results.jsonl   # 行级，sku=OSS路径
    03_generate_images/image_generation_checkpoint.jsonl
    03_generate_images/downloaded_images/
    03_generate_images/raw_responses/
    04_upload_oss/oss_upload_results.jsonl   # 行级（sku=OSS路径、image_name、oss_key、oss_url）
    04_upload_oss/oss_upload_checkpoint.jsonl
    05_build_replace_result/replace_payload.jsonl
    06_submit_replace/submit_results.jsonl   # 含 feed_id + replace_status(pending/submitted/success/failed)
    07_reconcile/reconcile_results.jsonl     # 每次对账的 feed 状态快照与 item 级结果
    08_build_report/result_report.jsonl      # 本次上传结果报告（店铺/平台SKU/GTIN/图片链接/是否成功/失败原因）
    08_build_report/result_report.xlsx       # 同上，表格版
```

> **主图与副图建模**：`主图链接` 列单独作为沃尔玛 feed 的 `mainImageUrl`；OSS 已有图 + 生成的 `{OSS路径}/{开发SKU}/new_sub{位置}_{开发SKU}.png` 仅作为 `productSecondaryImageURL[]`（不含主图）。阶段 05 负责把主图从副图数组中摘出，避免同一张图被提交两次（见 §7.3）。

批次名由入参 Excel 文件名决定（与既有一致），`batches/` 入 `.gitignore`。

---

## 10. 测试关注点（供后续出测试用例）

### 10.1 正常流程
- 缺失 3 张 → 生成 3 张 → 上传 3 张 → 最终集 6 张完整 → 提交成功。
- `replace_mode=full` → 重新生成全部 6 张并替换。

### 10.2 边界场景
- OSS 路径**已有 6 张**（0 缺失）→ 不生成不上传，仅组装原图集并提交。
- OSS 路径**0 张** → 生成全部 4 张（`min_sub_images`）。
- `min/max_sub_images` 修改（如 3/8）时的补齐与封顶逻辑。
- 文件名**无法解析位置**（不符合 `naming.existing_name_pattern`）→ 视为不可解析，走明确错误处理而非误判。

### 10.3 异常 / 失败场景
- BUZZ 返回 JSON 非法 / 提示词条数 ≠ 需生成数 → 校验失败，阻断后续。
- MXAPI 部分图片生成失败 → 该 SKU 最终集不完整 → **06 预检拦截，不提交**。
- OSS 上传部分失败 → 同上拦截。
- 沃尔玛 API 限流(429)/5xx → 按 `max_retries` 退避重试；401/403（凭证错）→ 直接失败不重试。
- `store` 在配置中缺失 / 凭证未注入 → 预检拦截该 SKU。
- 网络中断：各阶段 checkpoint 保证续跑不重复扣费、不重复提交。

### 10.4 权限 / 配置场景
- `submit_replace=false` 时 06 必须不执行（只出报告）。
- `--dry-run` 全程不调 BUZZ/MXAPI/OSS/沃尔玛 API。
- 不同 `store` 使用各自凭证，互不串。

### 10.5 回归范围
- 复用既有 BUZZ / MXAPI / OSS 模块，回归其原有能力不被破坏。
- `naming.existing_name_pattern` 解析逻辑对既有命名格式兼容。

---

## 11. 待确认 / 开放问题

> 已对照官方文档（`developer.walmart.com` 的 MP_MAINTENANCE / Manage Items）核实：图片替换走 **`MP_MAINTENANCE` feed**（`POST /v3/feeds`，`feedType=MP_MAINTENANCE`，异步提交后轮询 Feed 状态）；feed 内 `Visible.<ProductType>` 的 `mainImageUrl` / `productSecondaryImageURL[]` 承载图片；item 由 **`sku` + `productIdentifiers`（GTIN 等）** 共同标识；`processMode` 决定替换语义（`REPLACE_ALL` 删旧副图整体替换 / `PARTIAL_UPDATE` 合并保留）。

1. **入参已明确，仍需确认执行细节**：SKU + GTIN（productIdType/productId）为必填；图片字段为 `mainImageUrl` 与 `productSecondaryImageURL[]`。待确认：base_url、鉴权方式、feed 提交与状态轮询的具体端点、是否幂等（同 SKU 重复提交是否安全）。
2. **图片托管路径（关键阻塞）**：沃尔玛 feed 里图片值是 `partnerId/imagefilepathname`（**沃尔玛自家图片托管**路径），通常需先把图片传到沃尔玛托管再引用。需确认：feed 是否接受**外站公开 URL**（如本项目的阿里云 OSS 公开链接）？若不接受，则新增「上传到沃尔玛图片托管」步骤，OSS 仅作为源/暂存。这会改变阶段 04 的产物与阶段 06 的引用方式。
3. **`processMode` 选择**：`full` 替换用 `REPLACE_ALL`（会删除旧 SECONDARY 图，提交完整图集）；`fill` 补缺失用 `PARTIAL_UPDATE`（合并、保留未提交旧图）。需与业务确认「替换」究竟是整体替换还是仅补足，决定默认 mode。
4. **「原图」是否参与提交**：取决于 mode——`REPLACE_ALL` 必须提交「原图 + 新图」完整集；`PARTIAL_UPDATE` 只需提交新增位置。已在 §2.1 入参与 §7 门控中按此区分。
5. **目标副图数 6 是否硬性**：是否所有店铺/类目都为 6；`REPLACE_ALL` 下副图数量是否受类目上限约束。
6. **OSS 已有图片的命名规范**：确认 `filename_pattern` 能覆盖真实文件名；是否需要处理非标准命名。
7. **文案 + 原图如何组装 prompt**：是整段文案 + 多张原图多模态，还是逐位置差异化？需产品/算法明确提示词模板。
8. **提交失败的补偿**：feed 异步处理，需依赖 FeedStatus / FeedItemStatus / FeedErrorReport 轮询与对账；部分位置图失效是否需要回滚/重提策略。单 feed 批量条数/体积上限见确认清单 **Q6.3**（本项目默认按 `batch_size` 分批，建议值待对接方确认）。

---

---

## 附录 A：沃尔玛图片替换 feed 示例（基于官方文档还原）

> 以下为根据官方 *Update my existing items* / *Global Marketplace* 文档与公开 feed 示例还原的**图片替换请求模板**。字段名与结构已对齐官方 schema；标注 `TODO` 的需对接方按 §11 确认。

### A.1 提交方式
- 端点：`POST https://marketplace.walmartapis.com/v3/feeds?feedType=MP_MAINTENANCE`（Global Marketplace 同路径，注意环境与 businessUnit）
- 提交后异步处理，用 Feeds API 轮询：`AllFeedStatusesAPI` / `FeedItemStatusAPI` / `GetFeedErrorReportAPI`
- 一个 feed 可含多个 `MPItem`（一次提交多个 SKU）

### A.2 请求体模板（整体替换图片集，processMode=REPLACE_ALL）

```json
{
  "MPItemFeedHeader": {
    "locale": "en",
    "version": "5.0.20240517-04_08_27-api",   // TODO: 用 Get Spec API 取准确 schema 版本
    "businessUnit": "WALMART_US",             // TODO: 按店铺/市场填
    "processMode": "REPLACE_ALL"               // 整体替换（删除旧副图）；仅补足用 PARTIAL_UPDATE
  },
  "MPItem": [
    {
      "Orderable": {
        "sku": "<platform_sku>",                       // 来自入参 platform_sku
        "productIdentifiers": {
          "productIdType": "GTIN",                     // 来自入参 gtin_type（GTIN/UPC/EAN/ISBN）
          "productId": "<gtin>"                        // 来自入参 gtin（必填，与 sku 同时出现）
        }
      },
      "Visible": {
        "<ProductType>": {                             // TODO: 该 SKU 的 ProductType（从 Get An Item 取）
          "mainImageUrl": "<主图 URL>",               // 沃尔玛托管路径 partnerId/... 或 walmartimages.com URL
          "productSecondaryImageURL": [               // 副图数组，按顺序排列
            "<副图1 URL>", "<副图2 URL>", "<副图3 URL>",
            "<副图4 URL>", "<副图5 URL>", "<副图6 URL>"
          ]
        }
      }
    }
  ]
}
```

### A.3 关键注意点（来自官方文档）
- `processMode` 在 **feed 头**；`REPLACE_ALL` 会**删除旧的 SECONDARY/SWATCH 图片**并用提交集整体替换；`PARTIAL_UPDATE` 合并、保留未提交旧图（且不能带 MPOffer 元素）。
- `sku` 与 `productIdentifiers` **两者必填**，缺一会报错；同一 spec 内不能同时改 SKU 和 productId。
- 图片 URL 官方示例均为 `*.walmartimages.com/asr/...`（沃尔玛托管）；结合 *Hosting images with Walmart* 文档，feed 引用值为 `partnerId/imagefilepathname`。**外站 URL 是否可接受为待确认项 Q1**。
- `version` / `businessUnit` / `ProductType` 必须与实际商品匹配，建议先 `Get An Item` 取现状再构造。

---

> 下一步建议：先确认第 2 点（图片托管路径）与第 3 点（processMode 默认语义），这两点直接决定阶段 04/06 的实现形态，再进入实现与测试用例编写。
