"""★ 健康推荐引擎（项目核心算法）。

与「省钱助手」的本质区别：目标函数从「实付最低」换成「**营养最优，其次比价**」。

推荐逻辑全部**可解释**：
- 每个候选方案都有 :class:`ScoreBreakdown` 拆解（热量贴近度 / 蛋白质加分 / 钠与糖扣分）；
- 输出附带「为什么推荐」与「比你常点的组合少多少 kcal」的归因；
- 查不到营养数据的餐品**直接不参与**推荐（绝不估算）。
"""

from __future__ import annotations

import itertools
from typing import Dict, List, Optional, Sequence

from .body import MEAL_SODIUM_LIMIT_MG, MEAL_SUGAR_LIMIT_G, energy_targets
from .models import (
    Coupon,
    HealthPlan,
    MenuItem,
    ScoreBreakdown,
    SwapSuggestion,
    UserProfile,
    yuan,
)
from .pricing import best_coupon_plan

# 组合规则：1 主食 + 0~2 小食 + 0~1 饮料 + 0~1 甜品
COMBO_RULES = {"主食": (1, 1), "小食": (0, 2), "饮料": (0, 1), "甜品": (0, 1)}

# 评分权重（透明可调，不是黑盒）
W_KCAL = 0.6      # 每偏离 1 kcal 扣 0.6 分
W_PROTEIN = 2.0   # 每 1g 蛋白质加 2 分
W_SODIUM = 0.05   # 每超 1mg 钠扣 0.05 分
W_SUGAR = 1.5     # 每超 1g 糖扣 1.5 分


def meal_target(profile: UserProfile, deficit_kcal: float = 400.0) -> float:
    """本餐热量目标 = 每日目标 / 3。"""
    return energy_targets(profile, deficit_kcal).meal_target_kcal


def score(items: Sequence[MenuItem], target_kcal: float) -> Optional[ScoreBreakdown]:
    """营养评分；任一餐品营养未知则返回 None（不估算）。"""
    if not items or not all(i.nutrition is not None for i in items):
        return None
    kcal = sum(i.nutrition.calories_kcal for i in items)
    protein = sum(i.nutrition.protein_g for i in items)
    sodium = sum(i.nutrition.sodium_mg for i in items)
    sugar = sum(i.nutrition.sugar_g for i in items)

    kcal_penalty = -abs(kcal - target_kcal) * W_KCAL
    protein_bonus = protein * W_PROTEIN
    sodium_penalty = -max(0.0, sodium - MEAL_SODIUM_LIMIT_MG) * W_SODIUM
    sugar_penalty = -max(0.0, sugar - MEAL_SUGAR_LIMIT_G) * W_SUGAR
    return ScoreBreakdown(
        kcal=kcal,
        target_kcal=target_kcal,
        kcal_penalty=round(kcal_penalty, 1),
        protein_bonus=round(protein_bonus, 1),
        sodium_penalty=round(sodium_penalty, 1),
        sugar_penalty=round(sugar_penalty, 1),
        total=round(kcal_penalty + protein_bonus + sodium_penalty + sugar_penalty, 1),
    )


def _by_category(menu: Sequence[MenuItem]) -> Dict[str, List[MenuItem]]:
    buckets: Dict[str, List[MenuItem]] = {}
    for item in menu:
        if item.nutrition is None:  # 营养未知 → 不参与推荐
            continue
        buckets.setdefault(item.category, []).append(item)
    return buckets


def enumerate_combos(menu: Sequence[MenuItem], combo_limit: int = 4000) -> List[List[MenuItem]]:
    """按 COMBO_RULES 枚举候选组合；营养未知的餐品不参与。"""
    buckets = _by_category(menu)
    if not buckets.get("主食"):
        return []

    pools: List[List[List[MenuItem]]] = []
    for cat, (lo, hi) in COMBO_RULES.items():
        candidates = buckets.get(cat, [])
        if hi == 0 or not candidates:
            if lo > 0:
                return []  # 缺必需品类，无法成单
            pools.append([[]])
            continue
        options: List[List[MenuItem]] = []
        for k in range(lo, hi + 1):
            options.extend([list(c) for c in itertools.combinations(candidates, k)])
        pools.append(options)

    combos: List[List[MenuItem]] = []
    for parts in itertools.product(*pools):
        flat = [i for part in parts for i in part]
        combos.append(flat)
        if len(combos) >= combo_limit:
            break
    return combos


def recommend(
    menu: Sequence[MenuItem],
    profile: UserProfile,
    *,
    deficit_kcal: float = 400.0,
    coupons: Optional[Sequence[Coupon]] = None,
    budget_fen: Optional[int] = None,
    top_n: int = 3,
) -> List[HealthPlan]:
    """返回 top_n 个健康方案：营养评分优先，同分比价。"""
    target = meal_target(profile, deficit_kcal)
    scored: List[tuple] = []
    for items in enumerate_combos(menu):
        bd = score(items, target)
        if bd is None:
            continue
        budget_ok = budget_fen is None or sum(i.price_fen for i in items) <= budget_fen
        # 超预算的方案降权（而非直接丢弃，便于说明「差多少」）
        ranked = (bd.total + (8 if budget_ok else -40), bd, items, budget_ok)
        scored.append(ranked)

    scored.sort(key=lambda r: r[0], reverse=True)

    plans: List[HealthPlan] = []
    for _, bd, items, budget_ok in scored[: top_n * 3]:
        applied = best_coupon_plan(items, list(coupons or []))
        plan = HealthPlan(items=items, target_kcal=target, breakdown=bd, applied=applied)
        plan.reasons = _reasons(plan, budget_ok, budget_fen)
        if all(p.items != plan.items for p in plans):
            plans.append(plan)
        if len(plans) >= top_n:
            break
    return plans


def _reasons(plan: HealthPlan, budget_ok: bool, budget_fen: Optional[int]) -> List[str]:
    bd = plan.breakdown
    reasons: List[str] = []
    delta = bd.kcal - bd.target_kcal
    if abs(delta) <= bd.target_kcal * 0.10:
        reasons.append(f"热量 {bd.kcal:.0f} kcal，贴合本餐目标 {bd.target_kcal:.0f} kcal。")
    elif delta < 0:
        reasons.append(
            f"热量 {bd.kcal:.0f} kcal，低于目标 {bd.target_kcal:.0f} kcal（富余 {-delta:.0f} kcal），"
            f"适合搭配其他正餐。"
        )
    else:
        reasons.append(f"热量 {bd.kcal:.0f} kcal，超出目标 {delta:.0f} kcal，仅建议偶尔。")

    protein_ratio = (plan.protein_g * 4 / bd.kcal) if bd.kcal else 0.0
    reasons.append(f"蛋白质 {plan.protein_g:.0f} g（供能比 {protein_ratio * 100:.0f}%），饱腹感更强。")

    if plan.sodium_mg > MEAL_SODIUM_LIMIT_MG:
        reasons.append(f"钠 {plan.sodium_mg:.0f} mg，超过单餐参考上限 {MEAL_SODIUM_LIMIT_MG} mg，建议当日清淡。")
    if plan.sugar_g > MEAL_SUGAR_LIMIT_G:
        reasons.append(f"糖 {plan.sugar_g:.0f} g，超过单餐参考上限 {MEAL_SUGAR_LIMIT_G} g。")

    if plan.discount_fen > 0:
        reasons.append(
            f"已比价：用「{'、'.join(a.coupon.name for a in plan.applied)}」，"
            f"{yuan(plan.subtotal_fen)} → {yuan(plan.total_fen)}。"
        )
    else:
        reasons.append(f"实付 {yuan(plan.total_fen)}。")
    if not budget_ok and budget_fen is not None:
        reasons.append(f"超出预算 {yuan(budget_fen)}（超出 {yuan(plan.total_fen - budget_fen)}）。")
    return reasons


# --------------------------------------------------------------------------- #
# 替换建议：不改变「想吃什么」的方向，只换更低热量的同类
# --------------------------------------------------------------------------- #

def swap_suggestions(cart: Sequence[MenuItem], menu: Sequence[MenuItem], min_delta: float = 80.0) -> List[SwapSuggestion]:
    """对购物车里每件高热量餐品，找同品类低热量替代。

    只在替代能省 ≥ ``min_delta`` kcal 时才提，避免无意义的「换了个寂寞」。
    """
    result: List[SwapSuggestion] = []
    menu_by_cat: Dict[str, List[MenuItem]] = _by_category(menu)
    for item in cart:
        if item.nutrition is None:
            continue
        best: Optional[MenuItem] = None
        for cand in menu_by_cat.get(item.category, []):
            if cand.product_code == item.product_code or cand.nutrition is None:
                continue
            if best is None or cand.nutrition.calories_kcal < best.nutrition.calories_kcal:
                best = cand
        if best is None:
            continue
        delta = best.nutrition.calories_kcal - item.nutrition.calories_kcal
        if delta <= -min_delta:
            note = f"{item.name} → {best.name}，本餐少 {abs(delta):.0f} kcal"
            if item.category == "饮料" and best.nutrition.sugar_g < item.nutrition.sugar_g:
                note += f"，少 {item.nutrition.sugar_g - best.nutrition.sugar_g:.0f} g 糖"
            result.append(SwapSuggestion(original=item, replacement=best, delta_kcal=delta, note=note))
    return result
