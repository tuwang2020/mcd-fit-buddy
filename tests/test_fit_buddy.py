"""麦麦瘦身助手单元测试。

运行：``python -m unittest discover -s tests -v``（纯本地，无需 MCP Token）
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcd_fit import mock_data  # noqa: E402
from src.mcd_fit.adapter import coupon_face_value, to_orders  # noqa: E402
from src.mcd_fit.advisor import meal_target, recommend, score, swap_suggestions  # noqa: E402
from src.mcd_fit.auditor import audit, order_kcal  # noqa: E402
from src.mcd_fit.body import bmi_label, daily_target, energy_targets  # noqa: E402
from src.mcd_fit.calendar_render import render_svg_calendar, render_text_calendar  # noqa: E402
from src.mcd_fit.mcp_client import McpClient  # noqa: E402
from src.mcd_fit.models import Coupon, MenuItem, OrderItem, OrderRecord, UserProfile  # noqa: E402
from src.mcd_fit.nutrition_db import lookup_by_code, lookup_by_name  # noqa: E402
from src.mcd_fit.pricing import best_coupon_plan  # noqa: E402


# --------------------------------------------------------------------------- #

class TestBody(unittest.TestCase):
    def test_mifflin_st_jeor_male(self):
        user = UserProfile(sex="M", age=29, height_cm=173.0, weight_kg=76.0, activity="light")
        targets = energy_targets(user)
        self.assertAlmostEqual(targets.bmr_kcal, 1701.3, delta=0.5)
        self.assertAlmostEqual(targets.tdee_kcal, 2339.2, delta=1.0)
        self.assertAlmostEqual(targets.daily_target_kcal, 1939.2, delta=1.0)
        self.assertAlmostEqual(targets.meal_target_kcal, 646.4, delta=0.5)

    def test_safety_floor(self):
        user = UserProfile(sex="F", age=25, height_cm=160.0, weight_kg=50.0, activity="sedentary")
        # TDEE 很低时，目标不得低于女性安全下限 1200
        self.assertGreaterEqual(daily_target(user, deficit_kcal=2000), 1200)

    def test_bmi_label(self):
        self.assertEqual(bmi_label(22.0), "正常")
        self.assertEqual(bmi_label(25.0), "超重")
        self.assertEqual(bmi_label(29.0), "肥胖")


class TestNutritionDb(unittest.TestCase):
    def test_lookup_by_code(self):
        self.assertEqual(lookup_by_code("M001").calories_kcal, 550)

    def test_lookup_by_name_alias(self):
        # 订单里的名称常有别名，需双向包含匹配
        self.assertIsNotNone(lookup_by_name("巨无霸汉堡"))
        self.assertIsNotNone(lookup_by_name("中杯可口可乐"))

    def test_unknown_returns_none(self):
        self.assertIsNone(lookup_by_name("安格斯厚牛培根堡"))
        self.assertIsNone(lookup_by_code("AX001"))


class TestPricing(unittest.TestCase):
    def test_best_coupon_plan_combines_item_and_discount(self):
        menu = {m.product_code: m for m in mock_data.sample_menu()}
        items = [menu["M004"], menu["M206"]]  # 2450 + 950 = 3400 分
        coupons = mock_data.sample_coupons()
        applied = best_coupon_plan(items, coupons)
        # 最优：板烧-400 + 咖啡-300 + 8.8折(2700*12%=324) = 1024 分
        self.assertEqual(sum(a.discount_fen for a in applied), 1024)

    def test_no_coupons(self):
        menu = {m.product_code: m for m in mock_data.sample_menu()}
        self.assertEqual(best_coupon_plan([menu["M001"]], []), [])

    def test_threshold_not_met_ignored(self):
        menu = {m.product_code: m for m in mock_data.sample_menu()}
        coupons = [Coupon("C1", "T50", "满50减12", "THRESHOLD", threshold_fen=5000, discount_fen=1200)]
        applied = best_coupon_plan([menu["M007"]], coupons)  # 1050 分，远不达门槛
        self.assertEqual(applied, [])


class TestAuditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orders = mock_data.sample_orders()
        cls.user = mock_data.sample_user()
        cls.targets = energy_targets(cls.user)
        cls.report = audit(cls.orders, cls.targets.daily_target_kcal)

    def test_refunds_filtered(self):
        refunded = sum(1 for o in self.orders if o.refunded)
        self.assertGreater(refunded, 0)
        self.assertEqual(self.report.refunded_orders, refunded)
        self.assertEqual(self.report.total_orders, len(self.orders) - refunded)

    def test_unknown_heat_not_estimated(self):
        # 样例数据含 2 笔带「安格斯厚牛培根堡」的订单 → 必须标记，而不是估算
        self.assertGreaterEqual(self.report.orders_with_unknown, 2)

    def test_daily_aggregation_consistent(self):
        known_orders = [o for o in self.orders if not o.refunded and order_kcal(o)[1] == 0]
        expected = round(sum(order_kcal(o)[0] for o in known_orders), 1)
        self.assertAlmostEqual(self.report.total_kcal, expected, delta=1.0)

    def test_late_night_detected(self):
        self.assertGreaterEqual(self.report.late_night_orders, 1)

    def test_habits_generated(self):
        self.assertTrue(self.report.habits)

    def test_over_target_days(self):
        self.assertGreaterEqual(self.report.days_with_data, 1)
        self.assertGreaterEqual(self.report.over_target_days, 0)


class TestAdvisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.menu = mock_data.sample_menu()
        cls.user = mock_data.sample_user()

    def test_score_none_for_unknown_nutrition(self):
        bad = [MenuItem("X", "神秘餐品", 1000, "主食", None)]
        self.assertIsNone(score(bad, 600))

    def test_recommend_returns_plans_near_target(self):
        plans = recommend(self.menu, self.user, coupons=mock_data.sample_coupons(), top_n=3)
        self.assertEqual(len(plans), 3)
        target = meal_target(self.user)
        for plan in plans:
            self.assertTrue(plan.known_nutrition)
            self.assertEqual(sum(1 for i in plan.items if i.category == "主食"), 1)
            self.assertLessEqual(plan.kcal, target * 1.25)

    def test_recommend_reasons_exist(self):
        plan = recommend(self.menu, self.user, top_n=1)[0]
        self.assertTrue(plan.reasons)

    def test_coupon_applied_to_healthy_plan(self):
        plans = recommend(self.menu, self.user, coupons=mock_data.sample_coupons(), top_n=5)
        self.assertTrue(any(p.discount_fen > 0 for p in plans))

    def test_swap_suggestions(self):
        menu = {m.product_code: m for m in self.menu}
        cart = [menu["M002"], menu["M103"], menu["M201"]]  # 麦辣堡 + 大薯条 + 可乐
        swaps = swap_suggestions(cart, self.menu)
        targets = {s.original.product_code for s in swaps}
        self.assertEqual(targets, {"M002", "M103", "M201"})
        for s in swaps:
            self.assertLess(s.delta_kcal, -80)

    def test_swap_no_suggestion_for_already_healthy(self):
        menu = {m.product_code: m for m in self.menu}
        cart = [menu["M108"]]  # 鲜蔬杯已是最低热量
        self.assertEqual(swap_suggestions(cart, self.menu), [])


class TestAdapter(unittest.TestCase):
    def test_to_orders_filters_refunds(self):
        raw = {"orders": [
            {"orderId": "A1", "orderTime": "2026-09-07 12:30", "totalAmount": 3400,
             "items": [{"productCode": "M004", "productName": "板烧鸡腿堡", "quantity": 1, "price": 2450}]},
            {"orderId": "A2", "orderTime": "2026-09-07 19:00", "totalAmount": 5700,
             "orderStatus": "REFUNDED",
             "items": [{"productCode": "M001", "productName": "巨无霸", "quantity": 1, "price": 2550}]},
        ]}
        orders = to_orders(raw)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].order_id, "A1")
        self.assertEqual(orders[0].total_fen, 3400)
        self.assertEqual(orders[0].items[0].unit_price_fen, 2450)

    def test_coupon_face_value_bogo(self):
        menu = mock_data.sample_menu()
        coupon = Coupon("C", "BOGO", "零度可乐买一送一", "ITEM", discount_fen=950,
                        applicable_products=["M202"])
        self.assertEqual(coupon_face_value(coupon, menu), 950)  # 等于商品单价

    def test_coupon_face_value_fixed_price(self):
        menu = mock_data.sample_menu()
        coupon = Coupon("C", "FIX", "9.9元巨无霸", "ITEM", discount_fen=0,
                        applicable_products=["M001"])
        # 25.50 - 9.90 = 15.60 元
        self.assertEqual(coupon_face_value(coupon, menu), 1560)

    def test_coupon_face_value_unknown_is_zero(self):
        coupon = Coupon("C", "X", "神秘券", "ITEM", discount_fen=500, applicable_products=["AX001"])
        self.assertEqual(coupon_face_value(coupon, mock_data.sample_menu()), 0)


class TestCalendar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orders = mock_data.sample_orders()
        cls.targets = energy_targets(mock_data.sample_user())
        cls.report = audit(cls.orders, cls.targets.daily_target_kcal)

    def test_text_calendar_has_header_and_footer(self):
        text = render_text_calendar(self.report, 2026, 9, self.targets.daily_target_kcal)
        self.assertIn("2026 年 9 月热量日历", text)
        self.assertIn("超标", text)
        self.assertIn("*", text)

    def test_svg_structure(self):
        svg = render_svg_calendar(self.report, 2026, 9, self.targets.daily_target_kcal)
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("<rect", svg)
        self.assertIn("</svg>", svg)


class TestMcpParsing(unittest.TestCase):
    def test_parse_plain_json(self):
        parsed = McpClient._parse('{"jsonrpc":"2.0","id":1,"result":{"ok":true}}', "application/json")
        self.assertTrue(parsed["result"]["ok"])

    def test_parse_sse(self):
        raw = 'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"value":42}}\n\n'
        parsed = McpClient._parse(raw, "text/event-stream")
        self.assertEqual(parsed["result"]["value"], 42)


if __name__ == "__main__":
    unittest.main(verbosity=2)
