"""麦麦瘦身助手 · 基于麦当劳 MCP 的健康点餐引擎。

双链路::

    链路 A（这一餐）: advisor.recommend()   —— 营养评分 + 比价 + 一键下单
    链路 B（长期）  : auditor.audit()       —— 热量日历 + 饮食习惯画像
"""

from .models import (
    ACTIVITY_FACTORS,
    Coupon,
    HealthPlan,
    MenuItem,
    Nutrition,
    OrderRecord,
    SwapSuggestion,
    UserProfile,
    yuan,
)
from .advisor import meal_target, recommend, score, swap_suggestions
from .auditor import audit
from .body import bmi, bmi_label, bmr, daily_target, energy_targets, tdee
from .calendar_render import render_svg_calendar, render_text_calendar, save_svg
from .service import FitService

__all__ = [
    "UserProfile", "MenuItem", "Nutrition", "OrderRecord", "Coupon",
    "HealthPlan", "SwapSuggestion", "ACTIVITY_FACTORS",
    "bmi", "bmi_label", "bmr", "tdee", "daily_target", "energy_targets",
    "meal_target", "score", "recommend", "swap_suggestions",
    "audit", "render_text_calendar", "render_svg_calendar", "save_svg",
    "FitService", "yuan",
]

__version__ = "1.0.0"
