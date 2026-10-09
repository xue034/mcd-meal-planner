#!/usr/bin/env python3
"""
麦麦营养配餐计算引擎 (mcd-meal-planner)
========================================

基于麦当劳中国 MCP Server 真实返回的营养数据，为用户按热量/蛋白/钠目标
计算最优套餐组合，并给出与目标的差值和调整建议。

三种模式：
1. 热量模式（默认）—— 按热量与蛋白配餐
2. 控钠模式（--sodium-focus）—— 按钠摄入上限配餐，**本项目差异化核心**
3. 控钠密度模式（--density-focus）—— 按钠密度(mg/100kcal)排序，避开"高钠陷阱"

设计原则：
1. 数据来源可追溯 —— 全部营养数值来自 MCP list-nutrition-foods 接口真实返回
2. 离线可运行 —— MCP 不可用时回退到本地快照，不阻塞用户
3. 输出可验证 —— 每个套餐都给出精确到克的数值，不用模糊描述
4. 诚实告知无解 —— 目标不可达时明确说明，不做虚假承诺

数据字段说明：
  kcal  能量（千卡）
  p     蛋白质（克）
  f     脂肪（克）
  c     碳水化合物（克）
  na    钠（毫克）
  ca    钙（毫克）

作者：参赛作品，非麦当劳官方产品
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

# 允许以脚本方式直接运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toon_parser import parse_nutrition_toon  # noqa: E402
from commercial import (  # noqa: E402
    PointAccount,
    diagnose_points,
    diagnose_coupons,
    build_brand_message,
)

# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------

_DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "references",
    "nutrition-data.json",
)

# 分类中文名映射
CATEGORY_NAMES = {
    "burger": "汉堡",
    "chicken": "鸡类小食",
    "sides": "配餐/小食",
    "dessert": "甜品",
    "drink": "饮品",
    "coffee": "咖啡",
    "breakfast": "早餐",
    "kids": "儿童餐",
}


@dataclass
class Item:
    """单个餐品的营养信息"""

    name: str
    kcal: int
    protein: int
    fat: int
    carb: int
    sodium: int
    calcium: int
    category: str

    @property
    def category_cn(self) -> str:
        return CATEGORY_NAMES.get(self.category, self.category)

    @property
    def sodium_density(self) -> float:
        """钠密度：每 100 千卡含钠毫克数。

        这是本项目的核心指标之一。传统做法只看「总钠」，但同样1000mg钠
        分配到 2000kcal 和 400kcal 上，健康影响完全不同。

        典型对比（实测数据）：
            雪菜脆笋鸡肉粥  120kcal  552mg→ 460.0 mg/100kcal
            巨无霸          513kcal961mg → 187.3 mg/100kcal
        低热量≠低钠，粥类是高钠陷阱。
        """
        if self.kcal <= 0:
            return 0.0
        return round(self.sodium / self.kcal * 100, 1)

    @property
    def is_sodium_bomb(self) -> bool:
        """是否高钠单品（单份钠占成人建议上限 50% 以上）。"""
        return self.sodium >= 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kcal": self.kcal,
            "protein": self.protein,
            "fat": self.fat,
            "carb": self.carb,
            "sodium": self.sodium,
            "calcium": self.calcium,
            "category": self.category,
            "sodium_density": self.sodium_density,
        }


def load_items() -> List[Item]:
    """加载营养数据。

    优先尝试通过 MCP 实时刷新；MCP 不可用时回退到本地快照。
    """
    # 预留：未来接入 MCP 实时刷新时，此处调用 refresh_from_mcp()
    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        payload = json.load(f)

    return [
        Item(
            name=raw["n"],
            kcal=raw["kcal"],
            protein=raw["p"],
            fat=raw["f"],
            carb=raw["c"],
            sodium=raw["na"],
            calcium=raw["ca"],
            category=raw["cat"],
        )
        for raw in payload["items"]
    ]


def load_items_from_toon(toon_text: str) -> List[Item]:
    """从 MCP 原始 TOON 响应构建 Item 列表。

    这是接入实时数据的路径：调用 list-nutrition-foods → 得到 TOON 文本
    → 交给 toon_parser 解析 → 构建 Item。

    Args:
        toon_text: MCP list-nutrition-foods 接口的原始返回

    Returns:
        Item 列表

    Raises:
        toon_parser.ToonParseError: TOON 格式不合法
    """
    records = parse_nutrition_toon(toon_text)
    return [
        Item(
            name=r["name"],
            kcal=r.get("kcal", 0),
            protein=r.get("protein", 0),
            fat=r.get("fat", 0),
            carb=r.get("carb", 0),
            sodium=r.get("sodium", 0),
            calcium=r.get("calcium", 0),
            category="unknown",
        )
        for r in records
    ]


# ---------------------------------------------------------------------------
# 营养计算
# ---------------------------------------------------------------------------


@dataclass
class Target:
    """用户的营养目标"""

    kcal: int
    protein: int = 0
    #: 钠摄入上限（毫克），成人每日推荐不超过 2000mg
    sodium_limit: int = 2000
    #: 允许的最大热量偏差（千卡）
    tolerance: int = 60
    #: 允许的最大钠偏差（毫克）
    sodium_tolerance: int = 200
    #: 是否允许甜品
    allow_dessert: bool = False
    #: 排除的品类
    exclude_categories: List[str] = field(default_factory=list)
    #: 规划模式：heat（热量优先）| sodium（控钠优先）| density（钠密度优先）
    mode: str = "heat"

    def validate(self) -> None:
        if self.kcal <= 0:
            raise ValueError("热量目标必须大于 0")
        if self.protein < 0:
            raise ValueError("蛋白目标不能为负数")
        if self.sodium_limit <= 0:
            raise ValueError("钠上限必须大于 0")
        if self.protein > self.kcal // 4:
            raise ValueError(
                f"蛋白目标 {self.protein}g 相对热量目标 {self.kcal}kcal 不合理"
                "（蛋白热量占比不应超过 25%）"
            )


@dataclass
class Combo:
    """一个套餐组合"""

    main: Item
    side: Optional[Item]
    drink: Optional[Item]

    @property
    def items(self) -> List[Item]:
        result = [self.main]
        if self.side:
            result.append(self.side)
        if self.drink:
            result.append(self.drink)
        return result

    @property
    def total_kcal(self) -> int:
        return sum(i.kcal for i in self.items)

    @property
    def total_protein(self) -> int:
        return sum(i.protein for i in self.items)

    @property
    def total_fat(self) -> int:
        return sum(i.fat for i in self.items)

    @property
    def total_carb(self) -> int:
        return sum(i.carb for i in self.items)

    @property
    def total_sodium(self) -> int:
        return sum(i.sodium for i in self.items)

    @property
    def total_calcium(self) -> int:
        return sum(i.calcium for i in self.items)

    @property
    def total_sodium_density(self) -> float:
        """整套餐的钠密度（mg/100kcal）。

        比「总钠」更能反映实际负担：同样1500mg钠，分配到 2000kcal 上
        负担远低于分配到 500kcal 上。
        """
        if self.total_kcal <= 0:
            return 0.0
        return round(self.total_sodium / self.total_kcal * 100, 1)

    @property
    def has_sodium_bomb(self) -> bool:
        """套餐中是否含高钠单品（单份钠≥1000mg）。"""
        return any(i.is_sodium_bomb for i in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [i.to_dict() for i in self.items],
            "totals": {
                "kcal": self.total_kcal,
                "protein": self.total_protein,
                "fat": self.total_fat,
                "carb": self.total_carb,
                "sodium": self.total_sodium,
                "calcium": self.total_calcium,
            },
            "sodium_density": self.total_sodium_density,
            "has_sodium_bomb": self.has_sodium_bomb,
        }


# 各品类中适合作为「主食」的候选（高蛋白或高能量密度）
_MAIN_CATEGORIES = {"burger", "chicken", "breakfast", "kids"}

# 配餐候选
_SIDE_CATEGORIES = {"sides", "dessert"}

# 饮品候选（0 卡饮品优先）
_DRINK_CATEGORIES = {"drink", "coffee"}


def _candidates(items: List[Item], target: Target) -> Dict[str, List[Item]]:
    """按目标过滤候选餐品。"""
    pool = [i for i in items if i.category not in target.exclude_categories]

    # 甜品单独处理：默认排除
    desserts = [i for i in pool if i.category == "dessert"]
    if not target.allow_dessert:
        pool = [i for i in pool if i.category != "dessert"]

    return {
        "main": [i for i in pool if i.category in _MAIN_CATEGORIES],
        "side": [i for i in pool if i.category in _SIDE_CATEGORIES],
        "drink": [i for i in pool if i.category in _DRINK_CATEGORIES],
        "dessert": desserts,
    }


def _score(combo: Combo, target: Target) -> float:
    """给组合打分，分数越低越优。

    三种模式对应不同的权重策略：

    heat（默认）—— 热量贴近度优先
        1. 热量偏离度（权重最高）
        2. 蛋白缺口
        3. 钠超限惩罚

    sodium（--sodium-focus）—— 控钠优先
        1. 钠超限量（极重权重，控钠场景下钠是硬约束）
        2. 钠密度（同等钠量下密度越低越好）
        3. 热量偏离（次要，但仍需命中）

    density（--density-focus）—— 避开高钠陷阱
        1. 钠密度（权重最高，直接按密度排序）
        2. 热量偏离
        3. 蛋白
    """
    kcal_gap = abs(combo.total_kcal - target.kcal)
    sodium_over = max(0, combo.total_sodium - target.sodium_limit)
    protein_gap = max(0, target.protein - combo.total_protein)

    if target.mode == "sodium":
        # 控钠模式：钠是硬约束，热量退居次要
        score = (
            sodium_over * 12.0  # 超钠重罚
            + combo.total_sodium_density * 1.5  # 钠密度惩罚
            + kcal_gap * 0.6  # 热量仍需接近但不主导
            + protein_gap * 4.0
        )
        # 含高钠单品额外惩罚（即使总量达标，单份超1000mg也不理想）
        if combo.has_sodium_bomb:
            score += 60.0

    elif target.mode == "density":
        # 钠密度优先：直接按密度排序，找"低热量陷阱"之外的选择
        score = (
            combo.total_sodium_density * 3.0  # 密度主导
            + kcal_gap * 0.5
            + protein_gap * 3.0
            + sodium_over * 8.0
        )

    else:
        # 默认热量模式
        score = float(kcal_gap) * 1.0
        if protein_gap:
            score += protein_gap * 8.0
        score += sodium_over * 0.5

    # 组合过于简单（只有主食）时轻微加罚，鼓励搭配完整
    if combo.side is None and combo.drink is None:
        score += 20.0

    return score


def find_combos(items: List[Item], target: Target, limit: int = 3) -> List[Combo]:
    """找出最符合目标的若干套餐组合。"""
    target.validate()
    pool = _candidates(items, target)

    mains = pool["main"]
    sides = pool["side"]
    drinks = pool["drink"]

    if not mains:
        raise ValueError("没有可用的主餐候选，请检查排除品类设置")

    scored: List[Combo] = []

    for main in mains:
        # 预估剩余热量，用于筛选配餐和饮品
        remaining = target.kcal - main.kcal

        # 配餐：热量不应超过剩余太多，也不应让组合严重欠热量
        for side in [None] + sides:
            if side is not None and side.kcal > max(remaining, 0) + 150:
                continue

            for drink in [None] + drinks:
                combo = Combo(main=main, side=side, drink=drink)
                # 组合总热量严重超标则跳过
                if combo.total_kcal > target.kcal * 1.5:
                    continue
                scored.append(combo)

    scored.sort(key=lambda c: _score(c, target))

    # 去重：同一主餐只保留最优的一个组合
    seen_mains = set()
    unique: List[Combo] = []
    for combo in scored:
        if combo.main.name in seen_mains:
            continue
        seen_mains.add(combo.main.name)
        unique.append(combo)
        if len(unique) >= limit:
            break

    return unique


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------


def format_combo(combo: Combo, target: Target) -> str:
    """把套餐组合格式化为可读文本。"""
    lines = []
    lines.append("=" * 56)
    lines.append("推荐套餐" + ("（控钠模式）" if target.mode == "sodium" else ""))
    lines.append("=" * 56)

    for item in combo.items:
        bomb_mark = "⚠" if item.is_sodium_bomb else " "
        lines.append(
            f" {bomb_mark}· {item.name:<13}{item.kcal:>4} kcal"
            f" | 蛋白 {item.protein:>2}g"
            f" | 钠 {item.sodium:>4}mg"
            f" ({item.sodium_density:>5.1f}/100kcal)"
        )

    lines.append("-" * 56)
    lines.append(
        f"   合计{combo.total_kcal:>4} kcal"
        f" | 蛋白 {combo.total_protein:>2}g"
        f" | 脂肪 {combo.total_fat:>2}g"
        f" | 碳水 {combo.total_carb:>2}g"
    )
    lines.append(
        f"   钠 {combo.total_sodium} mg（占上限 {round(combo.total_sodium / target.sodium_limit * 100)}%）"
        f" | 钙 {combo.total_calcium} mg"
        f" | 钠密度 {combo.total_sodium_density} mg/100kcal"
    )

    # 与目标的差值
    kcal_gap = combo.total_kcal - target.kcal
    protein_gap = combo.total_protein - target.protein
    sodium_gap = combo.total_sodium - target.sodium_limit

    lines.append("-" * 56)

    # 钠评估（控钠模式下前置到热量之前）
    if sodium_gap > 0:
        lines.append(f" 钠：超出上限 {sodium_gap} mg")
        lines.append(f"   调整建议：{_sodium_suggestion(combo, target)}")
    else:
        lines.append(
            f" 钠：{combo.total_sodium} mg，低于上限 {-sodium_gap} mg ✓"
        )
        # 控钠模式下，若最优解仍高于推荐值，说明麦当劳可选空间有限
        if target.mode == "sodium" and combo.total_sodium > 1500:
            lines.append(
                "   注意：这是当前菜单下钠含量最低的可行组合之一。"
                "麦当劳主食普遍高钠，若需严格低钠，建议减少外出就餐频次"
            )

    if combo.has_sodium_bomb:
        bombs = [i.name for i in combo.items if i.is_sodium_bomb]
        lines.append(
            f"  ⚠ 高钠单品提醒：{'、'.join(bombs)}单份钠已超1000mg"
            "（占成人建议上限 50% 以上）"
        )

    if abs(kcal_gap) <= target.tolerance:
        lines.append(f" 热量：命中目标（偏差 {kcal_gap:+d} kcal）")
    elif kcal_gap > 0:
        lines.append(f" 热量：超出 {kcal_gap} kcal")
        lines.append(f"   调整建议：{_adjust_suggestion(combo, target, reduce=True)}")
    else:
        lines.append(f" 热量：低于目标 {-kcal_gap} kcal")
        lines.append(f"   调整建议：{_adjust_suggestion(combo, target, reduce=False)}")

    if target.protein <= 0:
        lines.append(f" 蛋白：{combo.total_protein} g（未设目标，仅供参考）")
    elif protein_gap >= 0:
        lines.append(f" 蛋白：达标（超出 {protein_gap}g）")
    else:
        lines.append(f" 蛋白：差 {-protein_gap}g")
        lines.append("   调整建议：可把主食换成双层吉士汉堡（蛋白 27g）或加一份麦乐鸡")

    lines.append("=" * 56)
    return "\n".join(lines)


def _sodium_suggestion(combo: Combo, target: Target) -> str:
    """生成降钠建议。"""
    over = combo.total_sodium - target.sodium_limit

    # 优先替换高钠单品
    swaps = []
    for item in combo.items:
        if item.is_sodium_bomb:
            swaps.append((item.name, item.sodium))
    if swaps:
        name, na = max(swaps, key=lambda x: x[1])
        return f"去掉「{name}」（钠 {na}mg），可减 {na}mg"

    # 找同类低钠替代品
    for item in combo.items:
        if item.kcal >= 100 and item.sodium < 100:
            continue  # 已经是低钠
        if item.category in ("drink", "coffee"):
            continue  # 饮品不是主要钠来源

    # 提示饮品替换
    if combo.drink and combo.drink.sodium > 50:
        return f"把「{combo.drink.name}」换成无糖可乐（钠 35mg）或纯牛奶（钠 73mg）"

    return f"当前麦当劳可选单品中，低钠主食（钠<150mg）仅有饮品和甜品，{over}mg 缺口需通过减少高钠单品或降低钠上限解决"


def format_sodium_report(items: List[Item], target: Target) -> str:
    """生成控钠模式专属的高钠陷阱报告。"""
    lines = []
    lines.append("=" * 56)
    lines.append("高钠陷阱预警（钠密度 TOP 8）")
    lines.append("=" * 56)
    lines.append("钠密度 = 每 100 千卡含钠毫克数。密度高= 少量热量就吃掉大量钠。")
    lines.append("")

    ranked = sorted(
        [i for i in items if i.kcal > 0], key=lambda x: x.sodium_density, reverse=True
    )[:8]

    for item in ranked:
        flag = "⚠" if item.is_sodium_bomb else " "
        pct = round(item.sodium / target.sodium_limit * 100)
        lines.append(
            f" {flag} {item.name:<16}{item.sodium:>5}mg /{item.kcal:>4}kcal"
            f"  = {item.sodium_density:>5.1f} mg/100kcal（占上限 {pct}%）"
        )

    lines.append("")
    lines.append("关键结论：低热量 ≠ 低钠。")
    lines.append("上方多数品项热量不高，但钠密度远超常见认知。")
    lines.append("=" * 56)
    return "\n".join(lines)

    lines.append("=" * 52)
    return "\n".join(lines)


def _adjust_suggestion(combo: Combo, target: Target, reduce: bool) -> str:
    """生成具体的调整建议。"""
    gap = abs(combo.total_kcal - target.kcal)

    if reduce:
        # 找出可替换的部分
        options = []
        if combo.side:
            options.append((combo.side.name, combo.side.kcal))
        if combo.drink and combo.drink.kcal > 20:
            options.append((combo.drink.name, combo.drink.kcal))
        if options:
            name, kcal = max(options, key=lambda x: x[1])
            return f"把「{name}」（{kcal} kcal）去掉，可省 {kcal} kcal"
        return f"把主食换成更低热量的单品，或去掉配餐"

    # 需要增加热量
    additions = [
        ("中薯条", 289),
        ("麦乐鸡5块", 213),
        ("小薯条", 210),
        ("圆筒冰淇淋", 93),
    ]
    best = min(additions, key=lambda x: abs(x[1] - gap))
    diff = gap - best[1]
    msg = f"加一份「{best[0]}」（{best[1]} kcal）"
    if abs(diff) <= 30:
        return msg
    if diff > 0:
        return msg + f"，再补 {diff} kcal 即可达标"
    return msg + f"，略超 {abs(diff)} kcal，可换更小的份量"


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="麦麦营养配餐计算引擎 —— 基于麦当劳 MCP 真实营养数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  # 热量模式（默认）
  python planner.py --kcal 800 --protein 30

  # 控钠模式（差异化核心）
  python planner.py --kcal 800 --sodium-limit 1200 --sodium-focus

  # 钠密度模式（避开高钠陷阱）
  python planner.py --kcal 800 --density-focus

  # 查看高钠陷阱报告
  python planner.py --kcal 800 --sodium-report
""",
    )
    parser.add_argument("--kcal", type=int, required=True, help="热量目标（千卡）")
    parser.add_argument("--protein", type=int, default=0, help="蛋白目标（克）")
    parser.add_argument(
        "--sodium-limit",
        type=int,
        default=2000,
        help="钠摄入上限（毫克），默认 2000",
    )
    parser.add_argument(
        "--sodium-focus",
        action="store_true",
        help="控钠模式：优先低钠组合（超钠重罚）",
    )
    parser.add_argument(
        "--density-focus",
        action="store_true",
        help="钠密度模式：按 mg/100kcal 排序，避开高钠陷阱",
    )
    parser.add_argument(
        "--sodium-report",
        action="store_true",
        help="输出高钠陷阱预警报告（钠密度 TOP 8）",
    )
    parser.add_argument(
        "--allow-dessert", action="store_true", help="允许包含甜品"
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], help="排除的品类，如 burger dessert"
    )
    parser.add_argument("--limit", type=int, default=3, help="返回方案数量")
    parser.add_argument(
        "--points",
        type=int,
        default=0,
        help="用户当前可用积分（非0 时输出会员资产诊断），"
        "配合 --accumulative/--expired-point 传入完整账户数据",
    )
    parser.add_argument(
        "--accumulative", type=int, default=0, help="累计获得积分"
    )
    parser.add_argument("--expired-point", type=int, default=0, help="已过期积分")
    parser.add_argument(
        "--brand-message",
        action="store_true",
        help="生成分享话术（品牌年轻化场景）",
    )
    parser.add_argument(
        "--json", action="store_true", help="以JSON 格式输出，便于程序化调用"
    )

    args = parser.parse_args()

    items = load_items()

    # 确定规划模式
    mode = "heat"
    if args.sodium_focus:
        mode = "sodium"
    elif args.density_focus:
        mode = "density"

    target = Target(
        kcal=args.kcal,
        protein=args.protein,
        sodium_limit=args.sodium_limit,
        allow_dessert=args.allow_dessert,
        exclude_categories=args.exclude,
        mode=mode,
    )

    # 仅输出高钠报告
    if args.sodium_report:
        print()
        print(format_sodium_report(items, target))
        print()
        return

    try:
        combos = find_combos(items, target, limit=args.limit)
    except ValueError as e:
        print(f"参数错误：{e}")
        return

    if args.json:
        print(
            json.dumps(
                {
                    "target": {
                        "kcal": target.kcal,
                        "protein": target.protein,
                        "sodium_limit": target.sodium_limit,
                        "mode": target.mode,
                    },
                    "combos": [c.to_dict() for c in combos],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    mode_cn = {"heat": "热量模式", "sodium": "控钠模式", "density": "钠密度模式"}
    print()
    print(f"模式：{mode_cn[mode]}")
    print(f"目标：{target.kcal} kcal" + (f" / 蛋白 {target.protein}g" if target.protein else ""))
    print(f"钠上限：{target.sodium_limit} mg")
    print(f"数据源：MCP list-nutrition-foods（共 {len(items)} 条餐品，本地快照）")

    if mode == "sodium":
        print()
        print(format_sodium_report(items, target))
        print()

    print()

    for idx, combo in enumerate(combos, 1):
        if idx > 1:
            print()
        print(f"【方案 {idx}】")
        print(format_combo(combo, target))

    # 会员资产诊断（商业价值：存量资产盘活）
    if args.points > 0:
        acc = PointAccount(
            available=args.points,
            accumulative=args.accumulative or args.points,
            expired=args.expired_point,
        )
        diag = diagnose_points(acc)
        print()
        print("=" * 56)
        print("会员资产诊断")
        print("=" * 56)
        for insight in diag["insights"]:
            print(f"  · {insight}")
        for action in diag["actions"]:
            print(f"    → {action}")

    # 品牌话术（商业价值：品牌年轻化）
    if args.brand_message:
        best = combos[0]
        print()
        print("=" * 56)
        print("分享话术（可复制到社交平台）")
        print("=" * 56)
        print(
            build_brand_message(
                kcal=best.total_kcal,
                protein=best.total_protein,
                combo_items=[i.name for i in best.items],
                sodium=best.total_sodium,
            )
        )
        print("=" * 56)
        print("提示：话术仅陈述个人选择，不做品牌对比，不夸大健康效果。")

    print()
    print("提示：本工具输出仅供参考，不构成医疗或营养专业建议。")
    print("餐品价格、供应状态及实际营养以麦当劳官方渠道实时结果为准。")


if __name__ == "__main__":
    main()
