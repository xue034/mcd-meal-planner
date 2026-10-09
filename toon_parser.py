#!/usr/bin/env python3
"""
TOON 格式解析器 (TOON Parser)
==============================

麦当劳中国 MCP Server 的 `list-nutrition-foods` 接口**不返回标准 JSON**，
而是返回 TOON（Token-Oriented Object Notation）——一种为降低 LLM Token
消耗而设计的紧凑行格式。

官方接口文档明确说明："为降低 LLM Token 消耗，营养信息采用紧凑的 TOON
(Token-Oriented Object Notation) 格式返回，而非标准 JSON 数组格式。"

TOON 格式样例（真实接口返回）：

    [160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
      猪柳麦满分,null,1288,308,16,16,24,781,213
      中薯条,null,1210,289,4,12,38,165,18
      巨无霸,null,2146,513,27,26,42,961,171

格式规则：
1. 首行 `[N]{f1,f2,...,fk}:` —— N 为记录数，fk 为字段名列表
2. 后续每行一条记录，字段值以逗号分隔，顺序与首行字段名一一对应
3. 空值为字面量 `null`
4. 可选的表头行以 `#` 开头（本接口实际返回中已省略）

直接用 json.loads() 解析会抛 JSONDecodeError，这是接入此接口最容易踩的坑。

作者：参赛作品，非麦当劳官方产品
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

__all__ = ["parse_toon", "parse_nutrition_toon", "to_toon", "ToonParseError"]


class ToonParseError(ValueError):
    """TOON 格式解析失败"""


# 首行模式：[N]{field1,field2,...}:
_HEADER_RE = re.compile(r"^\s*\[(\d+)\]\s*\{([^}]*)\}\s*:\s*$")

# 表头注释行：# field1,field2,...
_COMMENT_RE = re.compile(r"^\s*#\s*(.+?)\s*$")


def parse_toon(text: str) -> List[Dict[str, Any]]:
    """解析 TOON 格式文本，返回字典列表。

    Args:
        text: TOON 格式的完整文本

    Returns:
        记录列表，每条记录是一个字典

    Raises:
        ToonParseError: 格式不合法

    Example:
        >>> data = parse_toon(
        ...     '[2]{name,kcal}:\\n'
        ...     '  巨无霸,513\\n'
        ...     '  中薯条,289\\n'
        ... )
        >>> data[0]['name']
        '巨无霸'
    """
    if not text or not text.strip():
        raise ToonParseError("输入为空")

    lines = text.strip().splitlines()

    # 定位表头行（允许前面有空行）
    header_idx = None
    for i, line in enumerate(lines):
        if _HEADER_RE.match(line):
            header_idx = i
            break

    if header_idx is None:
        raise ToonParseError(
            "未找到 TOON 表头行，期望格式：[N]{field1,field2,...}:\n"
            f"实际输入首行：{lines[0][:80]!r}"
        )

    match = _HEADER_RE.match(lines[header_idx])
    assert match is not None  # 已确保匹配
    declared_count = int(match.group(1))
    fields = [f.strip() for f in match.group(2).split(",")]

    records: List[Dict[str, Any]] = []

    for line in lines[header_idx + 1 :]:
        # 跳过空行
        if not line.strip():
            continue

        # 跳过注释行
        comment = _COMMENT_RE.match(line)
        if comment:
            continue

        # 去掉行首缩进
        content = line.strip()

        values = content.split(",")

        # 字段数不匹配时做防御性处理：补齐或截断
        if len(values) < len(fields):
            values.extend([""] * (len(fields) - len(values)))
        elif len(values) > len(fields):
            values = values[: len(fields)]

        record: Dict[str, Any] = {}
        for field, value in zip(fields, values):
            record[field] = _coerce(value.strip())
        records.append(record)

    if declared_count != len(records):
        # 不抛异常，只提示——接口可能分页或截断
        print(
            f"[警告] TOON 声明记录数 {declared_count}，实际解析 {len(records)} 条"
        )

    return records


def _coerce(value: str) -> Any:
    """把字符串值转换为合适的 Python 类型。"""
    if value == "null" or value == "":
        return None

    # 尝试转数字（含小数）
    try:
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
    except (TypeError, ValueError):
        pass

    return value


def parse_nutrition_toon(text: str) -> List[Dict[str, Any]]:
    """解析营养数据 TOON，返回标准化结构。

    将官方字段名映射为更易用的短名，并做类型转换。

    官方字段 → 标准字段映射：
        productName→ name
        nutritionDescription → desc
        energyKj       → kcal_kj
        energyKcal     → kcal
        protein        → protein
        fat            → fat
        carbohydrate   → carb
        sodium         → sodium
        calcium        → calcium

    Args:
        text: TOON 格式的完整文本

    Returns:
        标准化后的营养记录列表
    """
    raw = parse_toon(text)

    field_map = {
        "productName": "name",
        "nutritionDescription": "desc",
        "energyKj": "kcal_kj",
        "energyKcal": "kcal",
        "protein": "protein",
        "fat": "fat",
        "carbohydrate": "carb",
        "sodium": "sodium",
        "calcium": "calcium",
    }

    numeric_fields = {"kcal_kj", "kcal", "protein", "fat", "carb", "sodium", "calcium"}

    result: List[Dict[str, Any]] = []
    for row in raw:
        item: Dict[str, Any] = {}
        for src, dst in field_map.items():
            if src not in row:
                continue
            value = row[src]
            if dst in numeric_fields and value is not None:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = 0
            item[dst] = value
        # 名称缺失的记录直接跳过
        if not item.get("name"):
            continue
        result.append(item)

    return result


def to_toon(records: List[Dict[str, Any]], fields: Optional[List[str]] = None) -> str:
    """将记录列表序列化回 TOON 格式（用于测试和文档示例）。

    这是 parse_toon 的逆操作，可用于验证解析器的正确性。

    Args:
        records: 记录列表
        fields: 字段顺序，默认取第一条记录的键顺序

    Returns:
        TOON 格式文本
    """
    if not records:
        return "[]{}:\n"

    if fields is None:
        fields = list(records[0].keys())

    lines = [f"[{len(records)}]{{{','.join(fields)}}}:"]
    for record in records:
        values = []
        for field in fields:
            value = record.get(field)
            values.append("null" if value is None else str(value))
        lines.append("  " + ",".join(values))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 自测：python toon_parser.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    SAMPLE = """[5]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  猪柳麦满分,null,1288,308,16,16,24,781,213
  中薯条,null,1210,289,4,12,38,165,18
  巨无霸,null,2146,513,27,26,42,961,171
  儿童鱼排堡,null,1126,269,15,6,36,442,58
  无糖可口可乐中杯,null,0,0,0,0,1,35,0
"""

    print("=" * 60)
    print("TOON 解析器自测")
    print("=" * 60)

    records = parse_toon(SAMPLE)
    print(f"\n[1] 基础解析：{len(records)} 条记录")
    for r in records:
        print(f"    {r['productName']:<14} {r['energyKcal']:>4} kcal")

    nutrition = parse_nutrition_toon(SAMPLE)
    print(f"\n[2] 营养标准化：{len(nutrition)} 条")
    for r in nutrition:
        print(
            f"    {r['name']:<14} {r['kcal']:>4}kcal"
            f" 蛋白{r['protein']:>2}g 钠{r['sodium']:>4}mg"
        )

    roundtrip = parse_toon(to_toon(records))
    assert roundtrip == records, "往返转换不一致"
    print("\n[3] 往返转换：一致✓")

    edge = """[2]{a,b,c}:
  x,null,1

  y,2,null
"""
    print(f"\n[4] 空值处理：{parse_toon(edge)}")

    short = """[3]{a,b,c}:
  x,1
"""
    print(f"[5] 字段缺失补齐：{parse_toon(short)}")

    try:
        parse_toon("这不是 TOON 格式")
    except ToonParseError as e:
        print(f"\n[6] 错误处理：正常捕获 -> {str(e)[:40]}...")

    print("\n" + "=" * 60)
    print("全部自测通过")
    print("=" * 60)
