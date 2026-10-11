"""麦当劳常见餐品营养参考库。

数据来源与使用原则
------------------
1. 数值为**公开营养标签的近似值**，用于估算与趋势分析；
2. 实际营养以麦当劳官方公示为准，报告中必须保留 `source` 字段声明；
3. **宁缺毋滥**：查不到热量的餐品一律返回 ``None`` 并标记为「未知热量」，
   绝不编造一个"看起来合理"的数字（沿用参考项目的设计原则）。

字段：kcal / 蛋白质 g / 脂肪 g / 碳水 g / 钠 mg / 糖 g
"""

from __future__ import annotations

from typing import Dict, Optional

from .models import MenuItem, Nutrition

# product_code -> Nutrition
NUTRITION_DB: Dict[str, Nutrition] = {
    # ---------------- 主食 ----------------
    "M001": Nutrition(550, 25, 32, 45, 1000, 9),    # 巨无霸
    "M002": Nutrition(570, 26, 33, 46, 1200, 8),    # 麦辣鸡腿堡
    "M003": Nutrition(330, 15, 13, 34, 780, 6),     # 麦香鱼
    "M004": Nutrition(430, 27, 17, 36, 950, 7),     # 板烧鸡腿堡
    "M005": Nutrition(440, 25, 23, 33, 1050, 7),    # 双层吉士汉堡
    "M006": Nutrition(300, 15, 12, 30, 720, 6),     # 吉士汉堡
    "M007": Nutrition(250, 12, 8, 31, 580, 6),      # 原味汉堡
    "M008": Nutrition(400, 19, 20, 35, 850, 6),     # 猪柳蛋麦满分
    # ---------------- 小食 ----------------
    "M101": Nutrition(350, 4, 17, 45, 210, 0),      # 中薯条
    "M102": Nutrition(220, 2, 10, 29, 140, 0),      # 小薯条
    "M103": Nutrition(490, 6, 23, 64, 290, 0),      # 大薯条
    "M104": Nutrition(230, 11, 13, 17, 450, 0),     # 麦乐鸡 5 块
    "M105": Nutrition(230, 14, 14, 9, 520, 0),      # 麦辣鸡翅 2 块
    "M106": Nutrition(150, 1, 9, 16, 290, 0),       # 脆薯饼
    "M107": Nutrition(90, 3, 1, 19, 5, 9),          # 玉米杯
    "M108": Nutrition(25, 1, 0, 5, 15, 3),          # 鲜蔬杯
    # ---------------- 饮料 ----------------
    "M201": Nutrition(180, 0, 0, 46, 10, 46),       # 可口可乐(中)
    "M202": Nutrition(0, 0, 0, 0, 15, 0),           # 零度可口可乐(中)
    "M203": Nutrition(90, 0, 0, 23, 15, 21),        # 冰鲜柠檬水(中)
    "M204": Nutrition(10, 1, 0, 1, 5, 0),           # 美式咖啡(中)
    "M205": Nutrition(155, 8, 6, 14, 90, 13),       # 拿铁(中)
    "M206": Nutrition(5, 0, 0, 1, 5, 0),            # 鲜煮咖啡(中)
    # ---------------- 甜品 ----------------
    "M301": Nutrition(280, 6, 7, 48, 120, 40),      # 草莓圣代
    "M302": Nutrition(330, 6, 11, 53, 200, 42),     # 麦旋风(奥利奥)
    "M303": Nutrition(200, 5, 6, 31, 90, 24),       # 圆筒冰淇淋
    "M304": Nutrition(230, 2, 10, 33, 120, 12),     # 苹果派
}


def _norm(name: str) -> str:
    """名称归一化：去空格、统一括号、小写。"""
    return (
        name.replace("（", "(").replace("）", ")")
        .replace(" ", "").replace("　", "")
        .lower()
    )


def lookup_by_code(code: str) -> Optional[Nutrition]:
    return NUTRITION_DB.get(code)


# 常见量词/规格词，匹配前先剔除（「中杯可口可乐」→「可口可乐」）
_SIZE_WORDS = ("中杯", "大杯", "小杯", "中份", "大份", "小份", "一份")


def lookup_by_name(name: str) -> Optional[Nutrition]:
    """按名称查找：先精确，再双向包含（订单里的名称常有别名）。"""
    target = _norm(name)
    for word in _SIZE_WORDS:
        target = target.replace(word, "")
    hit = NAME_INDEX.get(target)
    if hit is not None:
        return NUTRITION_DB[hit]
    # 双向包含（如「巨无霸汉堡」↔「巨无霸」）；短别名（<3字）不参与，避免误匹配
    for alias, code in NAME_INDEX.items():
        if len(alias) >= 3 and (alias in target or target in alias):
            return NUTRITION_DB[code]
    return None


def lookup(item: MenuItem) -> Optional[Nutrition]:
    """对 MenuItem 查营养：先 code，再名称。查不到返回 None（不估算）。"""
    return lookup_by_code(item.product_code) or lookup_by_name(item.name)


def attach_nutrition(menu_item: MenuItem) -> MenuItem:
    """若菜单项缺营养数据，尝试从库中补齐。"""
    if menu_item.nutrition is None:
        menu_item.nutrition = lookup(menu_item)
    return menu_item


def attach_to_menu(items: list) -> list:
    return [attach_nutrition(i) for i in items]


# --------------------------------------------------------------------------- #
# 名称索引（归一化后的名称 -> code），模块导入时构建
# --------------------------------------------------------------------------- #

ITEM_NAMES: Dict[str, str] = {
    "M001": "巨无霸", "M002": "麦辣鸡腿堡", "M003": "麦香鱼",
    "M004": "板烧鸡腿堡", "M005": "双层吉士汉堡", "M006": "吉士汉堡",
    "M007": "原味汉堡", "M008": "猪柳蛋麦满分",
    "M101": "中薯条", "M102": "小薯条", "M103": "大薯条",
    "M104": "麦乐鸡(5块)", "M105": "麦辣鸡翅(2块)", "M106": "脆薯饼",
    "M107": "玉米杯", "M108": "鲜蔬杯",
    "M201": "可口可乐(中)", "M202": "零度可口可乐(中)", "M203": "冰鲜柠檬水(中)",
    "M204": "美式咖啡(中)", "M205": "拿铁(中)", "M206": "鲜煮咖啡(中)",
    "M301": "草莓圣代", "M302": "麦旋风(奥利奥)", "M303": "圆筒冰淇淋",
    "M304": "苹果派",
}

NAME_INDEX: Dict[str, str] = {_norm(name): code for code, name in ITEM_NAMES.items()}
