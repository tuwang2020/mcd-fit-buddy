"""构建演示页数据：复用项目自身的算法模块，输出 demo/data.js。

数据来源
--------
1. 历史订单 / 热量审计 / 习惯画像 / 热量日历 —— `src.mcd_fit` 真实计算结果（离线样例订单，确定性可复现）；
2. 门店 / 菜单 / 优惠券 —— 2026-10-21 09:44 通过麦当劳官方 MCP（mcp.mcd.cn）实时拉取的快照；
3. 营养数据 —— 仅对「与本项目营养库同款」的餐品做精确匹配，其余标记「未知」，绝不估算。

运行：``python demo/build_demo_data.py``
"""

from __future__ import annotations

import calendar
import json
import os
import sys
from datetime import date
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcd_fit.advisor import swap_suggestions  # noqa: E402
from src.mcd_fit.advisor import recommend  # noqa: E402
from src.mcd_fit.auditor import audit, order_kcal  # noqa: E402
from src.mcd_fit.body import energy_targets  # noqa: E402
from src.mcd_fit.models import Coupon, MenuItem, Nutrition  # noqa: E402
from src.mcd_fit.nutrition_db import NUTRITION_DB  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "demo", "data.js")

# --------------------------------------------------------------------------- #
# 1. MCP 实时快照（2026-10-21 09:44:10，mcp.mcd.cn，到店自取 beType=1）
# --------------------------------------------------------------------------- #

MCP_META = {
    "server": "mcp.mcd.cn",
    "transport": "Streamable HTTP",
    "fetchedAt": "2026-10-21 09:44:10",
    "orderType": 1,
    "beType": 1,
    "beTypeLabel": "到店自取",
}

STORES = [
    {"storeCode": "1450713", "storeName": "麦当劳上海黄浦华旭国际大厦餐厅",
     "address": "南京东路街道西藏中路336号", "distance": 144,
     "businessStartTime": "00:00", "businessEndTime": "23:59", "reservation": True},
    {"storeCode": "1450441", "storeName": "麦当劳上海福州路餐厅",
     "address": "福州路666号", "distance": 235,
     "businessStartTime": "06:30", "businessEndTime": "23:00", "reservation": True},
    {"storeCode": "1450056", "storeName": "麦当劳上海食品一店餐厅",
     "address": "南京东路720号", "distance": 355,
     "businessStartTime": "06:30", "businessEndTime": "23:00", "reservation": True},
    {"storeCode": "1450195", "storeName": "麦当劳上海雅居乐餐厅",
     "address": "西藏中路525号", "distance": 382,
     "businessStartTime": "06:00", "businessEndTime": "23:00", "reservation": True},
    {"storeCode": "1450124", "storeName": "麦当劳上海南京西路NX258餐厅",
     "address": "南京西路258号1幢一层", "distance": 412,
     "businessStartTime": "07:00", "businessEndTime": "23:00", "reservation": True},
]

# 门店 1450713 的菜单实拍快照（价格单位：分；图片来自 menu-img.mcd.cn）
# nutrition_code: 与本项目营养库精确同款的餐品编码；None = 本地未收录，标记「未知」
MENU_SNAPSHOT = [
    {"code": "5022", "name": "猪柳蛋麦满分", "price_fen": 1800, "category": "主食",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/20250709/product/MS_5022_320.png",
     "nutrition_code": "M008", "tags": ["人气产品"]},
    {"code": "4825", "name": "脆薯饼", "price_fen": 850, "category": "小食",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/20250506/product/MS_4825_320_1745825068180.png",
     "nutrition_code": "M106", "tags": ["小食"]},
    {"code": "4437", "name": "玉米杯", "price_fen": 1300, "category": "小食",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G4437_320.png",
     "nutrition_code": "M107", "tags": ["小食"]},
    {"code": "520689", "name": "鲜萃咖啡", "price_fen": 950, "category": "饮料",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/20250324/product/MS_G520688_320.gif",
     "nutrition_code": "M206", "tags": ["热饮", "鲜萃咖啡"]},
    {"code": "507411", "name": "麦咖啡™美式", "price_fen": 1190, "category": "饮料",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/20260422/product/MS_G507374_320.gif",
     "nutrition_code": "M204", "tags": ["限定特惠"]},
    {"code": "507368", "name": "麦咖啡™热美式中杯", "price_fen": 1190, "category": "饮料",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/20250521/product/MS_507368_320.png",
     "nutrition_code": "M204", "tags": ["热饮"]},
    {"code": "9900008751", "name": "可乐", "price_fen": 950, "category": "饮料",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_9900008751_320.gif",
     "nutrition_code": "M201", "tags": ["冷饮"], "size_note": "按中杯匹配营养库"},
    {"code": "515837", "name": "圆筒冰淇淋", "price_fen": 500, "category": "甜品",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_G515837_320.png",
     "nutrition_code": "M303", "tags": ["冰淇淋", "第二份半价"]},
    # ---- 以下为本地营养库未收录的餐品：展示「未知热量」处理方式 ----
    {"code": "6800", "name": "原味板烧鸡腿麦满分", "price_fen": 1500, "category": "主食",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_6800_320.png",
     "nutrition_code": None, "tags": ["单品"]},
    {"code": "5889", "name": "大脆鸡扒麦满分", "price_fen": 1100, "category": "主食",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_5889_320.png",
     "nutrition_code": None, "tags": ["单品"]},
    {"code": "2631", "name": "脆香油条", "price_fen": 850, "category": "小食",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/ProductPool/product/MS_2631_320.png",
     "nutrition_code": None, "tags": ["小食"]},
    {"code": "3755", "name": "纯牛奶(盒装)", "price_fen": 1050, "category": "饮料",
     "image": "https://menu-img.mcd.cn/pcm/prod/menu/20240731/product/MS_3755_320.png",
     "nutrition_code": None, "tags": ["冷饮"]},
]

# 真实返回的可用券（query-store-coupons，2026-10-21 09:44:51）
REAL_COUPONS = [
    {"title": "新人专享-中杯美式7折", "couponId": "365A627ABDC435D840984F03055DF097",
     "couponCode": "MCD607CM100041009JQ35",
     "valid": "2026-10-12 ~ 2026-11-10", "productName": "美式中杯", "productCode": "9900000119"},
    {"title": "新人专享-中杯奶铁7折", "couponId": "54573C230294E24F154414A1EE2949CD",
     "couponCode": "MCD6300960510QJ0M10C0",
     "valid": "2026-10-12 ~ 2026-11-10", "productName": "奶铁中杯", "productCode": "9900000117"},
]

# 官方计价复核（calculate-price 真实返回，items = 方案 1：5022 + 4825 + 4437 + 507411）
PRICE_CHECK = {
    "originalPrice": 5850,      # 官方原价（未计促销）
    "officialDiscount": 710,    # 官方促销优惠（冰美式中杯 19.0 → 11.9）
    "price": 5140,              # 官方实付
    "fetchedAt": "2026-10-21 09:46:44",
    "traceId": "376faf33842f724a69866ba28d08f4b2",
    "products": [
        {"productName": "猪柳蛋麦满分", "originalSubtotal": 1800, "subtotal": 1800},
        {"productName": "脆薯饼", "originalSubtotal": 850, "subtotal": 850},
        {"productName": "小杯玉米杯", "originalSubtotal": 1300, "subtotal": 1300},
        {"productName": "麦咖啡™冰美式中杯", "originalSubtotal": 1900, "subtotal": 1190},
    ],
    "takeWayList": [
        {"code": "eat-in", "title": "堂食", "subtitle": "店内用餐"},
        {"code": "locker-out", "title": "外带", "subtitle": "店外取餐柜"},
    ],
}

# 演示用券（模拟）：真实券面不适配本单餐品，故用项目内的演示券展示比价逻辑
DEMO_COUPONS = [
    Coupon("D1", "TH35_6", "满 35 减 6", "THRESHOLD", threshold_fen=3500, discount_fen=600),
    Coupon("D2", "IT_CF3", "鲜萃咖啡立减 3 元", "ITEM", discount_fen=300, applicable_products=["520689"]),
    Coupon("D3", "TH50_12", "满 50 减 12", "THRESHOLD", threshold_fen=5000, discount_fen=1200),
]


# --------------------------------------------------------------------------- #
# 2. 构建菜单
# --------------------------------------------------------------------------- #

def build_menu() -> List[MenuItem]:
    menu: List[MenuItem] = []
    for row in MENU_SNAPSHOT:
        nutrition: Optional[Nutrition] = None
        if row["nutrition_code"]:
            base = NUTRITION_DB[row["nutrition_code"]]
            nutrition = Nutrition(
                calories_kcal=base.calories_kcal,
                protein_g=base.protein_g,
                fat_g=base.fat_g,
                carbs_g=base.carbs_g,
                sodium_mg=base.sodium_mg,
                sugar_g=base.sugar_g,
                source=f"本地营养库 {row['nutrition_code']}（公开营养标签近似值）",
            )
        menu.append(MenuItem(row["code"], row["name"], row["price_fen"], row["category"], nutrition))
    return menu


def menu_payload(menu: List[MenuItem]) -> List[dict]:
    by_code = {m.product_code: m for m in menu}
    out = []
    for row in MENU_SNAPSHOT:
        item = by_code[row["code"]]
        n = item.nutrition
        out.append({
            "code": item.product_code,
            "name": item.name,
            "priceFen": item.price_fen,
            "category": item.category,
            "image": row["image"],
            "tags": row.get("tags", []),
            "sizeNote": row.get("size_note"),
            "known": n is not None,
            "kcal": n.calories_kcal if n else None,
            "protein": n.protein_g if n else None,
            "sodium": n.sodium_mg if n else None,
            "sugar": n.sugar_g if n else None,
            "source": n.source if n else None,
        })
    return out


# --------------------------------------------------------------------------- #
# 3. 热量日历
# --------------------------------------------------------------------------- #

LEVELS = [(0.5, 1), (1.0, 2), (1.2, 3), (1.5, 4), (float("inf"), 5)]


def level_of(kcal: Optional[float], target: float) -> int:
    if kcal is None:
        return 0
    ratio = kcal / target if target else 0
    for limit, level in LEVELS:
        if ratio <= limit:
            return level
    return 5


def month_payload(report, year: int, month: int, target: float) -> dict:
    data = {s.day: s.kcal for s in report.daily if s.kcal is not None}
    _, ndays = calendar.monthrange(year, month)
    first_weekday = date(year, month, 1).weekday()  # Mon=0
    cells = []
    for day in range(1, ndays + 1):
        d = date(year, month, day)
        kcal = data.get(d)
        col, row = divmod(first_weekday + day - 1, 7)
        cells.append({
            "day": day, "col": col, "row": row,
            "kcal": round(kcal) if kcal is not None else None,
            "level": level_of(kcal, target),
            "over": bool(kcal is not None and kcal > target),
        })
    days = [c for c in cells if c["kcal"] is not None]
    return {
        "year": year, "month": month, "weeks": (first_weekday + ndays + 6) // 7,
        "firstWeekday": first_weekday, "cells": cells,
        "stats": {
            "daysWithData": len(days),
            "overDays": sum(1 for c in days if c["over"]),
            "avgKcal": round(sum(c["kcal"] for c in days) / len(days)) if days else 0,
        },
    }


# --------------------------------------------------------------------------- #
# 4. 组装
# --------------------------------------------------------------------------- #

def pick_tiers(plans):
    """从引擎候选中挑三档：最贴合目标 / 最省钱 / 最低热量（均来自同一份真实候选）。"""
    if not plans:
        return []
    tiers = [(plans[0], "最贴合目标")]
    head = plans[:6]
    cheap = min((p for p in head if len(p.items) >= 3), key=lambda p: p.total_fen, default=None)
    if cheap is not None and cheap.items != tiers[0][0].items:
        tiers.append((cheap, "最省钱"))
    light = min((p for p in plans[:8] if len(p.items) >= 3), key=lambda p: p.kcal, default=None)
    if light is not None and all(light.items != p.items for p, _ in tiers):
        tiers.append((light, "最低热量"))
    for p in plans:
        if len(tiers) >= 3:
            break
        if all(p.items != q.items for q, _ in tiers):
            tiers.append((p, "其他候选"))
    return tiers[:3]


def main() -> int:
    from src.mcd_fit import mock_data

    user = mock_data.sample_user()
    targets = energy_targets(user)
    orders = mock_data.sample_orders()
    report = audit(orders, targets.daily_target_kcal)

    menu = build_menu()
    candidates = recommend(menu, user, coupons=DEMO_COUPONS, top_n=8)
    tiers = pick_tiers(candidates)

    plan_payload = []
    for idx, (plan, label) in enumerate(tiers, 1):
        bd = plan.breakdown
        plan_payload.append({
            "index": idx,
            "label": label,
            "score": round(bd.total, 1),
            "kcal": round(plan.kcal),
            "protein": round(plan.protein_g),
            "sodium": round(plan.sodium_mg),
            "sugar": round(plan.sugar_g, 1),
            "subtotalFen": plan.subtotal_fen,
            "discountFen": plan.discount_fen,
            "totalFen": plan.total_fen,
            "targetKcal": round(bd.target_kcal),
            "items": [
                {"code": i.product_code, "name": i.name, "priceFen": i.price_fen,
                 "kcal": round(i.kcal) if i.kcal is not None else None}
                for i in plan.items
            ],
            "breakdown": {
                "kcalPenalty": bd.kcal_penalty,
                "proteinBonus": bd.protein_bonus,
                "sodiumPenalty": bd.sodium_penalty,
                "sugarPenalty": bd.sugar_penalty,
            },
            "reasons": plan.reasons,
            "coupons": [a.coupon.name for a in plan.applied],
        })

    # 全部候选（供前端按用户改动后的新目标实时重排）
    def _item(i):
        n = i.nutrition
        return {
            "code": i.product_code, "name": i.name, "priceFen": i.price_fen,
            "kcal": n.calories_kcal if n else None,
            "protein": n.protein_g if n else None,
            "sodium": n.sodium_mg if n else None,
            "sugar": n.sugar_g if n else None,
        }

    candidate_payload = [
        {
            "items": [_item(i) for i in p.items],
            "kcal": round(p.kcal), "protein": round(p.protein_g),
            "sodium": round(p.sodium_mg), "sugar": round(p.sugar_g, 1),
            "subtotalFen": p.subtotal_fen, "discountFen": p.discount_fen,
            "totalFen": p.total_fen,
            "coupons": [a.coupon.name for a in p.applied],
        }
        for p in candidates
    ]

    # 替换建议：以「可乐」为起点，展示同类低热量替换
    cola = next(m for m in menu if m.product_code == "9900008751")
    swaps = swap_suggestions([cola], menu)

    # 最近订单（用于演示列表）
    recent = []
    for order in sorted([o for o in orders if not o.refunded], key=lambda o: o.ordered_at, reverse=True)[:8]:
        kcal, unknown = order_kcal(order)
        recent.append({
            "id": order.order_id,
            "time": order.ordered_at.strftime("%m-%d %H:%M"),
            "channel": order.channel,
            "totalFen": order.total_fen,
            "kcal": round(kcal) if unknown == 0 else None,
            "unknown": unknown,
            "items": [{"name": i.name, "qty": i.quantity, "priceFen": i.unit_price_fen} for i in order.items],
        })

    payload = {
        "meta": {
            **MCP_META,
            "generatedAt": "2026-10-21 10:05",
            "scenario": "工作日上午 9:44 · 上海人民广场附近",
            "note": "门店、菜单、价格、可用券为 MCP 实时快照；用券与下单为演示模拟，不会产生真实订单。",
        },
        "user": {
            "sex": user.sex, "sexLabel": "男", "age": user.age,
            "heightCm": user.height_cm, "weightKg": user.weight_kg,
            "activity": user.activity, "activityLabel": "轻度活动（办公族）",
            "goal": user.goal, "goalLabel": "减脂",
        },
        "targets": {
            "bmr": round(targets.bmr_kcal),
            "tdee": round(targets.tdee_kcal),
            "daily": round(targets.daily_target_kcal),
            "meal": round(targets.meal_target_kcal),
            "bmi": targets.bmi,
            "bmiLabel": targets.bmi_label,
            "deficit": round(targets.deficit_kcal),
        },
        "report": {
            "totalOrders": report.total_orders,
            "refundedOrders": report.refunded_orders,
            "ordersWithUnknown": report.orders_with_unknown,
            "totalSpendFen": report.total_spend_fen,
            "avgMealKcal": round(report.avg_meal_kcal) if report.avg_meal_kcal else None,
            "maxDay": ({"date": report.max_day[0].isoformat(), "kcal": round(report.max_day[1])}
                       if report.max_day else None),
            "overTargetDays": report.over_target_days,
            "daysWithData": report.days_with_data,
            "lateNightOrders": report.late_night_orders,
            "weekdayAvg": round(report.weekday_avg_kcal) if report.weekday_avg_kcal else None,
            "weekendAvg": round(report.weekend_avg_kcal) if report.weekend_avg_kcal else None,
            "sugaryOrders": report.sugary_drink_orders,
            "habits": report.habits,
            "topItems": [{"name": t.name, "count": t.count,
                          "kcal": round(t.kcal_per_unit) if t.kcal_per_unit else None}
                         for t in report.top_items],
        },
        "calendar": {
            "2026-09": month_payload(report, 2026, 9, targets.daily_target_kcal),
            "2026-10": month_payload(report, 2026, 10, targets.daily_target_kcal),
        },
        "stores": STORES,
        "menu": menu_payload(menu),
        "plans": plan_payload,
        "candidates": candidate_payload,
        "coupons": {
            "real": REAL_COUPONS,
            "demo": [{"name": c.name, "type": c.coupon_type, "discountFen": c.discount_fen,
                      "thresholdFen": c.threshold_fen} for c in DEMO_COUPONS],
        },
        "swap": ([{"note": s.note, "from": s.original.name, "to": s.replacement.name,
                   "deltaKcal": round(s.delta_kcal)} for s in swaps] or []),
        "priceCheck": PRICE_CHECK,
        "recentOrders": recent,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// 由 demo/build_demo_data.py 生成，请勿手改。\n")
        fh.write("window.MCD_DEMO = ")
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write(";\n")

    print(f"已生成 {OUT}")
    print(f"方案数 {len(plan_payload)} / 菜单 {len(payload['menu'])} 项 / 订单 {len(recent)} 条")
    for p in plan_payload:
        print(f"  方案{p['index']} 评分 {p['score']:>5}  {p['kcal']} kcal  "
              f"实付 ¥{p['totalFen'] / 100:.2f}  " + " + ".join(i["name"] for i in p["items"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
