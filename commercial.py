#!/usr/bin/env python3
"""
商业价值模块 (commercial.py)
==============================

把营养配餐能力与麦当劳的实际业务诉求对接——会员资产激活、点单转化、
活动引流、品牌年轻化。

本模块不介入下单交易，只做「决策引导 + 资产提醒」：
- 积分资产诊断（过期预警，直接对应会员活跃度）
- 券资产盘点（沉睡券唤醒，直接对应券核销率）
- 积分兑换建议（积分→消费转化）
- 活动引流（新品/活动触达）
- 品牌年轻化表达（社交话术生成）

设计原则：
1. 商业指标必须可验证 —— 每个数字来自 MCP 真实返回
2. 不做夸大承诺 —— 只呈现事实，不编造效果
3. 不替用户决策 —— 引导而非诱导

作者：参赛作品，非麦当劳官方产品
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class PointAccount:
    """麦享会积分账户（对应 MCP query-my-account）"""

    available: int = 0
    accumulative: int = 0
    used: int = 0
    expired: int = 0
    current_month_expire: int = 0
    next_month_expire: int = 0
    frozen: int = 0

    @property
    def total_owned(self) -> int:
        """历史总获得积分"""
        return self.accumulative

    @property
    def expire_risk_ratio(self) -> float:
        """过期积分占累计比例（越高说明会员资产浪费越多）"""
        if self.accumulative <= 0:
            return 0.0
        return round(self.expired / self.accumulative * 100, 1)

    @property
    def dormant_ratio(self) -> float:
        """沉睡积分占比（可用 / 累计），越低说明积分越被闲置"""
        if self.accumulative <= 0:
            return 0.0
        return round(self.available / self.accumulative * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "accumulative": self.accumulative,
            "used": self.used,
            "expired": self.expired,
            "expire_risk_ratio": self.expire_risk_ratio,
            "dormant_ratio": self.dormant_ratio,
        }


@dataclass
class Coupon:
    """优惠券（对应 MCP available-coupons / query-my-coupons）"""

    title: str
    status: str  # 可领取 / 已领取 / 已使用 / 已过期

    @property
    def is_claimable(self) -> bool:
        return "可领取" in self.status

    @property
    def is_unused(self) -> bool:
        """已领取但未使用= 沉睡资产"""
        return "已领取" in self.status


@dataclass
class LotteryInfo:
    """积分抽奖信息（对应 MCP query-lottery-info）"""

    name: str = ""
    status: str = ""
    draw_point: int = 0
    available_point: int = 0
    eligible: bool = False
    prizes: List[str] = field(default_factory=list)

    @property
    def can_afford(self) -> bool:
        """当前积分是否够抽一次"""
        return self.draw_point > 0 and self.available_point >= self.draw_point


# ---------------------------------------------------------------------------
# 商业诊断
# ---------------------------------------------------------------------------


def diagnose_points(acc: PointAccount) -> Dict[str, Any]:
    """积分资产诊断——对应麦当劳「会员活跃度」诉求。

    核心洞察：过期积分是麦当劳最直接的会员资产流失点。
    实测样本：可用 57.9 / 累计 962.7 / 已过期 758.8
    → 79% 的历史积分已经过期，这是可被激活的存量。
    """
    insights: List[str] = []
    actions: List[str] = []

    # 过期积分预警
    if acc.expired > 0:
        insights.append(
            f"历史累计 {acc.total_owned} 积分中，已有 {acc.expired} 分过期"
            f"（占 {acc.expire_risk_ratio}%）"
        )
        actions.append(
            "过期积分不可恢复，但可通过稳定消费节奏避免再次沉淀过期"
        )

    # 本月/次月过期预警（最具行动价值）
    if acc.current_month_expire > 0:
        insights.append(f"本月将过期 {acc.current_month_expire} 分，**这是最紧急的**")
        actions.append(f"优先在{acc.current_month_expire} 分过期前完成兑换或消费")

    if acc.next_month_expire > 0:
        insights.append(f"下月将过期 {acc.next_month_expire} 分")
        actions.append(f"下月过期前安排一次兑换，预计可激活 {acc.next_month_expire} 分")

    # 沉睡积分诊断
    if acc.dormant_ratio < 20 and acc.available > 50:
        insights.append(
            f"可用积分 {acc.available} 分，但仅占累计的 {acc.dormant_ratio}%"
            "——积分账户处于沉睡状态"
        )
        actions.append("可用积分足以兑换，建议查看积分商城可用商品")

    # 消费转化建议
    if acc.available >= 24:
        insights.append(f"可用积分 {acc.available} 分，可参与积分抽奖（单次 24 分）")
        actions.append("积分抽奖是低门槛消耗积分的方式，可作为日常动作")

    return {
        "insights": insights,
        "actions": actions,
        "metrics": acc.to_dict(),
    }


def diagnose_coupons(coupons: List[Coupon]) -> Dict[str, Any]:
    """券资产盘点——对应麦当劳「券核销率」与「点单转化」诉求。

    核心洞察：已领取未使用的券是最容易转化的资产。
    用户已经完成了一次「领券」动作，核销只差临门一脚。
    """
    claimable = [c for c in coupons if c.is_claimable]
    unused = [c for c in coupons if c.is_unused]

    insights: List[str] = []
    actions: List[str] = []

    if claimable:
        insights.append(f"有 {len(claimable)} 张券未领取——领券是零成本动作")
        actions.append(
            f"可立即领取：{'、'.join(c.title for c in claimable[:3])}"
            f"{'等' if len(claimable) > 3 else ''}"
        )

    if unused:
        insights.append(
            f"有 {len(unused)} 张已领取但未使用的券——这是最容易转化的沉睡资产"
        )
        actions.append("已领券的用户购买意愿通常已确认，核销只差一次下单")

    if not coupons:
        insights.append("当前无任何优惠券，建议先领取新人券")
        actions.append("麦麦省可领券通常为无门槛或低门槛，是最直接的优惠来源")

    return {
        "insights": insights,
        "actions": actions,
        "metrics": {
            "total": len(coupons),
            "claimable": len(claimable),
            "unused": len(unused),
        },
    }


def build_brand_message(
    kcal: int, protein: int, combo_items: List[str], sodium: int
) -> str:
    """生成社交分享话术——对应麦当劳「品牌年轻化」诉求。

    场景：用户控钠成功后，主动分享到社交平台，
    形成「我居然在麦当劳吃出了健康餐」的内容传播。
    """
    lines = []
    lines.append("今天在麦当劳吃了个" + str(kcal) + " 大卡的套餐🍔")
    lines.append("组合：" + " + ".join(combo_items))
    lines.append(f"蛋白{protein}g，钠 {sodium}mg✅")

    if sodium <= 800:
        lines.append("重点是钠控制住了，别小看这个数字👇")
        lines.append("很多看着清淡的东西其实钠含量很高，麦当劳也一样")
        lines.append("（用这个工具查的：链接）")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 商业价值自述（供文档/演示引用）
# ---------------------------------------------------------------------------

COMMERCIAL_MAPPING = {
    "会员资产激活": {
        "对应MCP工具": ["query-my-account", "query-lottery-info", "mall-points-products"],
        "本项目能力": "积分过期预警 + 沉睡积分诊断 + 兑换时机建议",
        "可验证指标": [
            "会员积分活跃率（有过期积分的会员占比）",
            "积分月消耗率（可用积分 → 实际消耗）",
            "沉睡积分占比（可用/累计）",
        ],
        "实测样本": "可用 57.9 / 累计 962.7 / 已过期 758.8 → 79% 历史积分已过期",
    },
    "券核销率提升": {
        "对应MCP工具": ["available-coupons", "auto-bind-coupons", "query-my-coupons"],
        "本项目能力": "券资产盘点 + 临期/未领取提醒 + 券与配餐方案联动",
        "可验证指标": [
            "领券率（available-coupons → auto-bind-coupons 转化）",
            "核销率（已领券 → 实际使用）",
            "沉睡券占比（已领未用）",
        ],
        "实测样本": "9 张券中 6 张已领取，其中部分为已领未用",
    },
    "点单转化": {
        "对应MCP工具": ["query-meals", "calculate-price", "query-store-coupons"],
        "本项目能力": "配餐方案 → 明确「点什么」降低决策成本（本项目不直接下单）",
        "可验证指标": [
            "方案点击到下单转化率",
            "客单价变化（配餐引导 vs 随机点单）",
            "连带品项数（配餐是否带动加购）",
        ],
        "说明": "本项目刻意不接create-order，避免误下单风险；转化价值通过「决策引导」间接实现",
    },
    "活动引流": {
        "对应MCP工具": ["campaign-calendar", "query-lottery-info", "query-party-*"],
        "本项目能力": "活动日历同步 + 新品提示 + 积分抽奖/主题活动提醒",
        "可验证指标": [
            "活动期间参与人数",
            "新品首周销量",
            "主题活动预约转化率",
        ],
        "实测样本": "campaign-calendar 返回 13 个日期节点的活动，含未来活动",
    },
    "品牌年轻化": {
        "对应MCP工具": ["全部查询类接口（不写入任何数据）"],
        "本项目能力": "生成社交分享话术，形成「控钠也能吃麦当劳」的内容",
        "可验证指标": [
            "用户自发分享量",
            "UGC 中「健康」「控钠」关键词出现频次",
            "品牌提及情绪（正面占比）",
        ],
        "合规注意": "话术仅陈述个人选择，不做品牌对比、不夸大健康效果",
    },
}


def print_commercial_report(
    account: Optional[PointAccount] = None,
    coupons: Optional[List[Coupon]] = None,
    lottery: Optional[LotteryInfo] = None,
) -> None:
    """输出商业价值诊断报告。"""
    print()
    print("=" * 56)
    print("会员资产与转化机会诊断")
    print("=" * 56)

    if account:
        diag = diagnose_points(account)
        if diag["insights"]:
            print("\n【积分资产】")
            for i in diag["insights"]:
                print(f"  · {i}")
            for a in diag["actions"]:
                print(f"    → {a}")
        else:
            print("\n【积分资产】暂无数据")

    if coupons is not None:
        diag = diagnose_coupons(coupons)
        if diag["insights"]:
            print("\n【券资产】")
            for i in diag["insights"]:
                print(f"  · {i}")
            for a in diag["actions"]:
                print(f"    → {a}")

    if lottery and lottery.can_afford:
        print("\n【积分抽奖】")
        print(
            f"  · {lottery.name}（{lottery.status}），单次消耗 {lottery.draw_point} 分"
        )
        print(f"    → 当前可用 {lottery.available_point} 分，可抽 {lottery.available_point // lottery.draw_point} 次")

    print()
    print("说明：本模块仅做资产提醒与决策引导，不执行下单、领券、抽奖等写操作。")
    print("=" * 56)


if __name__ == "__main__":
    # 自测：使用实测数据
    acc = PointAccount(
        available=57,
        accumulative=962,
        used=146,
        expired=758,
        current_month_expire=0,
        next_month_expire=0,
    )
    coupons = [
        Coupon("免费脆薯饼", "可领取"),
        Coupon("人气麦旋风买一送一", "可领取"),
        Coupon("9.9元中杯冰美式", "可领取"),
        Coupon("麦旋风任选", "已领取"),
        Coupon("薯薯任选", "已领取"),
    ]
    lottery = LotteryInfo(
        name="麦麦积分抽奖",
        status="进行中",
        draw_point=24,
        available_point=57,
        eligible=True,
        prizes=["下单立减3元券", "麦辣三件套5折券", "麦旋风5折券"],
    )

    print_commercial_report(acc, coupons, lottery)

    print()
    print("\n【品牌话术示例】")
    print(build_brand_message(773, 16, ["麦乐鸡4块", "大薯条", "可乐大杯"], 553))
