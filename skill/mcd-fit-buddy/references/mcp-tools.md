# 麦当劳 MCP Tool 速查手册（mcd-fit-buddy 参考）

> 供 Skill 与源码调用时查阅。价格字段单位统一为**分**。

---

## 一、参数传递总规则

| 用户场景 | beType | orderType | beCode | 说明 |
| --- | --- | --- | --- | --- |
| 到店自取 | 1 | 1 | **不传** | 传了会报错 |
| 得来速 DT | 5 | 1 | **必传** | 来自 `query-nearby-stores` |
| 麦乐送 | 2 | 2 | **必传** | 来自 `delivery-query-stores` |
| 企业团餐 | 6 | 2 | **必传** | 来自 `delivery-query-stores` |

---

## 二、本项目重点字段

### order-list（热量审计数据源）
- 出参要点：`orderId`、`orderTime`、`totalAmount`（分）、`items[{productCode, productName, quantity, price}]`
- ⚠️ **整单退款必须过滤**（`orderStatus=REFUNDED` / `refunded=true`），否则热量与支出虚高
- ⚠️ 商品 `productCode` 与 `query-meals` 的 `code` 同源，可作营养匹配主键

### query-meals
- 入参：`storeCode`, `orderType`, `beType`[, `beCode`][, `reservationDate`]
- 出参要点：`productCode` / `productName` / `price`（分）/ `category`
- ⚠️ 不同版本字段名可能是 `salePrice` / `unitPrice`，需多候选兜底

### query-store-coupons
- 入参：`storeCode`, `orderType`, `beType`[, `beCode`][, `reservationDate`]
- ⚠️ 卡包券（`query-my-coupons`）只代表拥有，不代表当前门店可用；下单前以本接口为准

### calculate-price
- 入参：`storeCode`, `orderType`, `beType`[, `beCode`], `items[{productCode, quantity, couponId?, couponCode?}]`
- 出参：价格单位为**分**；`takeWayList[].code` 供下单使用

### create-order
- 入参：`storeCode`, `orderType`, `beType`, `items[]`
- 到店/得来速（orderType=1）**必传** `takeWayCode`
- 外送/团餐还需 `addressId`（团餐另需 `gmServiceCode`）

---

## 三、最小调用示例（JSON-RPC 语义）

```json
// 1) 历史订单（热量审计）
{"name":"order-list","arguments":{}}

// 2) 找门店
{"name":"query-nearby-stores","arguments":{"searchType":2,"city":"上海","keyword":"人民广场","beType":1}}

// 3) 领券 + 查门店可用券
{"name":"auto-bind-coupons","arguments":{}}
{"name":"query-store-coupons","arguments":{"storeCode":"1234567","orderType":1,"beType":1}}

// 4) 健康方案真实计价
{"name":"calculate-price","arguments":{
  "storeCode":"1234567","orderType":1,"beType":1,
  "items":[
    {"productCode":"M004","quantity":1,"couponCode":"IT_GB4"},
    {"productCode":"M102","quantity":1},
    {"productCode":"M202","quantity":1}
  ]
}}
```
