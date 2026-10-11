# MCP 集成说明 · MCP_INTEGRATION

本文件说明「麦麦瘦身助手」实际使用的麦当劳 MCP Server、Tool、调用流程、**实测调用契约**与业务价值。

---

## 1. 使用的 MCP Server

| 项 | 值 |
| --- | --- |
| Server 名称 | `mcd-mcp`（麦当劳中国官方 MCP Server） |
| 接入方式 | Streamable HTTP |
| 服务地址 | `https://mcp.mcd.cn` |
| 鉴权方式 | HTTP Header `Authorization: Bearer <MCD_MCP_TOKEN>` |
| 传输协议 | MCP (Model Context Protocol) over HTTP，JSON-RPC 2.0 |

配置片段见 [`mcp-config.example.json`](./mcp-config.example.json)（仅环境变量占位符，**严禁提交真实 Token**）。

本地 CLI 通过 `src/mcd_fit/mcp_client.py`（仅标准库的 JSON-RPC 客户端）同样可以直接调用该 Server，
便于脱离 WorkBuddy 独立运行与单元测试。

---

## 2. 实际调用的 Tool 清单

| # | Tool | 链路 | 在本项目中的用途 |
| --- | --- | --- | --- |
| 1 | `now-time-info` | A/B | 校准当前时间（日历月份锚点、活动时效） |
| 2 | `order-list` | **B** | 拉取历史订单 → 逐单热量 → 热量日历与习惯画像 |
| 3 | `query-my-coupons` | A | 卡包券资产（展示用） |
| 4 | `auto-bind-coupons` | A | 推荐前一键领券 |
| 5 | `query-store-coupons` | A | 查**指定门店 + 订单类型**可用的券（比价输入） |
| 6 | `query-nearby-stores` | A | 按城市/位置找门店，取 `storeCode` |
| 7 | `query-meals` | A | 菜单与价格（价格 + 营养匹配的输入） |
| 8 | `query-meal-detail` | A | 套餐组成 / 特调选项 |
| 9 | `calculate-price` | A | **真实计价**：健康方案用券后的实付复核 |
| 10 | `create-order` | A | 用户确认后一键下单 |
| 11 | `query-order` | A | 下单后查询订单状态 |

---

## 3. 实测调用契约（官方文档没写、但跑通链路必需）

这些坑都封装在 `src/mcd_fit/adapter.py`，算法层不接触原始响应：

| # | 契约 | 说明 |
| --- | --- | --- |
| 1 | **价格单位是「分」** | `calculate-price` 与 `order-list` 返回金额均为分；展示前 `/100` |
| 2 | beType 与 beCode 绑定 | 到店自取 `beType=1` **不传** beCode；得来速 `5`/麦乐送 `2`/团餐 `6` **必传** beCode |
| 3 | orderType 跟随 beType | 到店（自取+得来速）`orderType=1`；外送（麦乐送+团餐）`orderType=2` |
| 4 | 下单需 `takeWayCode` | 到店场景（orderType=1）必传，取自 `calculate-price` 返回的 `takeWayList[].code` |
| 5 | **退款必须过滤** | `order-list` 中整单退款订单若不过滤，热量与支出全部虚高 |
| 6 | 订单时间字段多形态 | `orderTime` / `createTime` / `date`，格式含 `yyyy-MM-dd HH:mm:ss` 等多种 |
| 7 | 商品编码跨接口一致 | `order-list` 的商品 `productCode` 与 `query-meals` 的 `code` 同源，可做营养匹配主键 |
| 8 | 券没有面值字段 | 券价值需从菜单**反查原价**推算；查不到原价一律记 0 并标注，绝不估算 |
| 9 | 卡包券 ≠ 可用券 | `query-my-coupons` 只代表拥有；下单前以 `query-store-coupons` 为准 |
| 10 | 菜单字段名有版本差异 | `price` / `salePrice` / `unitPrice` 多候选兜底 |
| 11 | 响应可能是 SSE | Streamable HTTP 下响应体可能为 `text/event-stream`，客户端需双格式解析 |
| 12 | 会话头 | 服务端可能返回 `Mcp-Session-Id`，后续请求需原样回传 |

---

## 4. 端到端调用流程

```
【链路 B · 长期】「我最近吃得健康吗？」
    order-list ──► adapter.to_orders（退款过滤 + 分→元 + 字段映射）
        │
        ▼
    nutrition_db 逐项匹配热量（查不到 → 标记「未知」，绝不估算）
        │
        ▼
    auditor.audit ──► 逐日热量 + 超标天数 + 高频单品 + 夜宵/含糖饮料统计
        │
        ▼
    calendar_render ──► 文本月历（终端） + SVG 月历（可保存分享）
        │
        ▼
    body.energy_targets ──► BMR/TDEE/每日目标/本餐目标（缺口 400 kcal）

【链路 A · 单次】「这一餐怎么吃更健康？」
    query-nearby-stores ──► storeCode
        │
        ▼
    auto-bind-coupons + query-store-coupons ──► 本店可用券
        │
        ▼
    query-meals ──► 菜单（价格 + 营养匹配）
        │
        ▼
    advisor.recommend ──► 枚举「主食1+小食0-2+饮料0-1+甜品0-1」组合
        │                 营养评分：|kcal−目标|·0.6 惩罚 + 蛋白质·2 加分
        │                 −超钠·0.05 −超糖·1.5（评分拆解全程可解释）
        ▼
    pricing.best_coupon_plan ──► 只在已选餐品内用券，不为用券凑单
        │
        ▼
    calculate-price ──► 官方口径复核实付
        │
        ▼
    输出方案 + 理由 + 替换建议 ──► 用户确认 ──► create-order ──► query-order
```

## 5. 参数传递硬规则

- 所有价格为**分**；`storeCode` 必须全为数字；
- `query-store-coupons` / `calculate-price` / `create-order` 的 `orderType`、`beType`、`beCode`
  必须与用户所选取餐方式一致（见契约 #2/#3）；
- 下单（orderType=1）必须传 `takeWayCode`（见契约 #4）。

---

## 6. 业务价值

| 价值维度 | 说明 |
| --- | --- |
| **补齐信息缺口** | 点单页只有价格没有热量，本项目把热量变成一等公民 |
| **可执行的小改变** | 「可乐 → 零度可乐（−180 kcal）」这类替换建议，比膳食计划书更容易被采纳 |
| **行为可视化** | 热量日历把「最近吃多了」变成一张看得见的月历，超标日一目了然 |
| **健康与省钱不冲突** | 健康方案内部仍跑用券最优化，省下的钱是健康的额外奖励 |
| **数据可信** | 未知热量不估算、退款过滤、官方计价复核——每个数字都可溯源 |
| **可复用引擎** | 营养评分/审计/日历与麦当劳解耦，可平移到其他餐饮 MCP 场景 |

---

## 7. 降级与容错

- 未配置 Token / 网络异常 → 自动降级到 `mock_data.py` 确定性样例（`cli demo`），保证可演示、可复现；
- 订单里出现营养库未收录的餐品 → 单独计数「未知热量」，**不计入**总量（宁缺毋滥）；
- `calculate-price` 与本地估算不一致 → 以官方返回为最终口径；
- 下单前必须用户显式确认（CLI 需追加 `--confirm`），未确认一律不执行。
