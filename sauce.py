"""
酱料减钠模块 (mcd-meal-planner · sauce 模式)
=============================================

数据来源与诚实声明（重要）
--------------------------
麦当劳 MCP 的 `query-meal-detail` 接口会返回餐品的 `modification`
字段，标明该餐品支持哪些"去料"操作（如去掉烤味酱、生菜）。
官方文档另明确一处可验证数据：「去沙拉酱立减 60 kcal」。

**但 MCP 不提供酱料单独的钠含量。** 本模块对"去酱减钠量"的数值
是**估算区间**，依据为公开营养成分数据库中常见汉堡酱料的钠含量
范围（典型沙拉酱/烤酱 150–350 mg/份），并在所有输出中明确标注
"估算"字样，绝不冒充麦当劳官方数据。

用途：与 planner.py 的控钠/密度模式组合，输出"同一套餐去酱后"
的钠改善区间，让控钠用户知道精准的操作路径。

设计原则：
1. 只列**实测确认支持去酱**的餐品（来自 query-meal-detail 真实返回）
2. 蔬菜类（生菜等）去料不计入减钠（钠含量可忽略，标注为口感取舍）
3. 所有估算数值必须带区间和"估算"标注，测试有专项断言

作者：参赛作品，非麦当劳官方产品
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 实测确认的可去酱餐品
# 来源：query-meal-detail 真实返回（2026-10-09，storeCode=1410574）
# ---------------------------------------------------------------------------

#: 酱料钠含量估算区间 (低, 高)，单位 mg。
#: 依据：公开营养数据库常见汉堡酱料（沙拉酱/烤酱/千岛酱类）典型范围。
#: ⚠️ 非麦当劳官方数据，输出时必须携带"估算"标注。
SAUCE_SODIUM_ESTIMATE: Tuple[int, int] = (150, 350)

@dataclass(frozen=True)
class SauceOption:
    """一个可去的酱料/配料"""

    name: str
    #: 是否为酱料（酱料计入减钠估算；蔬菜类不计）
    is_sauce: bool


#: 餐品名 → 可去酱料列表。
#: 只收录实测 query-meal-detail 返回 supportModify=true 的餐品。
MODIFIABLE_ITEMS: Dict[str, List[SauceOption]] = {
    "板烧鸡腿堡": [
        SauceOption("烤味酱", is_sauce=True),
        SauceOption("切块生菜", is_sauce=False),
    ],
    "麦辣鸡腿汉堡": [
        SauceOption("麦香鸡酱", is_sauce=True),
        SauceOption("生菜", is_sauce=False),
    ],
}

#: 蔬菜类去料的说明（不计减钠，仅口感提示）
VEGGIE_NOTE = "蔬菜类去料对钠影响可忽略，属口味取舍，不计入减钠估算"


def get_sauce_options(item_name: str) -> Optional[List[SauceOption]]:
    """查询餐品是否支持去酱。

    返回 None 表示未实测到该餐品支持 modification，
    此时**不得**为它生成减钠建议（防止无依据输出）。
    """
    return MODIFIABLE_ITEMS.get(item_name)


def estimate_sodium_saving(item_name: str) -> Optional[Tuple[int, int]]:
    """估算去掉所有酱料后的减钠区间 (低, 高) mg。

    未实测支持的餐品返回 None。
    """
    options = get_sauce_options(item_name)
    if not options:
        return None
    sauces = [o for o in options if o.is_sauce]
    if not sauces:
        return None
    # 每种酱料按独立区间估算，取合计范围
    low = SAUCE_SODIUM_ESTIMATE[0] * len(sauces)
    high = SAUCE_SODIUM_ESTIMATE[1] * len(sauces)
    return (low, high)


def list_modifiable_in(names: List[str]) -> List[str]:
    """从一组餐品名中筛出支持去酱的（模糊匹配：名称包含即命中）。"""
    hits = []
    for name in names:
        for mod_name in MODIFIABLE_ITEMS:
            if mod_name in name or name in mod_name:
                hits.append(name)
                break
    return hits


def format_sauce_report(item_names: List[str], combo_sodium: int) -> str:
    """生成"去酱减钠"报告文本。

    combo_sodium 为当前组合的总钠（mg），用于计算去酱后的改善幅度。
    若组合中没有任何支持去酱的餐品，返回空字符串（不硬凑）。
    """
    modifiable = list_modifiable_in(item_names)
    if not modifiable:
        return ""

    lines = []
    lines.append("")
    lines.append("-" * 56)
    lines.append(" 去酱减钠方案（sauce 模式）")
    lines.append("-" * 56)

    total_low = total_high = 0
    for name in modifiable:
        saving = estimate_sodium_saving(name)
        if saving is None:
            continue
        low, high = saving
        total_low += low
        total_high += high
        options = get_sauce_options(name)
        sauce_names = "、".join(o.name for o in options if o.is_sauce)
        lines.append(
            f"  · {name} 去{sauce_names}"
            f" → 预计减钠 {low}–{high} mg（估算）"
        )
        # 蔬菜类提示
        veggies = [o.name for o in options if not o.is_sauce]
        if veggies:
            lines.append(f"    （另有 {'、'.join(veggies)} 可去：{VEGGIE_NOTE}）")

    after_low = max(combo_sodium - total_high, 0)
    after_high = max(combo_sodium - total_low, 0)
    lines.append("-" * 56)
    lines.append(
        f"  当前组合钠 {combo_sodium} mg"
        f" → 去酱后约 {after_low}–{after_high} mg（估算区间）"
    )
    lines.append(
        "  数据说明：减钠量为基于常见酱料营养数据的估算区间，"
        "非麦当劳官方数值；"
        "官方文档仅明确「去沙拉酱立减 60 kcal」。"
        "下单时在自定义配料中选择去掉对应酱料即可。"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== 可去酱餐品 ===")
    for k, v in MODIFIABLE_ITEMS.items():
        sauces = [o.name for o in v if o.is_sauce]
        print(f"  {k}: 去{'、'.join(sauces)}")

    print()
    print("=== 减钠估算 ===")
    for k in MODIFIABLE_ITEMS:
        print(f"  {k}: {estimate_sodium_saving(k)}")

    print()
    print("=== 不支持去酱的餐品（应返回 None）===")
    for name in ["巨无霸", "薯条", "麦乐鸡"]:
        print(f"  {name}: {estimate_sodium_saving(name)}")

    print()
    print("=== 报告示例（含板烧鸡腿堡的组合）===")
    print(format_sauce_report(["板烧鸡腿堡", "脆薯饼", "无糖可乐"], 1250))

    print()
    print("=== 报告示例（无可去酱组合，应为空）===")
    print(repr(format_sauce_report(["巨无霸", "脆薯饼"], 1500)))
