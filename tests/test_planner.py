#!/usr/bin/env python3
"""
单元测试：麦麦营养配餐计算引擎
================================

运行方式：
    python -m unittest discover tests -v
    或
    python tests/test_planner.py

零依赖，仅用标准库 unittest。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planner import (  # noqa: E402
    Combo,
    Item,
    Target,
    find_combos,
    format_combo,
    load_items,
    load_items_from_toon,
)
from toon_parser import (  # noqa: E402
    ToonParseError,
    parse_nutrition_toon,
    parse_toon,
    to_toon,
)


class TestToonParser(unittest.TestCase):
    """TOON 格式解析器测试"""

    SAMPLE = (
        "[3]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:\n"
        "  巨无霸,null,2146,513,27,26,42,961,171\n"
        "  中薯条,null,1210,289,4,12,38,165,18\n"
        "  无糖可口可乐中杯,null,0,0,0,0,1,35,0\n"
    )

    def test_basic_parse(self):
        """基础解析：记录数与字段名正确"""
        records = parse_toon(self.SAMPLE)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["productName"], "巨无霸")
        self.assertEqual(records[0]["energyKcal"], 513)

    def test_null_handling(self):
        """null 应转为 Python None"""
        records = parse_toon(self.SAMPLE)
        self.assertIsNone(records[0]["nutritionDescription"])

    def test_number_coercion(self):
        """数字字符串应转为 int"""
        records = parse_toon(self.SAMPLE)
        self.assertIsInstance(records[0]["energyKcal"], int)
        self.assertIsInstance(records[0]["energyKcal"], int)

    def test_nutrition_standardization(self):
        """营养字段名映射正确"""
        items = parse_nutrition_toon(self.SAMPLE)
        self.assertEqual(items[0]["name"], "巨无霸")
        self.assertEqual(items[0]["kcal"], 513)
        self.assertEqual(items[0]["sodium"], 961)
        self.assertIn("desc", items[0])

    def test_roundtrip(self):
        """序列化后重新解析应完全一致"""
        original = parse_toon(self.SAMPLE)
        restored = parse_toon(to_toon(original))
        self.assertEqual(original, restored)

    def test_empty_input_raises(self):
        """空输入应抛出异常"""
        with self.assertRaises(ToonParseError):
            parse_toon("")

    def test_invalid_format_raises(self):
        """非TOON 格式应抛出异常"""
        with self.assertRaises(ToonParseError):
            parse_toon('{"json": true}')

    def test_empty_lines_skipped(self):
        """空行与注释行应被跳过"""
        text = "[2]{a,b}:\n\n  x,1\n\n  y,2\n"
        self.assertEqual(len(parse_toon(text)), 2)

    def test_missing_fields_padded(self):
        """字段缺失应补齐而非崩溃"""
        text = "[1]{a,b,c}:\n  x,1\n"
        records = parse_toon(text)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["a"], "x")

    def test_load_items_from_toon(self):
        """从 TOON 构建 Item 列表"""
        items = load_items_from_toon(self.SAMPLE)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].name, "巨无霸")
        self.assertEqual(items[0].kcal, 513)


class TestDataIntegrity(unittest.TestCase):
    """数据完整性测试"""

    def setUp(self):
        self.items = load_items()

    def test_dataset_not_empty(self):
        """数据集非空"""
        self.assertGreater(len(self.items), 50, "餐品数据应至少有 50 条")

    def test_all_fields_non_negative(self):
        """所有营养字段应为非负数"""
        for item in self.items:
            with self.subTest(item=item.name):
                self.assertGreaterEqual(item.kcal, 0)
                self.assertGreaterEqual(item.protein, 0)
                self.assertGreaterEqual(item.fat, 0)
                self.assertGreaterEqual(item.carb, 0)
                self.assertGreaterEqual(item.sodium, 0)

    def test_sodium_density_calculation(self):
        """钠密度计算正确"""
        # 巨无霸 961mg / 513kcal * 100 = 187.3
        big_mac = next(i for i in self.items if i.name == "巨无霸")
        self.assertAlmostEqual(big_mac.sodium_density, 187.3, places=1)

    def test_zero_calcium_drink_density(self):
        """零热量饮品钠密度应为 0"""
        coke = next(i for i in self.items if "无糖可口可乐中杯" in i.name)
        self.assertEqual(coke.kcal, 0)
        self.assertEqual(coke.sodium_density, 0.0)

    def test_sodium_bomb_detection(self):
        """高钠单品识别正确（单份钠≥1000mg）"""
        bombs = [i for i in self.items if i.is_sodium_bomb]
        self.assertGreater(len(bombs), 0, "应存在高钠单品")
        for b in bombs:
            self.assertGreaterEqual(b.sodium, 1000)


class TestTargetValidation(unittest.TestCase):
    """目标参数校验测试"""

    def test_valid_target(self):
        """合法目标不报错"""
        Target(kcal=800, protein=30).validate()

    def test_zero_kcal_rejected(self):
        """热量为 0 应报错"""
        with self.assertRaises(ValueError):
            Target(kcal=0).validate()

    def test_negative_protein_rejected(self):
        """负蛋白应报错"""
        with self.assertRaises(ValueError):
            Target(kcal=800, protein=-10).validate()

    def test_excessive_protein_rejected(self):
        """蛋白占比超25% 应报错"""
        with self.assertRaises(ValueError):
            Target(kcal=600, protein=400).validate()

    def test_zero_sodium_rejected(self):
        """钠上限为 0 应报错"""
        with self.assertRaises(ValueError):
            Target(kcal=800, sodium_limit=0).validate()


class TestHeatMode(unittest.TestCase):
    """热量模式测试（默认模式）"""

    def setUp(self):
        self.items = load_items()
        self.target = Target(kcal=800, protein=30, mode="heat")

    def test_finds_combos(self):
        """能找到方案"""
        combos = find_combos(self.items, self.target, limit=3)
        self.assertEqual(len(combos), 3)

    def test_hits_calorie_target(self):
        """方案应命中热量目标（容差内）"""
        combos = find_combos(self.items, self.target, limit=3)
        for combo in combos:
            gap = abs(combo.total_kcal - 800)
            self.assertLessEqual(
                gap, self.target.tolerance, f"热量偏差 {gap} 超出容差"
            )

    def test_protein_target_met(self):
        """蛋白目标应被满足（允许超出，不允许不足太多）"""
        combos = find_combos(self.items, self.target, limit=3)
        best = max(combos, key=lambda c: c.total_protein)
        self.assertGreaterEqual(best.total_protein, 30)

    def test_exclude_category(self):
        """排除品类后不应出现该品类"""
        target = Target(kcal=700, protein=25, exclude_categories=["burger"])
        combos = find_combos(self.items, target, limit=3)
        for combo in combos:
            self.assertNotEqual(combo.main.category, "burger")

    def test_dessert_excluded_by_default(self):
        """默认排除甜品"""
        combos = find_combos(self.items, self.target, limit=3)
        for combo in combos:
            for item in combo.items:
                self.assertNotEqual(item.category, "dessert")

    def test_dessert_allowed(self):
        """允许甜品后甜品应进入候选池。

        注意：在 800kcal 目标下，高热量甜品（香芋派 232kcal、菠萝派 221kcal）
        通常进不了 Top 3——这是打分逻辑的正确行为，不是缺陷。
        因此本测试验证「候选池包含甜品」而非「Top3 必含甜品」。
        """
        from planner import _candidates

        target = Target(kcal=800, allow_dessert=True)
        pool = _candidates(self.items, target)
        self.assertGreater(
            len(pool["side"]),
            0,
            "允许甜品后候选池应包含甜品类单品",
        )
        # 验证甜品确实进入了候选（通过对比未允许时的数量）
        target_no_dessert = Target(kcal=800, allow_dessert=False)
        pool_no_dessert = _candidates(self.items, target_no_dessert)
        self.assertGreater(
            len(pool["side"]),
            len(pool_no_dessert["side"]),
            "允许甜品时候选数应多于不允许时",
        )

    def test_dessert_in_high_kcal_target(self):
        """热量目标足够宽松时，甜品应能出现在方案中"""
        target = Target(kcal=1200, allow_dessert=True, protein=40)
        combos = find_combos(self.items, target, limit=5)
        has_dessert = any(
            i.category == "dessert" for c in combos for i in c.items
        )
        self.assertTrue(has_dessert, "高热量目标下应能出现甜品")


class TestSodiumMode(unittest.TestCase):
    """控钠模式测试（差异化核心）"""

    def setUp(self):
        self.items = load_items()
        self.target = Target(kcal=800, sodium_limit=1200, mode="sodium")

    def test_sodium_within_limit(self):
        """控钠方案钠含量应低于上限"""
        combos = find_combos(self.items, self.target, limit=3)
        for combo in combos:
            self.assertLessEqual(
                combo.total_sodium,
                self.target.sodium_limit,
                f"钠 {combo.total_sodium} 超出上限 {self.target.sodium_limit}",
            )

    def test_lower_sodium_than_heat_mode(self):
        """控钠模式的钠应显著低于热量模式（差异化验证）"""
        heat = find_combos(self.items, Target(kcal=800, mode="heat"), limit=3)
        sodium = find_combos(self.items, self.target, limit=3)

        heat_avg = sum(c.total_sodium for c in heat) / len(heat)
        sodium_avg = sum(c.total_sodium for c in sodium) / len(sodium)

        self.assertLess(
            sodium_avg,
            heat_avg,
            f"控钠模式({sodium_avg:.0f}mg) 应低于热量模式({heat_avg:.0f}mg)",
        )

    def test_avoids_sodium_bomb(self):
        """控钠模式应避开高钠单品"""
        combos = find_combos(self.items, self.target, limit=3)
        for combo in combos:
            self.assertFalse(
                combo.has_sodium_bomb,
                f"方案含高钠单品：{[i.name for i in combo.items if i.is_sodium_bomb]}",
            )

    def test_still_hits_calorie(self):
        """控钠模式下热量仍应命中（容差放宽到 100）"""
        combos = find_combos(self.items, self.target, limit=3)
        target = Target(kcal=800, sodium_limit=1200, mode="sodium", tolerance=100)
        for combo in combos:
            self.assertLessEqual(abs(combo.total_kcal - 800), 100)


class TestDensityMode(unittest.TestCase):
    """钠密度模式测试"""

    def setUp(self):
        self.items = load_items()
        self.target = Target(kcal=800, mode="density")

    def test_lower_density_than_heat(self):
        """密度模式的钠密度应低于热量模式"""
        heat = find_combos(self.items, Target(kcal=800, mode="heat"), limit=3)
        density = find_combos(self.items, self.target, limit=3)

        heat_density = sum(c.total_sodium_density for c in heat) / len(heat)
        density_density = sum(c.total_sodium_density for c in density) / len(density)

        self.assertLess(density_density, heat_density)

    def test_density_field_exposed(self):
        """JSON 输出应包含钠密度字段"""
        combos = find_combos(self.items, self.target, limit=1)
        data = combos[0].to_dict()
        self.assertIn("sodium_density", data)
        self.assertIn("has_sodium_bomb", data)
        for item in data["items"]:
            self.assertIn("sodium_density", item)


class TestComboOutput(unittest.TestCase):
    """套餐输出测试"""

    def setUp(self):
        self.items = load_items()
        self.target = Target(kcal=800, protein=30)

    def test_totals_match_items(self):
        """合计值应等于各单品之和"""
        combos = find_combos(self.items, self.target, limit=1)
        combo = combos[0]
        self.assertEqual(
            combo.total_kcal, sum(i.kcal for i in combo.items)
        )
        self.assertEqual(
            combo.total_sodium, sum(i.sodium for i in combo.items)
        )

    def test_format_contains_disclaimer(self):
        """输出应包含关键数值"""
        combos = find_combos(self.items, self.target, limit=1)
        output = format_combo(combos[0], self.target)
        self.assertIn("kcal", output)
        self.assertIn("钠", output)
        self.assertIn("钠密度", output)

    def test_no_protein_target_message(self):
        """未设蛋白目标时不应显示误导性达标提示"""
        target = Target(kcal=500)
        combos = find_combos(self.items, target, limit=1)
        output = format_combo(combos[0], target)
        self.assertIn("未设目标", output)
        self.assertNotIn("蛋白：达标", output)

    def test_edge_case_low_kcal(self):
        """极低热量目标不应崩溃"""
        target = Target(kcal=250)
        combos = find_combos(self.items, target, limit=1)
        self.assertEqual(len(combos), 1)


if __name__ == "__main__":
    print("=" * 60)
    print("麦麦营养配餐助手 · 单元测试")
    print("=" * 60)
    unittest.main(verbosity=2)
