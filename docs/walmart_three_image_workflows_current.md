# Walmart 三条图片流程现状说明

本文依据 2026-09-22 当前代码整理，说明以下三个独立业务：

- `walmart_image_prompt`：从商品资料重新策划并生成一套主图和副图。
- `walmart_image_replication`：以原主图和每张原副图为参照，逐张复刻新的主图和副图。
- `walmart_image_replace`：保留线上现有主图，只补齐最终图集中不足的新版副图。

三条流程共享底层图片平台适配器、异步任务、下载、断点和OSS上传组件，但输入含义、提示词来源、参考图用法、目标图片数量和最终结果不同。批次目录彼此隔离，不能混用任务ID或检查点。

## 一、业务边界对照

| 对比项 | 图片策划生成 `image_prompt` | 图片复刻 `image_replication` | 旧图替换 `image_replace` |
| --- | --- | --- | --- |
| 核心目的 | 根据商品资料重新策划完整图片 | 按原图视觉作用逐张重新制作 | 保留主图，按配置补足目标数量的新副图 |
| 是否调用文字模型 | 是 | 否 | 是 |
| 主图 | 生成新的优化主图 | 生成新的复刻主图 | 原样保留，不生成 |
| 副图数量 | 文字模型规划6类候选，当前目标成功5张 | 按非空原副图逐张复刻，当前最多5张 | `minimum_new_sub_images` 默认4、允许1～6；按已有新副图数动态补齐，超出目标全部保留 |
| 副图设计来源 | 文字模型重新策划 | 对应原副图的构图和视觉作用 | 文字模型从原六类体系中选择缺少数量的互补方案 |
| 生图参考图 | 主图任务用原主图；副图任务实际用原主图 | 主图任务用原主图；副图任务用原主图＋对应原副图 | 每个副图任务使用输入参考主图＋全部参考副图，来源不限于Walmart |
| 文字资料 | 标题、五点 | 标题、五点、描述 | 标题、五点 |
| OSS路径 | `develop/{sku}/...` | `develop/{sku}/...` | 来源SKU的原Walmart OSS目录 |
| 最终结果用途 | 新开发商品图片及人工审核 | 原有图片去品牌/版权风险后的复刻结果 | 交给 `walmart_api` 更新平台副图；本项目不提交Walmart |

## 二、图片策划生成流程：walmart_image_prompt

### 1. 输入和目标

当前输入Excel要求：

- `SKU`
- `标题`
- `五点`
- `主图`
- 可选的 `副图参考1` 至 `副图参考10`

当前总配置只取前4张副图参考，因此文字模型每个SKU最多收到：

```text
1张主图 + 4张副图参考
```

业务目标由两部分组成：

- 每个SKU生成1张优化主图。
- 文字模型先规划6类副图候选，图片阶段按当前优先级争取成功5张。

当前副图优先级为：

1. Hero Feature Image
2. Lifestyle Scene
3. Product Detail Showcase
4. Why Choose Us
5. Feature Explanation
6. Package & Detail / Trust Image

第6类是候补。当靠前类型明确失败时，后续类型可以补足目标5张。

### 2. 第一阶段：构建文字模型任务

入口：`01_generate_prompt_tasks.py`

提示词模板：

```text
subtasks/walmart_image_prompt/prompts/walmart_image_prompt_template.txt
```

程序将模板中的：

- `{{产品标题}}` 替换为Excel标题；
- `{{产品五点}}` 替换为Excel五点。

随后把渲染后的完整模板、主图和最多4张副图参考组成一个多模态任务，写入：

```text
01_get_pic_prompt/generated_prompt_tasks.jsonl
```

这一阶段只组装请求，不调用模型。

### 3. 第二阶段：文字模型规划副图

入口：`02_call_prompt_model.py`

当前配置使用 `tuzi_text` 和 `gpt-5.6-luna`，候选模型为 `gpt-5.6-terra`、`gpt-5.4`。开启模型预检时，会先读取当前Key可用模型，再选择首选或候选。

文字模型必须返回JSON对象，核心内容为：

- `product_analysis`
- 固定6个对象的 `image_plan`
- `global_prompt_restrictions`
- `final_checklist`

当前共享校验确认返回可解析为JSON、`image_plan` 数量等于6且没有明显乱码。成功完整结果保存到：

```text
02_call_prompt_model/full_outputs/<SKU>__<模型>.json
```

轻量状态、校验结果和完整文件路径保存到 `model_results.jsonl`。成功且校验通过的任务断点续跑时跳过；失败或无效结果后续重试。

### 4. 主图提示词及生图

入口：`03b_generate_main_images.py`

主图不使用第二阶段返回的JSON，也不再次调用文字模型。程序直接读取固定提示词：

```text
subtasks/walmart_image_prompt/prompts/main_image_optimization_prompt.txt
```

每个SKU形成一行：

```text
参考图：原主图
提示词：完整固定主图提示词
图片名：new_main_<SKU>
模式：fixed
```

固定模式表示图片引擎直接使用Excel中的“生成提示词”。主图任务异步提交；取得 `task_id` 后立即保存。后续轮次查询原任务，完成后下载，不重复提交。

主图任务Excel已存在时会直接复用。修改源数据或主图提示词后，如果确实需要重建主图入参，需要人工删除该批次的主图任务Excel；图片checkpoint不会因此自动删除。

### 5. 副图提示词及生图

入口：`03_generate_and_download_images.py`

程序读取成功的文字模型JSON，按 `image_type_order` 建立“图片类型 → image_number”映射，并生成6行候选入参。每行图片名沿用文字模型编号，例如：

```text
new_sub1_<SKU>
new_sub2_<SKU>
...
```

图片引擎读取对应 `image_plan` 对象的 `ai_image_generation_prompt`，并追加完整公共限制：

```text
<该对象的 ai_image_generation_prompt>

Global Prompt Restrictions:
<global_prompt_restrictions 的JSON文本>
```

实际副图生图请求使用原主图作为产品参考图。阶段一传给文字模型的副图参考用于策划，但不会再次逐张传给副图生图请求。

图片引擎按优先级处理6个候选，同一SKU成功达到当前 `desired_count=5` 后，其余候选显示为目标已满足并跳过。平台明确失败时，可以按当前 `max_regenerations_per_image=6` 重新提交。

### 6. 下载、OSS和结果

主图、副图各有独立的结果、checkpoint、下载目录和OSS结果。当前图片平台为TUZI异步接口：

1. 提交任务并保存 `task_id`；
2. 后续轮次查询 `submitted/pending`；
3. 完成后下载；
4. 下载429只延后当前图片，保留原task_id；
5. 成功图片上传OSS，普通PNG按总配置转为高质量JPEG，透明图保留PNG。

最终副图表 `最终图片结果_由sub生成.xlsx` 只汇总副图OSS结果；主图OSS结果在独立目录。人工审核入口 `07_export_review.py` 才把主图和副图合并展示。

## 三、图片复刻流程：walmart_image_replication

### 1. 输入和目标

当前输入Excel要求：

- `SKU`
- `标题`
- `五点`
- `描述`
- `主图`
- `副图参考1` 至 `副图参考6`

当前每个SKU最多选择前5张非空副图参考。目标是：

- 生成1张新的主图；
- 每一张选中的原副图对应生成1张新副图。

这里没有“六类图片策划”和动态补位。副图任务与原副图是一对一关系。原副图3为空时会跳过该位置；图片名称保留原列序号，例如副图1和副图4非空时生成 `new_sub1_<SKU>`、`new_sub4_<SKU>`。

### 2. 第一阶段：直接构建图片任务

入口：`01_build_replication_tasks.py`

本流程不调用文字模型，也不生成JSON方案。程序直接产生图片平台Excel：

```text
01_build_replication_input/walmart_replication_input.xlsx
```

一个SKU的主图和副图都在同一个任务表中。

### 3. 主图提示词

固定提示词：

```text
subtasks/walmart_image_replication/prompts/main_image_optimization_prompt.txt
```

主图任务内容：

```text
参考图：原主图1张
提示词：固定主图优化提示词
图片名：new_main_<SKU>
图片类型：Main Image
```

其业务目标是保持产品100%真实，在白底条件下调整摆放、角度、构图和商业摄影效果。

### 4. 副图提示词

固定模板：

```text
subtasks/walmart_image_replication/prompts/walmart_image_replication_prompt.txt
```

程序只做三项文本替换：

- `{{标题}}`
- `{{五点}}`
- `{{描述}}`

同一个SKU的所有副图任务使用同一份渲染后提示词，不经过JSON解析，也不按对象提取字段。

每个副图任务提供两张参考图：

```text
第1张：产品主图
第2张：当前这一张原副图
```

提示词明确区分两张图的职责：

- 第1张只负责锁定产品身份，纠正结构、颜色、材质、比例、配件和功能区域；
- 第2张负责当前副图的视觉作用、视角、摆放、构图、背景、光线、场景关系和信息布局；
- 不能逐像素复制，应去除品牌、商标、版权风险图案，并在有人物时替换为不同人物。

因此复刻流程的“提示词差异”主要来自每个任务对应的第二张原副图，而不是来自不同的文字提示词对象。

### 5. 图片提交、断点和开关

入口：`02_generate_replication_images.py`

图片阶段统一使用 `prompt_mode=fixed`，直接读取任务Excel里的“生成提示词”。主图和副图在同一个图片引擎运行中处理，但可分别通过以下开关启停：

- `generate_main_images`
- `generate_sub_images`

关闭某一类只停止该类的新提交和查询，不删除历史任务、task_id、下载文件、checkpoint或OSS结果。

当前异步逻辑为：

1. 新任务提交后保存task_id；
2. 下一轮查询原task_id；
3. 完成后下载；
4. 成功任务断点跳过；
5. 明确失败按 `max_regenerations_per_image` 重试，当前上限4次；
6. `max_records` 按SKU限制，不按图片行限制。

### 6. OSS、最终结果和审核

入口顺序：

```text
01 构建任务
→ 02 图片提交/查询/下载
→ 03 上传OSS
→ 04 生成最终结果
```

主图和副图上传到同一业务路径规则 `develop/{sku}/{image_name}.{extension}`。普通PNG在上传阶段转为JPEG，透明图片保留PNG。

最终结果 `最终图片结果_由复刻生成.xlsx` 按SKU汇总成功上传的主副图，副图连续填充，不保留中间空列。`05_export_replication_review.py` 是独立人工审核步骤，不属于自动循环。

## 四、旧图替换流程：walmart_image_replace

该流程的详细设计仍以 `docs/walmart_image_replace_design.md` 为准。这里仅说明它与另外两条流程的接口差异。

### 提示词链路

1. 根据已有副图文件名识别 `new_sub`，计算 `need_sub=max(0, minimum_new_sub_images-已有新副图数)`。目标数默认4、允许1～6，并在批次创建时锁定。
2. 主图原样保留，主图生成和上传入口被禁止。
3. 使用从 `walmart_image_prompt_template.txt` 适配出的 replace模板；标题、五点和动态数量进入真实文字模型请求。
4. 文字模型同时收到输入参考主图和全部参考副图，支持任意合法HTTP/HTTPS公网图片URL。
5. 返回内容必须通过replace专用结构校验，包括动态数量、连续编号、允许且不重复的图片类型、必需字段、公共限制和最终检查项。
6. 每个 `image_plan` 对象形成一个独立副图任务；实际生图提示词为该对象的 `ai_image_generation_prompt` 加完整 `global_prompt_restrictions`。
7. 每个图片任务继续携带同一组输入参考主副图。

### 结果链路

新图上传到本次来源SKU的原OSS目录，使用唯一名称。最终结果保留原主图、已有新副图和成功上传的新副图；旧副图只进入待归档候选。输出三套结果：

- 最新使用图片URL
- 本批次新生成图片URL
- 待归档旧副图URL

本流程不提交Walmart。最终Excel交给独立 `walmart_api` 项目进行平台更新。

## 五、不要混淆的关键区别

### image_prompt 与 image_replace

- `image_prompt` 目标是重新生成完整主副图体系；`image_replace` 只补缺少的新副图。
- `image_prompt` 固定规划6类候选并按优先级成功5张；`image_replace` 每行只返回 `need_sub` 条。
- `image_prompt` 的副图生图阶段只使用原主图作为参考；`image_replace` 每个副图任务使用全部输入参考主副图。
- `image_prompt` 使用开发目录；`image_replace` 使用来源SKU的历史Walmart目录。

### image_prompt 与 image_replication

- `image_prompt` 用文字模型重新策划；`image_replication` 不调用文字模型。
- `image_prompt` 的六张候选代表六种营销设计类型；`image_replication` 的每张副图直接对应一张原副图。
- `image_prompt` 的差异来自各个JSON对象提示词；`image_replication` 的同SKU副图共用一份固定提示词，差异来自第二张参考图。

### image_replication 与 image_replace

- `image_replication` 无论原图新旧，按选中的原副图逐张复刻；`image_replace` 明确不使用旧副图，只补足新图数量。
- `image_replication` 可以生成主图；`image_replace` 禁止修改主图。
- `image_replication` 直接生成图片；`image_replace` 先调用文字模型生成动态方案，再提交图片任务。

## 六、运行安全边界

- 三个总流程的正式模式都会根据开关调用外部服务；运行前应检查当前 `config.json`。
- `--dry-run` 用于读取和预览，不应调用文字模型、生图平台、下载或OSS。
- 同一批次成功结果、task_id和checkpoint用于断点续跑，不应随意删除。
- 输入文件名决定批次目录；需要完全独立测试时使用新的输入文件名。
- 不要同时启动同一批次的多个进程。
- 人工审核导出与平台更新是不同动作。审核Excel不会自动提交Walmart。
