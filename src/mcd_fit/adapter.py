"""MCP 适配层：唯一进行「单位换算 + 字段映射 + 退款过滤」的地方。

实测契约（踩坑记录，见 MCP_INTEGRATION.md）：
1. ``calculate-price`` 返回价格单位是**分**；
2. ``order-list`` 返回的金额同样是**分**；
3. 菜单接口不同版本字段名可能不同（price / salePrice / unitPrice），统一在此兜底；
4. 历史订单里「整单退款」必须过滤，否则支出与热量都会虚高；
5. 券通常只有名称没有面值，需从菜单反查原价推算（无法反查则记 0 并标注）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .models import Coupon, MenuItem, Nutrition, OrderItem, OrderRecord
from .nutrition_db import attach_nutrition, lookup

# --------------------------------------------------------------------------- #
# 通用
# --------------------------------------------------------------------------- #

def _pick(d: Dict[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def fen_str(fen: int) -> str:
    return f"¥{fen / 100:.2f}"


def _to_fen(value: Any, unit: str = "fen") -> int:
    if value in (None, ""):
        return 0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0
    return int(round(num if unit == "fen" else num * 100))


def _as_list(result: Any, keys: Sequence[str]) -> List[Dict[str, Any]]:
    if result is None:
        return []
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, str):
        import json

        try:
            return _as_list(json.loads(result), keys)
        except json.JSONDecodeError:
            return []
    if isinstance(result, dict):
        for k in keys:
            v = result.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        data = result.get("data")
        if isinstance(data, (dict, list)):
            return _as_list(data, keys)
    return []


# --------------------------------------------------------------------------- #
# 菜单
# --------------------------------------------------------------------------- #

def to_menu(raw: Any, price_unit: str = "fen") -> List[MenuItem]:
    """把 MCP 菜单响应映射为 MenuItem，并尽力补齐营养数据。"""
    items: List[MenuItem] = []
    for row in _as_list(raw, ("meals", "mealList", "products", "list", "data")):
        item = MenuItem(
            product_code=str(_pick(row, ("productCode", "code", "mealCode"), "")),
            name=str(_pick(row, ("productName", "name", "mealName"), "餐品")),
            price_fen=_to_fen(_pick(row, ("price", "salePrice", "unitPrice", "amount")), price_unit),
            category=str(_pick(row, ("category", "categoryName", "type"), "其他")),
        )
        nutrition_raw = _pick(row, ("nutrition", "nutriInfo"))
        if isinstance(nutrition_raw, dict) and nutrition_raw.get("calories") is not None:
            item.nutrition = Nutrition(
                calories_kcal=float(nutrition_raw.get("calories", 0)),
                protein_g=float(nutrition_raw.get("protein", 0) or 0),
                fat_g=float(nutrition_raw.get("fat", 0) or 0),
                carbs_g=float(nutrition_raw.get("carbs", 0) or 0),
                sodium_mg=float(nutrition_raw.get("sodium", 0) or 0),
                sugar_g=float(nutrition_raw.get("sugar", 0) or 0),
                source="MCP 菜单返回的官方营养字段",
            )
        items.append(attach_nutrition(item))
    return items


# --------------------------------------------------------------------------- #
# 历史订单
# --------------------------------------------------------------------------- #

def to_orders(raw: Any, amount_unit: str = "fen") -> List[OrderRecord]:
    """把 ``order-list`` 响应映射为 OrderRecord；**过滤整单退款**。"""
    orders: List[OrderRecord] = []
    for row in _as_list(raw, ("orders", "orderList", "list", "data")):
        refunded = bool(_pick(row, ("refunded", "isRefund", "refundFlag"), False)) or \
            str(_pick(row, ("orderStatus", "status"), "")).upper() in ("REFUNDED", "REFUND")
        raw_time = _pick(row, ("orderTime", "createTime", "createTimeStr", "date"), "")
        ordered_at = _parse_time(raw_time)
        if ordered_at is None:
            continue
        items: List[OrderItem] = []
        for it in _as_list(_pick(row, ("items", "orderItems", "productList"), []), ("items", "list")):
            items.append(
                OrderItem(
                    product_code=str(_pick(it, ("productCode", "code"), "")),
                    name=str(_pick(it, ("productName", "name"), "餐品")),
                    quantity=int(_pick(it, ("quantity", "count", "num"), 1) or 1),
                    unit_price_fen=_to_fen(_pick(it, ("price", "unitPrice", "salePrice")), amount_unit),
                )
            )
        orders.append(
            OrderRecord(
                order_id=str(_pick(row, ("orderId", "orderNo", "id"), "")),
                ordered_at=ordered_at,
                items=items,
                total_fen=_to_fen(_pick(row, ("totalAmount", "payAmount", "amount", "total")), amount_unit),
                channel=str(_pick(row, ("channel", "orderType", "beTypeName"), "")),
                refunded=refunded,
            )
        )
    return [o for o in orders if not o.refunded]


def _parse_time(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# 券面价值反查（麦麦瘦身里用于「比价」而非主目标）
# --------------------------------------------------------------------------- #

def coupon_face_value(coupon: Coupon, menu: Sequence[MenuItem]) -> int:
    """推算券面价值（单位：分）；查不到原价一律返回 0，不估算。"""
    if coupon.coupon_type == "THRESHOLD":
        return coupon.discount_fen
    if coupon.coupon_type == "DISCOUNT":
        return coupon.max_discount_fen or 0
    # 单品券 / 买一送一 / 固定价券：从菜单反查
    for code in coupon.applicable_products:
        match = next((m for m in menu if m.product_code == code), None)
        if match is not None and "买一送一" in coupon.name:
            return match.price_fen
        if match is not None:
            fixed = _fixed_price(coupon.name)
            if fixed is not None:
                return max(0, match.price_fen - fixed)
            return min(coupon.discount_fen, match.price_fen)
    return 0


def _fixed_price(name: str) -> Optional[int]:
    """从券名解析「9.9元」这类固定价（单位：分）。"""
    import re

    m = re.search(r"(\d+(?:\.\d+)?)\s*元", name)
    return int(float(m.group(1)) * 100) if m else None
