"""用券与计价：服务于健康方案的「价格最优」。

设计原则（承接参考项目的经验）：
- 不为用券而凑单——只在**用户已选餐品**范围内找最优用券组合；
- 金额最终以 MCP ``calculate-price`` 返回为准，本模块给出的是**候选方案**。

算法：单品券取最优作用对象 → 枚举组合 → 每个中间态选减免最大的订单级券 → 取实付最小。
"""

from __future__ import annotations

import itertools
from typing import List, Optional, Sequence, Tuple

from .models import (
    COUPON_DISCOUNT,
    COUPON_ITEM,
    COUPON_THRESHOLD,
    AppliedCoupon,
    Coupon,
    MenuItem,
)


def _best_item_target(coupon: Coupon, items: Sequence[MenuItem]) -> Optional[Tuple[str, int]]:
    """为单品券挑选最优作用对象（减免额最大者，且不超过餐品价值）。"""
    best: Optional[Tuple[str, int]] = None
    for item in items:
        if not coupon.applies_to(item.product_code):
            continue
        discount = min(coupon.discount_fen, item.price_fen)
        if discount <= 0:
            continue
        if best is None or discount > best[1]:
            best = (item.product_code, discount)
    return best


def _best_order_coupon(coupons: Sequence[Coupon], base_fen: int) -> Optional[Tuple[Coupon, int]]:
    """在订单级券（满减/折扣）中，选出对 ``base_fen`` 减免最大的一张。"""
    best: Optional[Tuple[Coupon, int]] = None
    for c in coupons:
        if c.coupon_type == COUPON_THRESHOLD:
            if base_fen < c.threshold_fen:
                continue
            discount = min(c.discount_fen, base_fen)
        elif c.coupon_type == COUPON_DISCOUNT:
            discount = int(round(base_fen * (1 - c.discount_rate)))
            if c.max_discount_fen is not None:
                discount = min(discount, c.max_discount_fen)
            discount = min(discount, base_fen)
        else:
            continue
        if discount <= 0:
            continue
        if best is None or discount > best[1]:
            best = (c, discount)
    return best


def best_coupon_plan(
    items: Sequence[MenuItem],
    coupons: Sequence[Coupon],
    *,
    max_item_coupons: int = 3,
    max_order_coupons: int = 1,
    allow_stack: bool = True,
) -> List[AppliedCoupon]:
    """在已选餐品范围内求减免最大的用券组合。"""
    if not items or not coupons:
        return []

    item_coupons = [c for c in coupons if c.coupon_type == COUPON_ITEM]
    order_coupons = [c for c in coupons if c.coupon_type in (COUPON_THRESHOLD, COUPON_DISCOUNT)]
    subtotal = sum(i.price_fen for i in items)

    item_actions: List[Tuple[Coupon, str, int]] = []
    for c in item_coupons:
        target = _best_item_target(c, items)
        if target is not None:
            item_actions.append((c, target[0], target[1]))

    best_applied: List[AppliedCoupon] = []
    best_pay = subtotal

    max_k = min(max_item_coupons, len(item_actions))
    for k in range(0, max_k + 1):
        for combo in itertools.combinations(item_actions, k):
            applied: List[AppliedCoupon] = [
                AppliedCoupon(coupon=c, target_product_code=code, discount_fen=d)
                for (c, code, d) in combo
            ]
            after_items = subtotal - sum(a.discount_fen for a in applied)
            if order_coupons and max_order_coupons > 0 and (allow_stack or not applied):
                pick = _best_order_coupon(order_coupons, after_items)
                if pick is not None:
                    c, d = pick
                    applied.append(AppliedCoupon(coupon=c, target_product_code=None, discount_fen=d))
            pay = max(0, subtotal - sum(a.discount_fen for a in applied))
            if pay < best_pay:
                best_pay = pay
                best_applied = applied
    return best_applied
