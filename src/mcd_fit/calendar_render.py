"""热量日历渲染：终端文本版 + SVG 图片版。

SVG 仿 GitHub contributions 风格：7 行（周一~周日）× N 列（周），
颜色档位按「当日热量 / 每日目标」划分，浅色主题。
"""

from __future__ import annotations

import calendar
import math
from datetime import date
from typing import Dict, Optional

from .auditor import CalorieReport

CELL = 14
GAP = 3
LEFT = 34
TOP = 64

# 颜色档位：(占目标比例上限, 颜色, 含义)
COLORS = [
    (0.0, "#ebedf0", "无数据"),
    (0.5, "#9be9a8", "≤50% 目标"),
    (1.0, "#40c463", "50%~100% 目标"),
    (1.2, "#f6c445", "超标 0~20%"),
    (1.5, "#f78140", "超标 20%~50%"),
    (float("inf"), "#d93a3a", "超标 50%+"),
]
TEXT_COLOR = "#1f2328"
BG_COLOR = "#ffffff"


def daily_index(report: CalorieReport) -> Dict[date, float]:
    return {s.day: s.kcal for s in report.daily if s.kcal is not None}


def _color(kcal: float, target: float) -> str:
    ratio = kcal / target if target else 0
    for limit, color, _ in COLORS:
        if ratio <= limit:
            return color
    return COLORS[-1][1]


def _fmt_kcal(kcal: float) -> str:
    return f"{kcal / 1000:.1f}k" if kcal >= 1000 else f"{kcal:.0f}"


# --------------------------------------------------------------------------- #
# 文本版
# --------------------------------------------------------------------------- #

def render_text_calendar(report: CalorieReport, year: int, month: int, target: float) -> str:
    data = daily_index(report)
    month_data = {d: v for d, v in data.items() if d.year == year and d.month == month}
    _, ndays = calendar.monthrange(year, month)
    lines = [f"{year} 年 {month} 月热量日历（目标 {target:.0f} kcal/日，* 表示超标）"]

    header = "  ".join(f"{w}" for w in ["一", "二", "三", "四", "五", "六", "日"])
    lines.append(header)
    first_weekday = date(year, month, 1).weekday()  # Mon=0
    cells: list = ["        "] * first_weekday
    for day in range(1, ndays + 1):
        d = date(year, month, day)
        if d in data:
            mark = "*" if data[d] > target else " "
            cells.append(f"{day:02d}·{_fmt_kcal(data[d]):>4}{mark}")
        else:
            cells.append(f"{day:02d}·  -  ")
    for i in range(0, len(cells), 7):
        week = cells[i:i + 7]
        week += ["        "] * (7 - len(week))
        lines.append("  ".join(week))
    over = sum(1 for v in month_data.values() if v > target)
    lines.append(f"本月有数据 {len(month_data)} 天，超标 {over} 天。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# SVG 版
# --------------------------------------------------------------------------- #

def render_svg_calendar(report: CalorieReport, year: int, month: int, target: float) -> str:
    data = daily_index(report)
    data = {d: v for d, v in data.items() if d.year == year and d.month == month}
    _, ndays = calendar.monthrange(year, month)
    first_weekday = date(year, month, 1).weekday()
    weeks = math.ceil((first_weekday + ndays) / 7)

    grid_width = LEFT + weeks * (CELL + GAP) + 24
    # 图例：chip(14) + gap(4) + 文本(10*字数) + item 间距(14)
    legend_items = [("无数据", COLORS[0][1])] + [(label, color) for _, color, label in COLORS[1:]]
    legend_width = 20 + sum(14 + 4 + 10 * len(label) + 14 for label, _ in legend_items)
    width = max(grid_width, legend_width + 24)
    height = TOP + 7 * (CELL + GAP) + 56
    over_days = sum(1 for v in data.values() if v > target)
    month_names = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="PingFang SC, Microsoft YaHei, sans-serif">',
        f"<rect width=\"{width}\" height=\"{height}\" fill=\"{BG_COLOR}\"/>",
        f'<text x="20" y="30" font-size="17" font-weight="700" fill="{TEXT_COLOR}">'
        f"{year} 年 {month_names[month - 1]} 月热量日历</text>",
        f'<text x="20" y="50" font-size="12" fill="#57606a">'
        f"每日目标 {target:.0f} kcal · 有数据 {len(data)} 天 · 超标 {over_days} 天"
        f"（数据为近似估算，以官方公示为准）</text>",
    ]

    # 星期标签
    for idx, label in enumerate(["一", "三", "五", "日"]):
        y = TOP + idx * 2 * (CELL + GAP) + CELL - 2
        parts.append(f'<text x="14" y="{y}" font-size="10" fill="#57606a">{label}</text>')

    # 日格子
    for day in range(1, ndays + 1):
        d = date(year, month, day)
        col, row = divmod(first_weekday + day - 1, 7)
        x = LEFT + col * (CELL + GAP)
        y = TOP + row * (CELL + GAP)
        kcal = data.get(d)
        color = _color(kcal, target) if kcal is not None else COLORS[0][1]
        title = f"{d.isoformat()}：{(_fmt_kcal(kcal) + ' kcal') if kcal is not None else '无数据'}"
        parts.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" fill="{color}">'
            f"<title>{title}</title></rect>"
        )

    # 图例
    ly = TOP + 7 * (CELL + GAP) + 24
    lx = 20
    for label, color in legend_items:
        parts.append(f'<rect x="{lx}" y="{ly}" width="{CELL}" height="{CELL}" rx="3" fill="{color}"/>')
        parts.append(
            f'<text x="{lx + CELL + 4}" y="{ly + 11}" font-size="10" fill="#57606a">{label}</text>'
        )
        lx += CELL + 4 + 10 * len(label) + 14
    parts.append("</svg>")
    return "\n".join(parts)


def save_svg(svg: str, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path
