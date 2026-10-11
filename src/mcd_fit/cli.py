"""命令行入口。

用法::

    python -m src.mcd_fit.cli demo                    # 离线全流程演示（无需 Token）
    python -m src.mcd_fit.cli report                  # 热量审计 + 饮食习惯画像
    python -m src.mcd_fit.cli calendar --year 2026 --month 9
    python -m src.mcd_fit.cli advise                  # 健康点餐推荐
    python -m src.mcd_fit.cli advise --store 1234567  # 实盘（需 MCD_MCP_TOKEN）
    python -m src.mcd_fit.cli order --store 1234567 --confirm   # 一键下单（实盘）
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import List, Optional

from . import mock_data
from .advisor import meal_target, recommend, swap_suggestions
from .auditor import audit
from .body import MEAL_SODIUM_LIMIT_MG, energy_targets
from .calendar_render import render_svg_calendar, render_text_calendar, save_svg
from .models import MenuItem, UserProfile, yuan
from .pricing import best_coupon_plan
from .service import FitService

LINE = "=" * 62
SUB = "-" * 62


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #

def render_report(title: str, report, targets) -> str:
    out = [LINE, title, SUB]
    out.append(f"有效订单 {report.total_orders} 单（另有 {report.refunded_orders} 单已退款，已过滤）")
    if report.total_spend_fen:
        out.append(f"累计支出 {yuan(report.total_spend_fen)}")
    if report.avg_meal_kcal is not None:
        out.append(
            f"平均每单 {report.avg_meal_kcal:.0f} kcal（本餐目标 {targets.meal_target_kcal:.0f} kcal）"
        )
    if report.max_day is not None:
        day, value = report.max_day
        out.append(f"最高单日：{day.isoformat()}，{value:.0f} kcal")
    out.append(f"超标天数：{report.over_target_days} / 有数据 {report.days_with_data} 天")
    if report.orders_with_unknown:
        out.append(f"含未知热量餐品的订单 {report.orders_with_unknown} 单（其热量未计入，不估算）")
    out.append(SUB)
    out.append("【饮食习惯画像】")
    for h in report.habits:
        out.append(f"  · {h}")
    out.append(LINE)
    return "\n".join(out)


def render_plan(index: int, plan, show_reasons: bool = True) -> str:
    out = [f"方案 {index}（评分 {plan.breakdown.total:.0f}）"]
    for item in plan.items:
        kcal = f"{item.kcal:.0f} kcal" if item.kcal is not None else "热量未知"
        out.append(f"  · {item.name:<16} {yuan(item.price_fen):>7}   {kcal}")
    out.append(
        f"  合计：{plan.kcal:.0f} kcal ｜ 蛋白质 {plan.protein_g:.0f} g ｜ "
        f"钠 {plan.sodium_mg:.0f} mg ｜ 实付 {yuan(plan.total_fen)}"
    )
    if show_reasons:
        for r in plan.reasons:
            out.append(f"  ▸ {r}")
    return "\n".join(out)


def typical_order(orders, menu: List[MenuItem]) -> List[MenuItem]:
    """从历史订单提炼「用户最常点的组合」，作为对比基线。"""
    by_code = {m.product_code: m for m in menu}
    counters = {"主食": Counter(), "小食": Counter(), "饮料": Counter()}
    for order in orders:
        if order.refunded:
            continue
        for item in order.items:
            ref = by_code.get(item.product_code)
            if ref is not None and ref.category in counters:
                counters[ref.category][item.product_code] += 1
    cart: List[MenuItem] = []
    for cat in ("主食", "小食", "饮料"):
        if counters[cat]:
            cart.append(by_code[counters[cat].most_common(1)[0][0]])
    return cart


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #

def _user_from_args(args: argparse.Namespace) -> UserProfile:
    return UserProfile(
        sex=args.sex, age=args.age, height_cm=args.height,
        weight_kg=args.weight, activity=args.activity, goal=args.goal,
    )


def cmd_demo(_: argparse.Namespace) -> int:
    svc = FitService.from_env()
    mode = "实盘" if svc.is_live else "离线样例"
    user = mock_data.sample_user()
    targets = energy_targets(user)
    orders = svc.get_orders()
    menu = mock_data.sample_menu() if not svc.is_live else svc.get_menu("1234567")

    print(LINE)
    print(f"麦麦瘦身助手 · 全流程演示（{mode}）")
    print(SUB)
    print(f"用户画像：{'男' if user.sex == 'M' else '女'} {user.age} 岁，"
          f"{user.height_cm:.0f}cm / {user.weight_kg:.0f}kg，活动水平 {user.activity}")
    print(f"BMR {targets.bmr_kcal:.0f} kcal ｜ TDEE {targets.tdee_kcal:.0f} kcal ｜ "
          f"每日目标 {targets.daily_target_kcal:.0f} kcal（缺口 {targets.deficit_kcal:.0f}）｜ "
          f"本餐目标 {targets.meal_target_kcal:.0f} kcal ｜ BMI {targets.bmi}（{targets.bmi_label}）")

    # 链路 B：长期审计
    report = audit(orders, targets.daily_target_kcal)
    print()
    print(render_report("【链路 B · 长期】历史订单热量审计", report, targets))

    # 热量日历
    os.makedirs("output", exist_ok=True)
    from collections import defaultdict

    by_month: dict = defaultdict(list)
    for day in report.daily:
        by_month[(day.day.year, day.day.month)].append(day)
    for (year, month), days in sorted(by_month.items()):
        target = targets.daily_target_kcal
        mini_report = type(report)(daily=days)
        text = render_text_calendar(mini_report, year, month, target)
        print()
        print(text)
        svg = render_svg_calendar(mini_report, year, month, target)
        path = save_svg(svg, f"output/calorie-calendar-{year}-{month:02d}.svg")
        print(f"（SVG 已保存：{path}）")

    # 链路 A：这一餐怎么吃
    print()
    coupons = mock_data.sample_coupons() if not svc.is_live else svc.list_store_coupons("1234567")
    plans = recommend(menu, user, coupons=coupons, top_n=3)
    print(LINE)
    print("【链路 A · 单次】这一餐怎么吃更健康（健康优先，其次比价）")
    print(SUB)
    for i, plan in enumerate(plans, 1):
        print(render_plan(i, plan))
        print(SUB)

    # 替换建议：基于用户最常点的组合
    base = typical_order(orders, menu)
    if base:
        base_kcal = sum(i.kcal or 0 for i in base)
        best_plan = plans[0]
        delta = base_kcal - best_plan.kcal
        if delta > 0:
            print(f"对比：你最常点的组合「{' + '.join(i.name for i in base)}」约 {base_kcal:.0f} kcal；"
                  f"推荐方案少 {delta:.0f} kcal（约占日目标的 {delta / targets.daily_target_kcal * 100:.1f}%）。")
        else:
            print(f"对比：你最常点的组合「{' + '.join(i.name for i in base)}」约 {base_kcal:.0f} kcal，"
                  f"已经比推荐方案还低 {-delta:.0f} kcal——保持现状即可，无需调整。")
        print()
        print("【替换建议】不改变你想吃的方向，只换更低热量的同类：")
        for s in swap_suggestions(base, menu):
            print(f"  ▸ {s.note}")
    print(LINE)
    print("⚠️ 输出为通用估算，不构成医疗建议；营养数据为公开标签近似值，以官方公示为准。")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    svc = FitService.from_env()
    user = _user_from_args(args)
    targets = energy_targets(user)
    orders = svc.get_orders()
    report = audit(orders, targets.daily_target_kcal)
    print(render_report("麦麦瘦身助手 · 热量审计报告", report, targets))
    return 0


def cmd_calendar(args: argparse.Namespace) -> int:
    svc = FitService.from_env()
    user = _user_from_args(args)
    target = args.target or energy_targets(user).daily_target_kcal
    report = audit(svc.get_orders(), target)
    print(render_text_calendar(report, args.year, args.month, target))
    os.makedirs("output", exist_ok=True)
    path = save_svg(
        render_svg_calendar(report, args.year, args.month, target),
        f"output/calorie-calendar-{args.year}-{args.month:02d}.svg",
    )
    print(f"（SVG 已保存：{path}）")
    return 0


def cmd_advise(args: argparse.Namespace) -> int:
    svc = FitService.from_env()
    user = _user_from_args(args)
    coupons = mock_data.sample_coupons()
    menu = mock_data.sample_menu()
    if svc.is_live:
        if args.auto_coupon:
            svc.auto_bind_coupons()
        menu = svc.get_menu(args.store, order_type=args.order_type, be_type=args.be_type)
        coupons = svc.list_store_coupons(args.store, order_type=args.order_type, be_type=args.be_type)
    plans = recommend(
        menu, user, coupons=coupons,
        deficit_kcal=args.deficit,
        budget_fen=int(args.budget * 100) if args.budget else None,
        top_n=args.top,
    )
    print(f"本餐热量目标：{meal_target(user, args.deficit):.0f} kcal")
    for i, plan in enumerate(plans, 1):
        print(SUB)
        print(render_plan(i, plan))
    print(LINE)
    return 0


def cmd_order(args: argparse.Namespace) -> int:
    svc = FitService.from_env()
    if not svc.is_live:
        print("实盘下单需配置 MCD_MCP_TOKEN。当前为离线模式，未执行任何下单。", file=sys.stderr)
        return 1
    if not args.confirm:
        print("⚠️ 下单需要显式确认：请追加 --confirm 重跑。", file=sys.stderr)
        return 1
    user = _user_from_args(args)
    menu = svc.get_menu(args.store, order_type=args.order_type, be_type=args.be_type)
    coupons = svc.list_store_coupons(args.store, order_type=args.order_type, be_type=args.be_type)
    plan = recommend(menu, user, coupons=coupons, top_n=1)[0]
    result = svc.calculate_price(args.store, plan, order_type=args.order_type, be_type=args.be_type)
    print("官方计价复核：", result)
    result = svc.create_order(args.store, plan, order_type=args.order_type, be_type=args.be_type)
    print("下单结果：", result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mcd-fit-buddy", description="麦麦瘦身助手 · 麦当劳 MCP 健康点餐助手")
    p.add_argument("--sex", default="M", choices=["M", "F"])
    p.add_argument("--age", type=int, default=30)
    p.add_argument("--height", type=float, default=172.0)
    p.add_argument("--weight", type=float, default=70.0)
    p.add_argument("--activity", default="light",
                   choices=["sedentary", "light", "moderate", "active"])
    p.add_argument("--goal", default="cut", choices=["cut", "keep", "bulk"])
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="离线全流程演示").set_defaults(func=cmd_demo)
    sub.add_parser("report", help="热量审计 + 画像").set_defaults(func=cmd_report)

    pc = sub.add_parser("calendar", help="热量日历")
    pc.add_argument("--year", type=int, required=True)
    pc.add_argument("--month", type=int, required=True)
    pc.add_argument("--target", type=float, default=None)
    pc.set_defaults(func=cmd_calendar)

    pa = sub.add_parser("advise", help="健康点餐推荐")
    pa.add_argument("--store", default="1234567")
    pa.add_argument("--deficit", type=float, default=400.0)
    pa.add_argument("--budget", type=float, default=None, help="预算（元）")
    pa.add_argument("--top", type=int, default=3)
    pa.add_argument("--auto-coupon", action="store_true")
    pa.add_argument("--order-type", type=int, default=1, choices=[1, 2])
    pa.add_argument("--be-type", type=int, default=1, choices=[1, 2, 5, 6])
    pa.set_defaults(func=cmd_advise)

    po = sub.add_parser("order", help="一键下单（实盘，需 --confirm）")
    po.add_argument("--store", required=True)
    po.add_argument("--confirm", action="store_true")
    po.add_argument("--order-type", type=int, default=1, choices=[1, 2])
    po.add_argument("--be-type", type=int, default=1, choices=[1, 2, 5, 6])
    po.set_defaults(func=cmd_order)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
