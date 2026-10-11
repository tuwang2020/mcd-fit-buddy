"""数据模型：餐品、营养、订单、身体指标、方案。

金额统一以「分」（int）存储，展示时再换算为「元」；热量统一为 kcal（float）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


def yuan(fen: int) -> str:
    """把「分」格式化为 `¥12.34` 形式。"""
    return f"¥{fen / 100:.2f}"


# --------------------------------------------------------------------------- #
# 营养
# --------------------------------------------------------------------------- #

@dataclass
class Nutrition:
    """一份餐品的营养信息（近似值，来源见 source）。"""

    calories_kcal: float
    protein_g: float = 0.0
    fat_g: float = 0.0
    carbs_g: float = 0.0
    sodium_mg: float = 0.0
    sugar_g: float = 0.0
    source: str = "公开营养标签近似值，实际以麦当劳官方公示为准"


# --------------------------------------------------------------------------- #
# 餐品 / 订单
# --------------------------------------------------------------------------- #

@dataclass
class MenuItem:
    product_code: str
    name: str
    price_fen: int
    category: str  # 主食 / 小食 / 饮料 / 甜品 / 早餐
    nutrition: Optional[Nutrition] = None

    @property
    def kcal(self) -> Optional[float]:
        return self.nutrition.calories_kcal if self.nutrition else None


@dataclass
class OrderItem:
    product_code: str
    name: str
    quantity: int
    unit_price_fen: int


@dataclass
class OrderRecord:
    order_id: str
    ordered_at: datetime
    items: List[OrderItem]
    total_fen: int
    channel: str = ""       # 到店 / 麦乐送 / 得来速
    refunded: bool = False  # 整单退款 → 审计时过滤

    @property
    def date(self) -> date:
        return self.ordered_at.date()

    @property
    def hour(self) -> int:
        return self.ordered_at.hour


# --------------------------------------------------------------------------- #
# 身体指标
# --------------------------------------------------------------------------- #

ACTIVITY_FACTORS = {
    "sedentary": 1.2,    # 久坐
    "light": 1.375,      # 轻度活动（默认办公族）
    "moderate": 1.55,    # 中度活动
    "active": 1.725,     # 高强度
}


@dataclass
class UserProfile:
    sex: str = "M"          # M / F
    age: int = 30
    height_cm: float = 172.0
    weight_kg: float = 70.0
    activity: str = "light"
    goal: str = "cut"       # cut 减脂 / keep 维持 / bulk 增肌

    @property
    def activity_factor(self) -> float:
        return ACTIVITY_FACTORS.get(self.activity, 1.375)


# --------------------------------------------------------------------------- #
# 优惠券 / 用券（沿用「价格最优」能力，服务于健康方案的比价）
# --------------------------------------------------------------------------- #

COUPON_ITEM = "ITEM"            # 单品券：对指定餐品减免固定金额
COUPON_THRESHOLD = "THRESHOLD"  # 满减券：满 threshold_fen 减 discount_fen
COUPON_DISCOUNT = "DISCOUNT"    # 折扣券：订单打 discount_rate 折（可封顶）


@dataclass
class Coupon:
    coupon_id: str
    coupon_code: str
    name: str
    coupon_type: str
    discount_fen: int = 0
    discount_rate: float = 0.0
    threshold_fen: int = 0
    applicable_products: List[str] = field(default_factory=list)
    max_discount_fen: Optional[int] = None

    def applies_to(self, product_code: str) -> bool:
        return not self.applicable_products or product_code in self.applicable_products


@dataclass
class AppliedCoupon:
    coupon: Coupon
    target_product_code: Optional[str]  # None = 订单级券
    discount_fen: int


# --------------------------------------------------------------------------- #
# 方案
# --------------------------------------------------------------------------- #

@dataclass
class ScoreBreakdown:
    """营养评分的可解释拆解（推荐必须能说清「为什么」）。"""

    kcal: float
    target_kcal: float
    kcal_penalty: float
    protein_bonus: float
    sodium_penalty: float
    sugar_penalty: float
    total: float


@dataclass
class HealthPlan:
    """一个候选「健康点餐方案」。"""

    items: List[MenuItem]
    target_kcal: float
    breakdown: Optional[ScoreBreakdown] = None
    applied: List[AppliedCoupon] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    @property
    def kcal(self) -> float:
        return sum(i.nutrition.calories_kcal for i in self.items if i.nutrition)

    @property
    def protein_g(self) -> float:
        return sum(i.nutrition.protein_g for i in self.items if i.nutrition)

    @property
    def sodium_mg(self) -> float:
        return sum(i.nutrition.sodium_mg for i in self.items if i.nutrition)

    @property
    def sugar_g(self) -> float:
        return sum(i.nutrition.sugar_g for i in self.items if i.nutrition)

    @property
    def subtotal_fen(self) -> int:
        return sum(i.price_fen for i in self.items)

    @property
    def discount_fen(self) -> int:
        return sum(a.discount_fen for a in self.applied)

    @property
    def total_fen(self) -> int:
        return max(0, self.subtotal_fen - self.discount_fen)

    @property
    def known_nutrition(self) -> bool:
        """是否所有餐品都查到了营养数据（未知热量绝不估算）。"""
        return all(i.nutrition is not None for i in self.items)


@dataclass
class SwapSuggestion:
    """替换建议：用同品类低热量餐品替换当前选择。"""

    original: MenuItem
    replacement: MenuItem
    delta_kcal: float
    note: str = ""
