"""身体指标与热量目标计算。

参考依据
--------
- BMR 采用 **Mifflin-St Jeor** 公式（营养学界公认较准的估算公式之一）；
- 每日目标 = TDEE − 热量缺口（减脂默认 400 kcal，属温和缺口）；
- 参考《中国居民膳食指南（2022）》：轻身体活动成人每日能量需要量约
  男 2150~2400 kcal、女 1700~2100 kcal；钠 < 2000 mg（约 5 g 盐）；
  添加糖 < 50 g（最好 < 25 g）。

⚠️ 本模块输出仅为通用估算，不构成医疗建议；孕产妇、慢病人群请遵医嘱。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .models import UserProfile

# 每日安全下限（低于此值不建议再制造缺口）
SAFE_FLOOR_KCAL = {"F": 1200, "M": 1500}

# 每餐钠上限（每日 2000mg 的 1/3，取整）
MEAL_SODIUM_LIMIT_MG = 700
# 每餐添加糖上限（每日 50g 的 1/3）
MEAL_SUGAR_LIMIT_G = 17


@dataclass
class EnergyTargets:
    bmr_kcal: float
    tdee_kcal: float
    daily_target_kcal: float
    meal_target_kcal: float
    bmi: float
    bmi_label: str
    deficit_kcal: float


def bmi(profile: UserProfile) -> float:
    h = profile.height_cm / 100.0
    return profile.weight_kg / (h * h)


def bmi_label(value: float) -> str:
    """中国成人 BMI 标准（WS/T 428-2013）。"""
    if value < 18.5:
        return "偏瘦"
    if value < 24.0:
        return "正常"
    if value < 28.0:
        return "超重"
    return "肥胖"


def bmr(profile: UserProfile) -> float:
    """Mifflin-St Jeor 基础代谢率。"""
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    return base + (5 if profile.sex.upper() == "M" else -161)


def tdee(profile: UserProfile) -> float:
    return bmr(profile) * profile.activity_factor


def daily_target(profile: UserProfile, deficit_kcal: float = 400.0) -> float:
    """每日摄入目标，带安全下限保护。"""
    if profile.goal == "keep":
        deficit = 0.0
    elif profile.goal == "bulk":
        deficit = -200.0
    else:
        deficit = max(0.0, deficit_kcal)
    raw = tdee(profile) - deficit
    floor = SAFE_FLOOR_KCAL.get(profile.sex.upper(), 1500)
    return max(raw, floor)


def energy_targets(profile: UserProfile, deficit_kcal: float = 400.0) -> EnergyTargets:
    daily = daily_target(profile, deficit_kcal)
    value = bmi(profile)
    applied_deficit = 0.0 if profile.goal != "cut" else max(0.0, deficit_kcal)
    return EnergyTargets(
        bmr_kcal=round(bmr(profile), 1),
        tdee_kcal=round(tdee(profile), 1),
        daily_target_kcal=round(daily, 1),
        meal_target_kcal=round(daily / 3, 1),
        bmi=round(value, 1),
        bmi_label=bmi_label(value),
        deficit_kcal=applied_deficit,
    )


# 膳食指南参考常量（用于审计与推荐）
GUIDELINES: Dict[str, float] = {
    "sodium_mg_daily": 2000,
    "added_sugar_g_daily": 50,
    "protein_energy_ratio_low": 0.10,
    "protein_energy_ratio_high": 0.20,
}
