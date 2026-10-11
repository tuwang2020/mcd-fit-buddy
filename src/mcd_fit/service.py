"""编排层：MCP 官方能力 ↔ 本地健康算法。

- 有 Token → 实盘（真实菜单 / 历史订单 / 可用券 / 下单）；
- 无 Token → 自动降级到离线样例，保证 demo 与单测可复现；
- 营养数据：优先用 MCP 返回的官方营养字段，缺失则查本地参考库，都没有则标记未知。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from . import mock_data
from .adapter import to_menu, to_orders
from .mcp_client import McpClient
from .models import Coupon, MenuItem, OrderRecord, UserProfile
from .nutrition_db import attach_nutrition

DEFAULT_MCP_URL = "https://mcp.mcd.cn"


class FitService:
    def __init__(self, client: Optional[McpClient] = None) -> None:
        self.client = client

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls, token: Optional[str] = None, url: str = DEFAULT_MCP_URL) -> "FitService":
        token = token or os.environ.get("MCD_MCP_TOKEN", "")
        if not token:
            return cls(client=None)
        client = McpClient(url=url, token=token)
        client.initialize()
        return cls(client=client)

    @property
    def is_live(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------------ #
    # MCP 封装
    # ------------------------------------------------------------------ #
    def find_stores(self, city: str, keyword: str, be_type: int = 1) -> List[Dict[str, Any]]:
        if not self.client:
            return [dict(mock_data.SAMPLE_STORE)]
        args = {"searchType": 2, "city": city, "keyword": keyword, "beType": be_type}
        return _listify(self.client.call_tool("query-nearby-stores", args),
                        ("stores", "storeList", "list", "data"))

    def get_menu(self, store_code: str, order_type: int = 1, be_type: int = 1,
                 be_code: Optional[str] = None) -> List[MenuItem]:
        if not self.client:
            return mock_data.sample_menu()
        args: Dict[str, Any] = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
        if be_type in (2, 5, 6) and be_code:
            args["beCode"] = be_code
        raw = self.client.call_tool("query-meals", args)
        return to_menu(raw)

    def get_orders(self) -> List[OrderRecord]:
        """拉取历史订单（含退款过滤与单位换算，见 adapter）。"""
        if not self.client:
            return mock_data.sample_orders()
        return to_orders(self.client.call_tool("order-list", {}))

    def auto_bind_coupons(self) -> Any:
        if not self.client:
            return {"offline": True}
        return self.client.call_tool("auto-bind-coupons", {})

    def list_store_coupons(self, store_code: str, order_type: int = 1, be_type: int = 1,
                           be_code: Optional[str] = None) -> List[Coupon]:
        if not self.client:
            return mock_data.sample_coupons()
        args: Dict[str, Any] = {"storeCode": store_code, "orderType": order_type, "beType": be_type}
        if be_type in (2, 5, 6) and be_code:
            args["beCode"] = be_code
        raw = self.client.call_tool("query-store-coupons", args)
        from .adapter import _as_list  # 复用列表抽取

        rows = _as_list(raw, ("coupons", "couponList", "list", "data"))
        coupons: List[Coupon] = []
        for row in rows:
            coupons.append(
                Coupon(
                    coupon_id=str(_first(row, ("couponId", "id"), "")),
                    coupon_code=str(_first(row, ("couponCode", "code"), "")),
                    name=str(_first(row, ("couponName", "name", "title"), "优惠券")),
                    coupon_type=str(_first(row, ("couponType", "type"), "ITEM")).upper(),
                    discount_fen=int(_first(row, ("discount", "discountFen", "amount"), 0) or 0),
                    discount_rate=float(_first(row, ("discountRate", "rate"), 0.0) or 0.0),
                    threshold_fen=int(_first(row, ("threshold", "thresholdFen", "minAmount"), 0) or 0),
                    applicable_products=[
                        p if isinstance(p, str) else str(_first(p, ("productCode", "code"), ""))
                        for p in (_first(row, ("productCodes", "applicableProducts", "products"), []) or [])
                    ],
                )
            )
        return coupons

    def calculate_price(self, store_code: str, plan, order_type: int = 1, be_type: int = 1,
                        be_code: Optional[str] = None) -> Any:
        """用官方口径复核方案价格。"""
        if not self.client:
            return {"offline": True, "totalFen": plan.total_fen}
        coupon_of = {a.target_product_code: a.coupon for a in plan.applied if a.target_product_code}
        order_coupon = next((a.coupon for a in plan.applied if a.target_product_code is None), None)
        items = []
        for it in plan.items:
            entry: Dict[str, Any] = {"productCode": it.product_code, "quantity": 1}
            c = coupon_of.get(it.product_code) or order_coupon
            if c is not None:
                entry["couponId"], entry["couponCode"] = c.coupon_id, c.coupon_code
            items.append(entry)
        args: Dict[str, Any] = {"storeCode": store_code, "orderType": order_type,
                                "beType": be_type, "items": items}
        if be_type in (2, 5, 6) and be_code:
            args["beCode"] = be_code
        return self.client.call_tool("calculate-price", args)

    def create_order(self, store_code: str, plan, *, take_way_code: Optional[str] = None,
                     order_type: int = 1, be_type: int = 1, be_code: Optional[str] = None) -> Any:
        """一键下单：**必须由用户显式确认后调用**。"""
        if not self.client:
            return {"offline": True, "hint": "实盘下单需配置 MCD_MCP_TOKEN 并连接 mcd-mcp"}
        coupon_of = {a.target_product_code: a.coupon for a in plan.applied if a.target_product_code}
        order_coupon = next((a.coupon for a in plan.applied if a.target_product_code is None), None)
        items = []
        for it in plan.items:
            entry: Dict[str, Any] = {"productCode": it.product_code, "quantity": 1}
            c = coupon_of.get(it.product_code) or order_coupon
            if c is not None:
                entry["couponId"], entry["couponCode"] = c.coupon_id, c.coupon_code
            items.append(entry)
        args: Dict[str, Any] = {"storeCode": store_code, "orderType": order_type,
                                "beType": be_type, "items": items}
        if be_type in (2, 5, 6) and be_code:
            args["beCode"] = be_code
        if order_type == 1 and take_way_code:
            args["takeWayCode"] = take_way_code
        return self.client.call_tool("create-order", args)


def _first(d: Any, keys: Sequence[str], default: Any = None) -> Any:
    if isinstance(d, dict):
        for k in keys:
            if d.get(k) not in (None, ""):
                return d[k]
    return default


def _listify(result: Any, keys: Sequence[str]) -> List[Dict[str, Any]]:
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        for k in keys:
            v = result.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        data = result.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []
