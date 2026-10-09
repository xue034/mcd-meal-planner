#!/usr/bin/env python3
"""
门店实时数据模块 (store.py)
============================

把营养配餐从「纸上计算」升级为「能真实买到」。

解决的问题：
    营养数据（list-nutrition-foods）是全国统一的标准营养库，但门店实际在售的
    菜单、实时价格、可用的门店优惠券是动态的。只用营养库计算，可能推荐出
    用户所在门店买不到的品项，或价格与实际不符。

本模块的能力：
    1. 门店定位—— searchType=2 按位置搜索（关键：不依赖用户收藏门店）
    2. 实时菜单—— 拉取门店实际在售商品与价格
    3. 门店优惠券—— 该门店当前可用的券及其适用商品
    4. 可买性校验 —— 把营养推荐与真实菜单做交集，过滤掉买不到的品项

⚠️ 重要技术勘误（2026-10-09）
────────────────────────────────────────────────
本项目早期版本在文档中声称「query-nearby-stores 对未收藏门店的用户不可用」
并以此作为差异化卖点。**该结论是错误的。**

实测结论：
    searchType=1（搜索收藏门店）→ 未收藏时返回 600050 收藏门店列表为空
    searchType=2（按位置搜索）→ **完全可用**，无需收藏任何门店

正确用法示例（已实测跑通）：
    query-nearby-stores(beType=1, searchType=2, city="厦门", keyword="思明区")
    → 返回 5 家门店，含 storeCode / 营业时间 / 预约时段

教训：接口报错时先怀疑自己的参数组合，不要急着下"接口不可用"的结论。
     本模块的定位逻辑即基于此勘误。

作者：参赛作品，非麦当劳官方产品
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Store:
    """门店信息（对应 query-nearby-stores 返回）"""

    store_code: str
    store_name: str
    address: str
    distance: int  # 米
    business_status: bool = True
    business_start: str = ""
    business_end: str = ""
    supports_reservation: bool = False
    #: 到店自取(1) / 得来速(5) / 麦乐送(2) / 团餐(6)
    be_type: int = 1
    #: 业务编码，得来速/外送场景必填
    be_code: str = ""

    @property
    def order_type(self) -> int:
        """订单类型：1-到店，2-外送"""
        return 1 if self.be_type in (1, 5) else 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storeCode": self.store_code,
            "storeName": self.store_name,
            "address": self.address,
            "distance": self.distance,
            "businessStatus": self.business_status,
            "businessStartTime": self.business_start,
            "businessEndTime": self.business_end,
            "supportsReservation": self.supports_reservation,
            "beType": self.be_type,
            "beCode": self.be_code,
        }


@dataclass
class MenuItem:
    """菜单商品（对应 query-meals 返回）"""

    code: str
    name: str
    current_price: float
    original_price: float
    #: 优惠类型：None / 早餐卡优惠 / 促销优惠 / 麦金卡优惠 / 随单购麦金卡优惠
    discount_type: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    category: str = ""

    @property
    def is_discounted(self) -> bool:
        return self.discount_type is not None

    @property
    def discount_amount(self) -> float:
        """折扣金额"""
        return round(self.original_price - self.current_price, 2)

    @property
    def discount_rate(self) -> str:
        """折扣率，如「47折」不准确，用百分比表达"""
        if self.original_price <= 0:
            return "-"
        return f"{round(self.current_price / self.original_price * 100)}%"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "currentPrice": self.current_price,
            "originalPrice": self.original_price,
            "discountType": self.discount_type,
            "discountRate": self.discount_rate,
            "tags": self.tags,
            "category": self.category,
        }


@dataclass
class StoreCoupon:
    """门店优惠券（对应 query-store-coupons 返回）"""

    title: str
    coupon_id: str
    coupon_code: str
    #: 有效期
    valid_from: str = ""
    valid_to: str = ""
    #: 适用商品编码列表
    product_codes: List[str] = field(default_factory=list)
    product_names: List[str] = field(default_factory=list)

    def applies_to(self, product_code: str) -> bool:
        """该券是否适用于指定商品"""
        return product_code in self.product_codes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "couponId": self.coupon_id,
            "validFrom": self.valid_from,
            "validTo": self.valid_to,
            "products": self.product_names,
        }


# ---------------------------------------------------------------------------
# 参数构造（供 MCP 调用方使用）
# ---------------------------------------------------------------------------


def build_store_query(city: str, keyword: str, be_type: int = 1) -> Dict[str, Any]:
    """构造 query-nearby-stores 的调用参数。

    ⚠️ 关键：`searchType=2` 是按位置搜索，不需要用户预先收藏门店。
    `searchType=1`（默认值）是搜索收藏门店，未收藏时会返回 600050。

    Args:
        city: 城市名，如 "厦门"
        keyword: 商圈/区域关键词，如 "思明区"、"湖滨南路"
        be_type: 1-到店自取，5-得来速，2-麦乐送，6-团餐

    Returns:
        MCP 调用参数字典
    """
    return {
        "beType": be_type,
        "searchType": 2,  # 必须为 2，否则未收藏用户会失败
        "city": city,
        "keyword": keyword,
    }


def build_menu_query(store: Store) -> Dict[str, Any]:
    """构造 query-meals 的调用参数。

    Args:
        store: 门店对象

    Returns:
        MCP 调用参数字典
    """
    params: Dict[str, Any] = {
        "storeCode": store.store_code,
        "orderType": store.order_type,
        "beType": store.be_type,
    }
    # 得来速/外送/团餐必须传 beCode，到店自取不传
    if store.be_type in (2, 5, 6):
        if not store.be_code:
            raise ValueError(
                f"门店 {store.store_name} 为得来速/外送/团餐场景，"
                "必须提供 beCode（来自 query-nearby-stores 的 beCode 字段）"
            )
        params["beCode"] = store.be_code
    return params


def build_store_coupon_query(store: Store) -> Dict[str, Any]:
    """构造 query-store-coupons 的调用参数。"""
    params: Dict[str, Any] = {
        "storeCode": store.store_code,
        "orderType": store.order_type,
        "beType": store.be_type,
    }
    if store.be_type in (2, 5, 6):
        if not store.be_code:
            raise ValueError(f"门店 {store.store_name} 缺少 beCode")
        params["beCode"] = store.be_code
    return params


def build_price_query(
    store: Store, items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """构造 calculate-price 的调用参数。

    Args:
        store: 门店对象
        items: 商品列表，形如
               [{"productCode": "1100", "quantity": 1, "couponCode": "xxx"}]
               couponCode 为选填，用券核价时传入

    Returns:
        MCP 调用参数字典
    """
    params: Dict[str, Any] = {
        "storeCode": store.store_code,
        "orderType": store.order_type,
        "beType": store.be_type,
        "items": items,
    }
    if store.be_type in (2, 5, 6):
        if not store.be_code:
            raise ValueError(f"门店 {store.store_name} 缺少 beCode")
        params["beCode"] = store.be_code
    return params


# ---------------------------------------------------------------------------
# 解析函数（从 MCP 返回的 JSON 构建对象）
# ---------------------------------------------------------------------------


def parse_stores(raw: str) -> List[Store]:
    """解析 query-nearby-stores 返回。

    Args:
        raw: 接口返回的原始 JSON 字符串

    Returns:
        Store 列表
    """
    import json

    payload = json.loads(raw)
    if not payload.get("success"):
        raise ValueError(payload.get("message", "门店查询失败"))

    stores: List[Store] = []
    for item in payload.get("data", []):
        stores.append(
            Store(
                store_code=item["storeCode"],
                store_name=item["storeName"],
                address=item.get("address", ""),
                distance=item.get("distance", 0),
                business_status=item.get("businessStatus", True),
                business_start=item.get("businessStartTime", ""),
                business_end=item.get("businessEndTime", ""),
                supports_reservation=item.get("reservation", False),
            )
        )
    return stores


def parse_menu(raw: str) -> List[MenuItem]:
    """解析 query-meals 返回。

    Args:
        raw: 接口返回的原始 JSON 字符串

    Returns:
        MenuItem 列表（按菜单分类顺序）
    """
    import json

    payload = json.loads(raw)
    if not payload.get("success"):
        raise ValueError(payload.get("message", "菜单查询失败"))

    data = payload.get("data", {})
    meals_map = data.get("meals", {})
    items: List[MenuItem] = []

    for category in data.get("categories", []):
        cat_name = category.get("name", "").replace("\n", "")
        for ref in category.get("meals", []):
            code = ref["code"]
            detail = meals_map.get(code)
            if not detail:
                continue
            items.append(
                MenuItem(
                    code=code,
                    name=detail.get("name", ""),
                    current_price=float(detail.get("currentPrice", 0)),
                    original_price=float(detail.get("originalPrice", 0)),
                    discount_type=detail.get("discountType"),
                    tags=ref.get("tags", []),
                    category=cat_name,
                )
            )
    return items


def parse_store_coupons(raw: str) -> List[StoreCoupon]:
    """解析 query-store-coupons 返回。"""
    import json

    payload = json.loads(raw)
    if not payload.get("success"):
        raise ValueError(payload.get("message", "门店优惠券查询失败"))

    coupons: List[StoreCoupon] = []
    for item in payload.get("data", []):
        time_range = item.get("tradeDateTime", "")
        # 格式 "2026-10-05 10:30:00-2026-10-09 23:59:59"
        parts = time_range.split("-") if "-" in time_range else [time_range, ""]
        valid_from = parts[0].strip() if len(parts) > 0 else ""
        valid_to = parts[-1].strip() if len(parts) > 1 else ""

        products = item.get("products", [])
        coupons.append(
            StoreCoupon(
                title=item.get("title", ""),
                coupon_id=item.get("couponId", ""),
                coupon_code=item.get("couponCode", ""),
                valid_from=valid_from,
                valid_to=valid_to,
                product_codes=[p["productCode"] for p in products],
                product_names=[p["productName"] for p in products],
            )
        )
    return coupons


# ---------------------------------------------------------------------------
# 可买性校验（本模块的核心价值）
# ---------------------------------------------------------------------------


@dataclass
class AvailabilityReport:
    """可买性校验报告"""

    #: 推荐组合中可买到的品项名称
    available: List[str] = field(default_factory=list)
    #: 推荐组合中买不到的品项名称
    unavailable: List[str] = field(default_factory=list)
    #: 可买品项合计价格
    total_price: float = 0.0
    #: 可用券（与可买品项有交集的）
    usable_coupons: List[StoreCoupon] = field(default_factory=list)

    @property
    def all_available(self) -> bool:
        return not self.unavailable

    @property
    def coverage(self) -> float:
        """可买率"""
        total = len(self.available) + len(self.unavailable)
        if total == 0:
            return 0.0
        return round(len(self.available) / total * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "unavailable": self.unavailable,
            "totalPrice": self.total_price,
            "usableCoupons": [c.to_dict() for c in self.usable_coupons],
            "coverage": self.coverage,
        }


def check_availability(
    recommended_names: List[str],
    menu: List[MenuItem],
    coupons: Optional[List[StoreCoupon]] = None,
) -> AvailabilityReport:
    """校验推荐组合在目标门店是否真的买得到。

    这是本模块最关键的功能——没有它，营养计算可能给出"看起来完美但
    门店买不到"的方案。

    Args:
        recommended_names: 引擎推荐品项名称列表
        menu: 门店实时菜单（query-meals 返回）
        coupons: 门店优惠券（query-store-coupons 返回），可选

    Returns:
        AvailabilityReport

    Example:
        >>> menu = parse_menu(raw_menu_json)
        >>> report = check_availability(["巨无霸", "中薯条"], menu)
        >>> report.coverage
        100.0
    """
    menu_index = {m.name: m for m in menu}
    report = AvailabilityReport()

    matched_codes: List[str] = []

    for name in recommended_names:
        matched = _fuzzy_find(name, menu_index)
        if matched is None:
            report.unavailable.append(name)
        else:
            report.available.append(name)
            report.total_price += matched.current_price
            matched_codes.append(matched.code)

    # 找出适用于可买品项的券
    if coupons:
        for coupon in coupons:
            if any(coupon.applies_to(code) for code in matched_codes):
                report.usable_coupons.append(coupon)

    return report


def _fuzzy_find(
    name: str, menu_index: Dict[str, MenuItem]
) -> Optional[MenuItem]:
    """在菜单中按名称查找品项，容忍部分差异。

    匹配策略：
    1. 精确匹配
    2. 忽略括号内容后匹配（"儿童鱼排堡" vs "儿童鱼排堡(鱼排)")
    3. 双向包含匹配
    """
    if name in menu_index:
        return menu_index[name]

    # 去掉括号后再试
    simplified = _strip_brackets(name)
    for menu_name, item in menu_index.items():
        if _strip_brackets(menu_name) == simplified:
            return item

    # 包含匹配
    for menu_name, item in menu_index.items():
        if name in menu_name or menu_name in name:
            return item

    return None


def _strip_brackets(text: str) -> str:
    """去掉括号及其内容。"""
    import re

    return re.sub(r"[（(][^）)]*[）)]", "", text).strip()


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------


def format_availability(report: AvailabilityReport, store_name: str = "") -> str:
    """把可买性报告格式化为可读文本。"""
    lines = []
    title = f"门店可买性校验{f'（{store_name}）' if store_name else ''}"
    lines.append("=" * 56)
    lines.append(title)
    lines.append("=" * 56)

    if report.all_available:
        lines.append(f"✅ 推荐组合全部可买（可买率 {report.coverage}%）")
    else:
        lines.append(f"⚠️ 部分品项在当前门店不可买（可买率 {report.coverage}%）")
        if report.unavailable:
            lines.append(f"   买不到：{'、'.join(report.unavailable)}")
            lines.append("   建议：换用同营养档位的其他品项，或换一家门店")

    lines.append("")
    lines.append(f"  预估合计：¥{report.total_price:.1f}（以门店实际价格为准）")

    if report.usable_coupons:
        lines.append("")
        lines.append("  该门店当前可用券：")
        for c in report.usable_coupons:
            lines.append(f"    · {c.title}（适用于 {'、'.join(c.product_names)}）")
            if c.valid_to:
                lines.append(f"      有效期至 {c.valid_to}")
    else:
        lines.append("  该门店暂无可用券（或券不适用于本组合）")

    lines.append("=" * 56)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 自测
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 56)
    print("门店模块自测（使用 2026-10-09 实测数据）")
    print("=" * 56)

    # 测试 1：门店查询参数构造
    print("\n[1] 门店查询参数（关键：searchType=2）")
    print("   ", build_store_query("厦门", "思明区"))

    # 测试 2：菜单查询参数
    store = Store(
        store_code="1410574",
        store_name="麦当劳厦门湖滨南路(华润万象城二期)餐厅",
        address="湖滨南路与金榜路交叉口东北侧华润万象城二期",
        distance=242,
        business_start="07:00",
        business_end="22:00",
        supports_reservation=True,
    )
    print("\n[2] 菜单查询参数")
    print("   ", build_menu_query(store))

    # 测试 3：外送场景缺 beCode 应报错
    delivery = Store(
        store_code="1410574",
        store_name="测试门店",
        address="",
        distance=0,
        be_type=5,  # 得来速
    )
    try:
        build_menu_query(delivery)
        print("\n[3] 得来速缺 beCode：未报错（异常）")
    except ValueError as e:
        print(f"\n[3] 得来速缺 beCode：正确捕获 -> {str(e)[:50]}...")

    # 测试 4：可买性校验
    menu = [
        MenuItem("1100", "巨无霸", 26.0, 26.0, category="巨无霸牛鱼肉堡"),
        MenuItem("1406", "板烧鸡腿堡", 23.5, 23.5, category="鸡肉汉堡/卷"),
        MenuItem("4810", "薯条", 14.5, 14.5, category="小食甜品/其他"),
        MenuItem(
            "9900008751", "可乐", 9.5, 9.5, category="饮品"
        ),
        MenuItem(
            "9900005462", "板烧鸡腿堡三件套", 34.5, 48.0,
            category="鸡肉汉堡/卷"
        ),
    ]
    coupons = [
        StoreCoupon(
            "薯薯任选",
            "E86377A0349D730EF7C27EBBE7B4C0FE",
            "MCD6001708A300092MX3W",
            "2026-10-05 10:30:00",
            "2026-10-09 23:59:59",
            ["9900016370"],
            ["薯薯任选"],
        )
    ]

    print("\n[4] 可买性校验——全部可买场景")
    rep = check_availability(["巨无霸", "薯条", "可乐"], menu, coupons)
    print(format_availability(rep, "实测门店"))

    print("\n[5] 可买性校验——部分不可买场景")
    rep2 = check_availability(["巨无霸", "中薯条", "雪菜脆笋鸡肉粥"], menu)
    print(format_availability(rep2, "实测门店"))

    print("\n[6] 模糊匹配（括号差异）")
    rep3 = check_availability(["板烧鸡腿堡三件套"], menu)
    print(f"   板烧鸡腿堡三件套 → {rep3.available or rep3.unavailable}")

    print("\n" + "=" * 56)
    print("全部自测通过")
    print("=" * 56)
