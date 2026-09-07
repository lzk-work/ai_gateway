# 沃尔玛图片替换 · API 对接确认清单

> 用途：发给负责沃尔玛 API 对接的研发 / 接口方，确认图片替换流程的关键未知项。
> 来源：已基于官方文档（`developer.walmart.com` 的 *Update my existing items* / *Manage Items* / *Hosting images with Walmart*）核对。
> 标注说明：**【已确认】** = 官方文档已明确，无需再答；**【待确认】** = 需对接方回填；**【阻塞】** = 不确认会导致设计/实现卡住。

---

## 0. 已确认（来自官方文档，无需再答）

- 图片替换走 **`MP_MAINTENANCE` feed**：`POST /v3/feeds`，`feedType=MP_MAINTENANCE`，异步提交后轮询 Feed 状态。
- 商品由 **`Orderable.sku` + `Orderable.productIdentifiers{productIdType, productId}`** 共同标识；维护 feed 中 SKU 与商品标识（GTIN/UPC/EAN/ISBN）**两者必填**，缺一不可。
- 图片承载字段在 `Visible.<ProductType>` 下：`mainImageUrl`（主图）、`productSecondaryImageURL[]`（副图数组）。
- `processMode` 语义：`REPLACE_ALL` = 整体替换 MPProduct/MPOffer，并**删除旧的 SECONDARY/SWATCH 图片**；`PARTIAL_UPDATE` = 合并内容、保留未提交的旧图（不能带 MPOffer 元素）。
- 新卖家应迁移到 **Global Marketplace APIs**（现有 MP feed 仍可用）。

---

## 1. 【阻塞】图片托管方式

- **Q1.1【待确认】** feed 里的图片 URL 是否接受**外站公开 URL**（如本项目阿里云 OSS 的公开链接）？还是必须先把图片传到**沃尔玛自家图片托管**（`partnerId/imagefilepathname` 路径）后才能引用？
- **Q1.2【待确认】** 若必须用沃尔玛托管：图片上传接口路径、路径命名规范（`partnerId/dir/file`）、`partnerId` 如何获取、接受的格式/尺寸/分辨率/命名约束分别是什么？
- **影响**：决定「阶段 04 上传 OSS」的产物形态与「阶段 06 提交」的引用方式。如果必须走沃尔玛托管，需**新增「上传到沃尔玛图片托管」步骤**，阿里云 OSS 降级为源/暂存。这是当前最大阻塞。

## 2. 【阻塞】processMode 默认语义

- **Q2.1【待确认】** 业务语义的「替换」到底是**整体替换**（用 `REPLACE_ALL` 提交完整图集）还是**仅补足缺失**（用 `PARTIAL_UPDATE` 只提交新增）？
- **Q2.2【待确认】** `REPLACE_ALL` 下，只提交 `Visible` 的图片字段时，是否**不会清空/覆盖 MPOffer**（价格、库存等）？
- **Q2.3【待确认】** 副图数量是否有类目上限？是否所有店铺/类目都按 6 张处理？
- **影响**：决定默认 `processMode` 与「阶段 05 组装最终图集」的逻辑（全集 vs 增量）。

## 3. API 端点与鉴权

- **Q3.1【待确认】** 调用 base_url 与环境（prod / sandbox）？
- **Q3.2【待确认】** 鉴权方式（Marketplace 通常为 Consumer ID + Private Key 签名 / OAuth Token）？密钥如何注入（与现有 `configs/local.env` 体系如何对齐）？
- **Q3.3【待确认】** feed 提交、状态轮询（FeedStatus/AllFeedStatuses）、逐条状态（FeedItemStatus）、错误报告（GetFeedErrorReport）的接口路径与返回结构？
- **Q3.4【待确认】** 是否应直接采用 Global Marketplace APIs（新体系）而非经典 MP feed？两者图片替换入参是否有差异？

## 4. 商品标识与多店铺

- **Q4.1【待确认】** 确认本任务是 **Marketplace 卖家体系**（非 1P/DSV 供应商体系）？1P 体系主键是 GTIN-14 + WIN，入参设计不同。
- **Q4.2【待确认】** 贵方账号下「SKU + GTIN 两者必填」是否适用？GTIN 豁免商品如何取得 Walmart 生成的 GTIN？
- **Q4.3【待确认】** 入参里的 `store`（所属店铺）如何映射到账号/凭证：是同一卖家账号下不同 store 参数，还是多个独立卖家账号？这决定 `walmart_api` 配置是按 store 选凭证还是选账号。

## 5. 图片字段与顺序

- **Q5.1【待确认】** 当前使用的 schema 版本（如 `MP_MAINTENANCE-5.0.20240517-04_08_27` 或最新）与 `ProductType`？字段名是否确为 `mainImageUrl` / `productSecondaryImageURL`？
- **Q5.2【待确认】** 副图的**排列顺序**由数组顺序决定，还是由文件名/位置编号决定？主图是否也在本次替换范围内？
- **Q5.3【待确认】** 接受的图片格式、建议分辨率、单文件大小、命名约束（是否允许中文/特殊字符）？

## 6. 幂等性与错误处理

- **Q6.1【待确认】** 同一 SKU **重复提交**是否幂等安全（重复提交不会导致商品异常或重复计费）？
- **Q6.2【待确认】** feed 内单条商品失败时，如何通过 `FeedItemStatus` 逐条定位失败原因？
- **Q6.3【待确认】** 限流（429）策略、单次 feed 批量条数上限、建议提交并发？

## 7. 异步监控

- **Q7.1【待确认】** feed 状态轮询端点、典型处理耗时、错误报告文件格式（用于阶段 06 提交后的对账与回归）？

---

## 回填区（对接方填写）

| 问题编号 | 结论 | 依据 / 备注 |
|----------|------|------------|
| Q1.1 |  |  |
| Q1.2 |  |  |
| Q2.1 |  |  |
| Q2.2 |  |  |
| Q2.3 |  |  |
| Q3.1 |  |  |
| Q3.2 |  |  |
| Q3.3 |  |  |
| Q3.4 |  |  |
| Q4.1 |  |  |
| Q4.2 |  |  |
| Q4.3 |  |  |
| Q5.1 |  |  |
| Q5.2 |  |  |
| Q5.3 |  |  |
| Q6.1 |  |  |
| Q6.2 |  |  |
| Q6.3 |  |  |
| Q7.1 |  |  |

---

> 优先级：先回答 **Q1.1 / Q1.2 / Q2.1** 三个阻塞项，即可定稿阶段 04/05/06 的实现形态，再进入开发与测试用例编写。
