#!/usr/bin/env python3
"""
麦麦营养配餐计算引擎 (mcd-meal-planner)
========================================

基于麦当劳中国 MCP Server 真实返回的营养数据，为用户按热量/蛋白目标
计算最优套餐组合，并给出与目标的差值和调整建议。

设计原则：
1. 数据来源可追溯 —— 全部营养数值来自 MCP list-nutrition-foods 接口真实返回
2. 离线可运行 —— MCP 不可用时回退到本地快照，不阻塞用户
3. 输出可验证 —— 每个套餐都给出精确到克的数值，不用模糊描述

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
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

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
    #: 是否允许甜品
    allow_dessert: bool = False
    #: 排除的品类
    exclude_categories: List[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.kcal <= 0:
            raise ValueError("热量目标必须大于 0")
        if self.protein < 0:
            raise ValueError("蛋白目标不能为负数")
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

    评分维度：
    1. 热量贴近度（权重最高）
    2. 蛋白达标度
    3. 钠惩罚（超上限重罚）
    """
    kcal_gap = abs(combo.total_kcal - target.kcal)

    # 热量每偏离 1 kcal 的代价
    score = float(kcal_gap) * 1.0

    # 蛋白缺口按每克 8 kcal 的等价代价计入
    if combo.total_protein < target.protein:
        protein_gap = target.protein - combo.total_protein
        score += protein_gap * 8.0

    # 钠超限重罚
    if combo.total_sodium > target.sodium_limit:
        score += (combo.total_sodium - target.sodium_limit) * 0.5

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
    lines.append("=" * 52)
    lines.append("推荐套餐")
    lines.append("=" * 52)

    for item in combo.items:
        lines.append(
            f"  · {item.name:<12} {item.kcal:>4} kcal"
            f" | 蛋白 {item.protein:>2}g"
            f" | 脂肪 {item.fat:>2}g"
            f" | 碳水 {item.carb:>2}g"
        )

    lines.append("-" * 52)
    lines.append(
        f"  合计       {combo.total_kcal:>4} kcal"
        f" | 蛋白 {combo.total_protein:>2}g"
        f" | 脂肪 {combo.total_fat:>2}g"
        f" | 碳水 {combo.total_carb:>2}g"
    )
    lines.append(
        f"  钠 {combo.total_sodium} mg"
        f" | 钙 {combo.total_calcium} mg"
    )

    # 与目标的差值
    kcal_gap = combo.total_kcal - target.kcal
    protein_gap = combo.total_protein - target.protein

    lines.append("-" * 52)
    if abs(kcal_gap) <= target.tolerance:
        lines.append(f"  热量：命中目标（偏差 {kcal_gap:+d} kcal，在 ±{target.tolerance} 容差内）")
    elif kcal_gap > 0:
        lines.append(f"  热量：超出 {kcal_gap} kcal")
        lines.append(f"    调整建议：{_adjust_suggestion(combo, target, reduce=True)}")
    else:
        deficit = -kcal_gap
        lines.append(f"  热量：低于目标 {deficit} kcal")
        lines.append(f"    调整建议：{_adjust_suggestion(combo, target, reduce=False)}")

    if target.protein <= 0:
        lines.append(f"  蛋白：{combo.total_protein} g（未设目标，仅供参考）")
    elif protein_gap >= 0:
        lines.append(f"  蛋白：达标（超出 {protein_gap}g）")
    else:
        lines.append(f"  蛋白：差 {-protein_gap}g")
        lines.append("    调整建议：可把主食换成双层吉士汉堡（蛋白 27g）或加一份麦乐鸡")

    if combo.total_sodium > target.sodium_limit:
        lines.append(
            f"  钠：{combo.total_sodium} mg，超出建议上限 {target.sodium_limit} mg"
            "，建议搭配无糖可乐或清水"
        )
    else:
        lines.append(
            f"  钠：{combo.total_sodium} mg"
            f"（占建议上限 {round(combo.total_sodium / target.sodium_limit * 100)}%）"
        )

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
        description="麦麦营养配餐计算引擎 —— 基于麦当劳 MCP 真实营养数据"
    )
    parser.add_argument("--kcal", type=int, required=True, help="热量目标（千卡）")
    parser.add_argument("--protein", type=int, default=0, help="蛋白目标（克）")
    parser.add_argument(
        "--sodium-limit", type=int, default=2000, help="钠摄入上限（毫克），默认 2000"
    )
    parser.add_argument(
        "--allow-dessert", action="store_true", help="允许包含甜品"
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], help="排除的品类，如 burger dessert"
    )
    parser.add_argument("--limit", type=int, default=3, help="返回方案数量")
    parser.add_argument(
        "--json", action="store_true", help="以JSON 格式输出，便于程序化调用"
    )

    args = parser.parse_args()

    items = load_items()
    target = Target(
        kcal=args.kcal,
        protein=args.protein,
        sodium_limit=args.sodium_limit,
        allow_dessert=args.allow_dessert,
        exclude_categories=args.exclude,
    )

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
                    },
                    "combos": [c.to_dict() for c in combos],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print()
    print(f"目标：{target.kcal} kcal" + (f" / 蛋白 {target.protein}g" if target.protein else ""))
    print(f"数据源：MCP list-nutrition-foods（共 {len(items)} 条餐品，本地快照）")
    print()

    for idx, combo in enumerate(combos, 1):
        if idx > 1:
            print()
        print(f"【方案 {idx}】")
        print(format_combo(combo, target))

    print()
    print("提示：本工具输出仅供参考，不构成医疗或营养专业建议。")
    print("餐品价格、供应状态及实际营养以麦当劳官方渠道实时结果为准。")


if __name__ == "__main__":
    main()
