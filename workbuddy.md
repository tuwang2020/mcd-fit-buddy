# workbuddy.md · WorkBuddy 开发对话上下文

> 本文件导出本项目在 **WorkBuddy** 中的开发对话上下文，用于核验是否符合本次大赛
> 「WorkBuddy 专项奖励」的联动条件。项目从创意构思、脚手架搭建、源码编写到本地调试验证，
> 均在 WorkBuddy 内完成。

---

## 1. 开发环境

- 工具：WorkBuddy（Agent 模式）
- 工作目录：`C:/mycode/mcd-dev`
- 连接器：`mcd-mcp`（麦当劳中国官方 MCP Server，Streamable HTTP）
- 日期：2026-10-12

---

## 2. 项目演进

### 阶段一 · 初版「麦麦省钱搭子」

**用户**：读取官方赛事仓库，按「开发 Skill」栏目创建参赛必需文件与源码示例。

**WorkBuddy**：抓取官方 `CONTEST_DECLARATION.md` 原文、加载 `mcd-mcp` 全部 Tool schema，
搭出「优惠券最优化引擎」版本的参赛项目（文档 + Skill + 源码 + 22 项单测）。

### 阶段二 · 方向转变为「麦麦瘦身助手」

**用户**：项目方向转变，改为「麦麦瘦身助手」——根据历史订单计算每餐热量、生成热量日历图、
构建用户画像与饮食习惯，参考膳食指南与历史习惯推荐更健康、可制造热量缺口的菜品，
并支持一键点单；思路参考 `Ayzzz123/mcd-coupon-strategist` 并在此基础上深化。

**WorkBuddy**：
1. 读取参考仓库，提炼可迁移经验：**双链路架构（单次决策 + 长期审计）、统一适配层、
   绝不编造数据、测试可离线运行**；
2. 把目标函数从「实付最低」升维为「**营养最优，其次比价**」，重构整个项目：
   - 移除旧 `mcd_saver` 包，新建 `mcd_fit` 包（营养库 / 身体指标 / 热量审计 / 热量日历 /
     健康推荐引擎 / 适配层 / 极简 MCP 客户端 / 编排层 / CLI）；
   - 新增 `order-list` 历史订单链路（热量审计 + SVG 热量日历 + 7 类习惯洞察）；
   - 保留用券最优化作为「健康方案内比价」，并明确**不为用券凑单**；
   - 编写 29 项单测（含退款过滤、未知热量不估算、BMR/安全下限、替换建议等边界）；
3. 本地验证：`python -m unittest discover -s tests` → 29 passed；
   `python -m src.mcd_fit.cli demo` → 审计报告 + 双月热量日历（SVG 已导出）+ 3 个健康方案 + 替换建议。

---

## 3. 采用的 WorkBuddy 能力

| 能力 | 本项目中的使用 |
| --- | --- |
| Agent 模式（文件读写） | 生成并写入全部参赛文件与源码，重构项目结构 |
| WebFetch / GitHub API | 读取官方赛事仓库、参考仓库 README 与文件树 |
| MCP 连接器 `mcd-mcp` | 提供门店/菜单/优惠券/价格/下单能力，并核对全部 Tool schema |
| Bash（本地验证） | 运行 29 项单元测试、离线 demo，导出热量日历 SVG |

---

## 4. 复现方式

```bash
# 1) 运行单元测试（29 项，离线可跑）
python -m unittest discover -s tests -v

# 2) 全流程演示（离线样例数据，无需 Token）
python -m src.mcd_fit.cli demo

# 3) 单独生成热量日历（导出 SVG）
python -m src.mcd_fit.cli calendar --year 2026 --month 9
```

---

_本文件由 WorkBuddy 会话上下文整理导出，供大赛组委会核验使用。_
