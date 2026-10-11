"""热量审计：从历史订单还原「你到底吃了多少」。

链路 B（长期）：``order-list`` 历史订单 → 逐单热量 → 逐日聚合 → 饮食习惯画像。
设计原则：
- **退款不算吃**：整单退款订单过滤；
- **未知热量不估算**：查不到营养的餐品单独计数，宁可少报；
- 输出的每条洞察都必须能从数据中复现。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from .nutrition_db import lookup
from .models import OrderItem, OrderRecord


@dataclass
class DailyStat:
    day: date
    kcal: Optional[float] = None      # 仅统计已知热量部分
    spend_fen: int = 0
    order_count: int = 0
    unknown_items: int = 0            # 未知热量餐品数（不计入 kcal）
    refund_count: int = 0


@dataclass
class TopItem:
    name: str
    count: int
    kcal_per_unit: Optional[float]


@dataclass
class CalorieReport:
    daily: List[DailyStat] = field(default_factory=list)
    total_orders: int = 0
    refunded_orders: int = 0
    orders_with_unknown: int = 0
    total_kcal: float = 0.0
    total_spend_fen: int = 0
    avg_meal_kcal: Optional[float] = None
    max_day: Optional[Tuple[date, float]] = None
    over_target_days: int = 0
    days_with_data: int = 0
    late_night_orders: int = 0
    weekend_avg_kcal: Optional[float] = None
    weekday_avg_kcal: Optional[float] = None
    top_items: List[TopItem] = field(default_factory=list)
    sugary_drink_orders: int = 0
    habits: List[str] = field(default_factory=list)


def order_kcal(order: OrderRecord) -> Tuple[float, int]:
    """返回 ``(已知热量 kcal, 未知热量餐品数)``。"""
    kcal = 0.0
    unknown = 0
    for item in order.items:
        nutrition = _lookup_item(item)
        if nutrition is None:
            unknown += item.quantity
            continue
        kcal += nutrition.calories_kcal * item.quantity
    return kcal, unknown


def _lookup_item(item: OrderItem):
    from .models import MenuItem  # 局部导入避免循环

    return lookup(MenuItem(item.product_code, item.name, 0, "未知"))


def audit(orders: Sequence[OrderRecord], daily_target_kcal: float) -> CalorieReport:
    """审计历史订单，生成热量与习惯报告。"""
    by_day: Dict[date, DailyStat] = {}
    item_counter: Counter = Counter()
    item_kcal: Dict[str, Optional[float]] = {}
    kcal_per_order: List[float] = []
    weekend: List[float] = []
    weekday: List[float] = []
    sugary = 0

    report = CalorieReport()
    for order in sorted(orders, key=lambda o: o.ordered_at):
        if order.refunded:  # 退款不算吃
            report.refunded_orders += 1
            stat = by_day.setdefault(order.date, DailyStat(day=order.date))
            stat.refund_count += 1
            continue
        report.total_orders += 1
        kcal, unknown = order_kcal(order)
        if unknown:
            report.orders_with_unknown += 1
        else:
            kcal_per_order.append(kcal)

        stat = by_day.setdefault(order.date, DailyStat(day=order.date))
        stat.order_count += 1
        stat.spend_fen += order.total_fen
        stat.unknown_items += unknown
        if unknown == 0:
            stat.kcal = (stat.kcal or 0.0) + kcal
            (weekend if order.date.weekday() >= 5 else weekday).append(kcal)
        if order.hour >= 21 or order.hour < 5:
            report.late_night_orders += 1

        for item in order.items:
            item_counter[item.name] += item.quantity
            nutrition = _lookup_item(item)
            item_kcal[item.name] = nutrition.calories_kcal if nutrition else None
            if nutrition and nutrition.sugar_g >= 20:
                sugary += 1

    report.daily = [by_day[d] for d in sorted(by_day)]
    report.total_kcal = round(sum(s.kcal or 0 for s in report.daily), 1)
    report.total_spend_fen = sum(s.spend_fen for s in report.daily)
    report.avg_meal_kcal = round(sum(kcal_per_order) / len(kcal_per_order), 1) if kcal_per_order else None
    report.days_with_data = sum(1 for s in report.daily if s.kcal is not None)
    report.over_target_days = sum(1 for s in report.daily if s.kcal and s.kcal > daily_target_kcal)
    if report.daily:
        day, value = max(
            ((s.day, s.kcal) for s in report.daily if s.kcal is not None),
            key=lambda kv: kv[1],
            default=(None, None),
        )
        if day is not None:
            report.max_day = (day, value)
    report.weekend_avg_kcal = round(sum(weekend) / len(weekend), 1) if weekend else None
    report.weekday_avg_kcal = round(sum(weekday) / len(weekday), 1) if weekday else None
    report.sugary_drink_orders = sugary
    report.top_items = [
        TopItem(name=n, count=c, kcal_per_unit=item_kcal.get(n)) for n, c in item_counter.most_common(5)
    ]
    report.habits = _habits(report, daily_target_kcal)
    return report


def _habits(report: CalorieReport, daily_target_kcal: float) -> List[str]:
    habits: List[str] = []
    if report.top_items:
        top = report.top_items[0]
        kcal_txt = f"，单份 {top.kcal_per_unit:.0f} kcal" if top.kcal_per_unit is not None else ""
        habits.append(f"你最常点「{top.name}」（近 {report.total_orders} 单中出现 {top.count} 次{kcal_txt}）。")
    if report.avg_meal_kcal is not None:
        habits.append(f"平均每单 {report.avg_meal_kcal:.0f} kcal。")
    if report.weekend_avg_kcal and report.weekday_avg_kcal:
        diff = report.weekend_avg_kcal - report.weekday_avg_kcal
        if diff > 100:
            habits.append(f"周末比工作日平均多吃 {diff:.0f} kcal/单，周末是主要超标来源。")
        elif diff < -100:
            habits.append(f"工作日反而比周末多吃 {-diff:.0f} kcal/单。")
    if report.late_night_orders:
        habits.append(f"有 {report.late_night_orders} 单在 21 点后下单（夜宵场景）。")
    if report.sugary_drink_orders:
        habits.append(f"含糖饮料/甜品出现 {report.sugary_drink_orders} 份——这是最容易替换掉的热量来源。")
    if report.days_with_data:
        habits.append(
            f"有数据的 {report.days_with_data} 天里，{report.over_target_days} 天超过每日目标 "
            f"{daily_target_kcal:.0f} kcal。"
        )
    if report.orders_with_unknown:
        habits.append(
            f"{report.orders_with_unknown} 单含未收录热量的餐品，其热量未计入（宁缺毋滥，不估算）。"
        )
    return habits
