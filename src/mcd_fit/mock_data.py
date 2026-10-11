"""离线样例数据：菜单、券、用户画像、5 周历史订单。

订单为**确定性生成**（固定随机种子），保证 demo 与单测结果可复现；
其中故意包含：1 笔整单退款、2 笔含未知热量餐品的订单，用于验证过滤与「宁缺毋滥」逻辑。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List

from .models import Coupon, MenuItem, OrderItem, OrderRecord, UserProfile
from .nutrition_db import NUTRITION_DB, ITEM_NAMES

# ---------------- 菜单 ---------------- #

PRICES_FEN = {
    "M001": 2550, "M002": 2350, "M003": 1950, "M004": 2450,
    "M005": 1950, "M006": 1350, "M007": 1050, "M008": 1350,
    "M101": 1400, "M102": 1050, "M103": 1750, "M104": 1250,
    "M105": 1250, "M106": 750, "M107": 900, "M108": 750,
    "M201": 950, "M202": 950, "M203": 1050, "M204": 1150,
    "M205": 1650, "M206": 950,
    "M301": 1100, "M302": 1200, "M303": 650, "M304": 900,
}

CATEGORY = {
    **{c: "主食" for c in ("M001", "M002", "M003", "M004", "M005", "M006", "M007")},
    "M008": "早餐",
    **{c: "小食" for c in ("M101", "M102", "M103", "M104", "M105", "M106", "M107", "M108")},
    **{c: "饮料" for c in ("M201", "M202", "M203", "M204", "M205", "M206")},
    **{c: "甜品" for c in ("M301", "M302", "M303", "M304")},
}

MAIN_CODES = ["M001", "M002", "M003", "M004", "M005", "M006", "M007"]
SIDE_CODES = ["M101", "M102", "M103", "M104", "M105", "M106", "M107", "M108"]
DRINK_CODES = ["M201", "M202", "M203", "M204", "M205", "M206"]
DESSERT_CODES = ["M301", "M302", "M303", "M304"]


def sample_menu() -> List[MenuItem]:
    menu: List[MenuItem] = []
    for code, name in ITEM_NAMES.items():
        menu.append(
            MenuItem(
                product_code=code,
                name=name,
                price_fen=PRICES_FEN[code],
                category=CATEGORY[code],
                nutrition=NUTRITION_DB[code],
            )
        )
    return menu


# ---------------- 用户画像 ---------------- #

def sample_user() -> UserProfile:
    return UserProfile(sex="M", age=29, height_cm=173.0, weight_kg=76.0, activity="light", goal="cut")


# ---------------- 优惠券 ---------------- #

def sample_coupons() -> List[Coupon]:
    return [
        Coupon("C001", "TH50_12", "满 50 减 12", "THRESHOLD", threshold_fen=5000, discount_fen=1200),
        Coupon("C002", "TH35_6", "满 35 减 6", "THRESHOLD", threshold_fen=3500, discount_fen=600),
        Coupon("C003", "IT_GB4", "板烧鸡腿堡立减 4 元", "ITEM", discount_fen=400, applicable_products=["M004"]),
        Coupon("C004", "IT_CF3", "鲜煮咖啡立减 3 元", "ITEM", discount_fen=300, applicable_products=["M206"]),
        Coupon("C005", "DC88", "全场 8.8 折（最高减 15 元）", "DISCOUNT", discount_rate=0.88, max_discount_fen=1500),
    ]


# ---------------- 历史订单（确定性生成） ---------------- #

SAMPLE_STORE = {"storeCode": "1234567", "storeName": "人民广场餐厅", "beType": 1, "orderType": 1}


def sample_orders(start: str = "2026-09-07", end: str = "2026-10-11") -> List[OrderRecord]:
    """生成 2026-09-07 ~ 2026-10-11（5 周）的确定性历史订单。"""
    rng = random.Random(7)
    menu = {i.product_code: i for i in sample_menu()}
    orders: List[OrderRecord] = []
    seq = 0

    day = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while day <= end_dt:
        weekday = day.weekday()
        is_weekend = weekday >= 5
        order_times: List[int] = []
        if rng.random() < (0.88 if is_weekend else 0.72):
            order_times.append(rng.choice([11, 12, 12, 13, 18, 19] if is_weekend else [12, 12, 13, 19]))
        if is_weekend and rng.random() < 0.25:
            order_times.append(rng.choice([21, 22]))           # 周末夜宵
        if rng.random() < 0.10:
            order_times.append(10)                              # 工作日早午餐

        for hour in order_times:
            seq += 1
            items: List[OrderItem] = []
            if hour >= 21:  # 夜宵：小食 + 甜品为主
                chosen = rng.sample(SIDE_CODES, k=rng.randint(1, 2)) + [rng.choice(DESSERT_CODES)]
            else:
                chosen = [rng.choice(MAIN_CODES if hour >= 11 else ["M008"])]
                n_sides = rng.randint(0, 2)
                side_pool = SIDE_CODES + (["M103"] if is_weekend else [])
                chosen += rng.sample(side_pool, k=min(n_sides, len(side_pool)))
                if rng.random() < 0.85:
                    drink_pool = DRINK_CODES + (["M304"] if is_weekend and rng.random() < 0.4 else [])
                    chosen.append(rng.choice(drink_pool))
                if rng.random() < 0.15:
                    chosen.append(rng.choice(DESSERT_CODES))

            for code in chosen:
                item = menu[code]
                items.append(OrderItem(item.product_code, item.name, 1, item.price_fen))

            total = sum(i.unit_price_fen * i.quantity for i in items)
            orders.append(
                OrderRecord(
                    order_id=f"ORD{seq:04d}",
                    ordered_at=day.replace(hour=hour, minute=rng.choice([0, 7, 15, 30, 42])),
                    items=items,
                    total_fen=total,
                    channel=rng.choice(["到店", "麦乐送"]),
                )
            )

        # 两笔含「库中无热量」餐品的订单（验证不估算逻辑）
        if day.strftime("%Y-%m-%d") in ("2026-09-16", "2026-10-06"):
            orders[-1].items.append(OrderItem("AX001", "安格斯厚牛培根堡", 1, 3650))
            orders[-1].total_fen += 3650
        # 一笔整单退款（2026-09-13）
        if day.strftime("%Y-%m-%d") == "2026-09-13":
            seq += 1
            refund = OrderRecord(
                order_id=f"ORD{seq:04d}",
                ordered_at=day.replace(hour=12, minute=20),
                items=[OrderItem("M002", "麦辣鸡腿堡", 1, menu["M002"].price_fen)],
                total_fen=menu["M002"].price_fen,
                channel="麦乐送",
                refunded=True,
            )
            orders.append(refund)
        day += timedelta(days=1)

    return orders
