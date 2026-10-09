<div align="center">

# 🥗 麦麦营养配餐助手 · mcd-meal-planner

### 按热量与钠双目标，从麦当劳真实菜单算出精确到克的套餐

[![Skill](https://img.shields.io/badge/Type-MCP%20Skill-ffc72c?style=for-the-badge&labelColor=27251F)](https://github.com/xue034/mcd-meal-planner)
[![Powered by mcd-mcp](https://img.shields.io/badge/Powered%20by-mcd--mcp-FFC72C?style=for-the-badge&labelColor=27251F)](https://open.mcd.cn/mcp)
[![License](https://img.shields.io/badge/License-MIT-27251F?style=for-the-badge&labelColor=27251F)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-37%20passed-38a169?style=for-the-badge)](tests/test_planner.py)

</div>

---

## 别人怎么帮你点麦当劳 vs. 我们怎么帮你点

市面上的"AI 帮你点麦当劳"给的是这样的建议：

> "推荐巨无霸搭配中薯，可乐换成无糖更健康。"

问题在于——**没有数字**。你知道自己要控制热量，但得不到「这个组合多少大卡」「距目标差多少」「怎么调整最省事」。

本项目把麦当劳 MCP 接口返回的 **160 条真实营养数据**（能量/蛋白/脂肪/碳水/钠/钙）建成可计算数据集，给出精确到克的方案与差值。

**🎯 更关键的是：我们做了控钠维度，而这是麦当劳官方数据里被大多数人忽略的部分。**

---

## 💡 核心洞察：低热量 ≠ 低钠

用实测数据看这两句话的差别：

| |热量 | 钠 | 钠密度 |
|---|---:|---:|---:|
| **雪菜脆笋鸡肉粥** | 120 kcal | 552 mg | **460.0** mg/100kcal |
| **巨无霸** | 513 kcal | 961 mg | 187.3 mg/100kcal |

那碗粥热量只有巨无霸的 **1/4**，但钠密度是巨无霸的 **2.5 倍**。

很多人以为"点个清淡的粥就没事了"——**恰恰相反**。粥类是麦当劳菜单里钠密度最高的品项之一。

这不是文字游戏，是**同为 800 大卡的两个方案，钠含量能差 3 倍**：

| 方案 | 组合 | 热量 | 钠 |
|---|---|---:|---:|
| 普通热量模式 | 巨无霸 + 鸡肉粥 + 拿铁 | 800 kcal | **1601 mg**（上限 80%） |
| **控钠模式** | 麦乐鸡4块 + 大薯条 + 可乐 | 773 kcal | **553 mg**（上限 28%） |

**同样的热量目标，钠含量 1601mg vs 553 mg。**

📊 **[在线演示：docs/demo.html](docs/demo.html)**（浏览器直接打开，含完整数据对比）

---

## ✨ 核心特性

| 特性 | 说明 |
|---|---|
| 🎯 **双目标计算** | 热量、蛋白、钠同时约束，输出精确到克的方案与差值 |
| 🧂 **控钠模式** | `--sodium-focus` 优先低钠组合，超钠重罚 |
| 📊 **钠密度指标** | `--density-focus` 按 mg/100kcal 排序，避开高钠陷阱 |
| ⚠️ **高钠预警** | 单份钠≥1000mg 的「钠炸弹」自动标记 |
| 🔄 **调整建议** | 没命中目标时，直接告诉你"换哪个单品能省多少" |
| 🎟️ **今日券叠加** | 补充当日可领优惠券（不依赖门店定位） |
| 🔌 **离线可跑** | MCP 不可用时回退本地快照，功能不中断 |
| 📦 **可编程** | `--json` 输出，便于接入饮食记录工具 |
| 🧪 **有测试** | 37 个单元测试全部通过 |

---

## 🚀 快速开始

**零依赖**，仅需 Python 3.10+：

```bash
git clone https://github.com/xue034/mcd-meal-planner.git
cd mcd-meal-planner
```

### 控钠模式（推荐先试这个）

```bash
python planner.py --kcal 800 --sodium-limit 1200 --sodium-focus
```

```
模式：控钠模式
目标：800 kcal
钠上限：1200 mg
数据源：MCP list-nutrition-foods（共 75 条餐品，本地快照）

【方案 1】
========================================================
推荐套餐（控钠模式）
========================================================
  · 麦乐鸡4块        170 kcal | 蛋白 10g | 钠  337mg (198.2/100kcal)
  · 大薯条           379 kcal | 蛋白  6g | 钠  216mg ( 57.0/100kcal)
  · 可乐大杯         224 kcal | 蛋白   0g | 钠    0mg (  0.0/100kcal)
--------------------------------------------------------
   合计  773 kcal | 蛋白 16g | 脂肪 26g | 碳水 116g
   钠 553 mg（占上限 46%）| 钙 45 mg | 钠密度 71.5 mg/100kcal
--------------------------------------------------------
 钠：553 mg，低于上限 647 mg ✓
 热量：命中目标（偏差 -27 kcal）
========================================================
```

### 其他用法

```bash
# 热量模式（默认）
python planner.py --kcal 800 --protein 30

# 钠密度模式（避开高钠陷阱）
python planner.py --kcal 800 --density-focus

# 高钠陷阱预警报告
python planner.py --kcal 800 --sodium-report

# 排除某些品类
python planner.py --kcal 700 --protein 25 --exclude burger

# JSON 输出（接入其他应用）
python planner.py --kcal 800 --sodium-focus --json

# 跑测试
python tests/test_planner.py
```

### 接入麦当劳 MCP（可选，用于实时券与活动）

1. 访问 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 右上角【登录】→ 手机号验证
2. 登录后点【控制台】→【激活】→ 同意协议 → 复制 MCP Token
3. 设置环境变量 `export MCD_MCP_TOKEN="你的Token"`
4. 参考 `mcp-config.example.json` 配置你的 MCP Client

> ⚠️ 配置只使用环境变量占位符 `${MCD_MCP_TOKEN}`，请勿把真实 Token 提交到版本库。

### 作为 WorkBuddy Skill 使用

```bash
git clone https://github.com/xue034/mcd-meal-planner ~/.workbuddy/skills/mcd-meal-planner
```

重启 WorkBuddy 后直接提问：

> "晚饭 800 大卡，要 30g 蛋白，帮我控制钠"

---

## 📊 为什么钠维度值得单独做

实测 75 条单品数据后，我们发现三件事：

**1. 成人建议钠上限 2000mg，一个汉堡能吃掉 69%**

| 餐品 | 钠 | 占上限 |
|---|---:|---:|
| 芝士双层安格斯厚牛堡 | 1373 mg | **69%** |
| 麦辣鸡腿汉堡 | 1208 mg | 60% |
| 板烧鸡腿堡 | 1041 mg | 52% |

**2. 主食类几乎全部高钠，真正低钠的只有饮品**

钠 <150mg 的品项：可乐（0mg）、雪碧（29mg）、优品豆浆小杯（32mg）、纯牛奶（73mg）。

**3. 我们选择诚实告知，而不是虚假承诺**

实测确认：麦当劳现有菜单内，**严格低钠的主食基本不存在**。本工具能做的是在约束下找到最优解，并明确告知可行边界——而不是硬凑一个"看起来健康"的组合。

这个诚实是有价值的：控钠人群（高血压、肾病患者、孕妇、老人）需要的正是这种确定性。

---

## 🔧 技术实现

### 架构

```
用户需求（自然语言）
    │
    ├─ Step 1  解析目标：热量 / 蛋白 / 钠上限 / 模式
    │
    ├─ Step 2  营养数据获取
    │          MCP list-nutrition-foods
    │          → TOON 解析（toon_parser.py）
    │          → 筛选 75 条常用单品
    │          → 失败时回退本地快照
    │
    ├─ Step 3  候选枚举：主食(35) × 配餐(20) × 饮品(15) ≈ 1.1 万组合
    │
    ├─ Step 4  剪枝：总热量 > 目标 × 1.5 直接丢弃
    │
    ├─ Step 5  多维打分（按模式切换权重）
    │          heat    ：热量偏离×1.0 + 蛋白缺口×8.0 + 钠超限×0.5
    │          sodium  ：钠超限×12.0 + 钠密度×1.5 + 热量×0.6
    │          density ：钠密度×3.0 + 热量×0.5 + 钠超限×8.0
    │
    ├─ Step 6  差值计算 + 具体调整建议
    │
    └─ Step 7  输出（先数字结论，再调整建议）
```

### 钠密度：本项目引入的指标

```
钠密度 = 钠(mg) / 热量(kcal) × 100
```

**为什么这个指标有用**：同样 1000mg 钠，分配到 2000kcal 上和分配到 400kcal 上，健康负担完全不同。只看「总钠」会误判。

实测对比（钠密度 TOP 5）：

| 餐品 | 钠 | 热量 | 钠密度 |
|---|---:|---:|---:|
| 雪菜脆笋鸡肉粥 | 552 mg | 120 kcal | 460.0 |
| 皮蛋鸡肉粥 | 611 mg | 133 kcal | 459.4 |
| 德式图林根香肠 | 293 mg | 87 kcal | 336.8 |
| 薄皮焦香V翅 | 594 mg | 192 kcal | 309.4 |
| 酥酥多笋卷 | 1044 mg | 342 kcal | 305.3 |

---

## 🧩 TOON 格式解析（接入此接口必踩的坑）

麦当劳 MCP 的 `list-nutrition-foods` **不返回标准 JSON**，而是返回 **TOON**（Token-Oriented Object Notation）——官方文档说明是为降低 LLM Token 消耗。

直接用 `json.loads()` 会抛 `JSONDecodeError`。真实返回长这样：

```
[160]{productName,nutritionDescription,energyKj,energyKcal,protein,fat,carbohydrate,sodium,calcium}:
  巨无霸,null,2146,513,27,26,42,961,171
  中薯条,null,1210,289,4,12,38,165,18
  儿童鱼排堡,null,1126,269,15,6,36,442,58
```

**格式规则**：
1. 首行 `[N]{f1,f2,...,fk}:` —— N 为记录数，fk 为字段名
2. 后续每行一条记录，逗号分隔，顺序与字段名一一对应
3. 空值为字面量 `null`
4. 可选 `#` 开头的表头注释行

本项目实现了完整解析（`toon_parser.py`），包含：空行跳过、注释忽略、字段缺失补齐、往返转换校验。

```python
from toon_parser import parse_nutrition_toon

records = parse_nutrition_toon(mcp_response)
# → [{'name': '巨无霸', 'kcal': 513, 'protein': 27, 'sodium': 961, ...}, ...]
```

**代码可直接复用**，如果你也要接这个接口。

---

## 🚫 这个项目刻意不做的事

**不调用 `query-nearby-stores`。**

实测该接口对未收藏门店的用户返回：

```json
{"success":false,"code":600050,"message":"收藏餐厅列表为空，请您提供城市+关键词进行搜索"}
```

换 `city="厦门"`、`keyword="思明"` 都一样，两次不同参数稳定复现——这不是用法问题，是接口设计有前置依赖。

**依赖它的方案，在真实用户场景下会直接失败。** 本项目主动放弃「就近门店」能力，优惠券直接读用户账户（`available-coupons`），换取全场景稳定可用。

**不接入下单链路。** 本项目是营养规划工具，不介入交易流程，避免误下单风险。

---

## 📁 项目结构

```
mcd-meal-planner/
├── planner.py                      计算引擎（零第三方依赖）
├── toon_parser.py                  TOON 格式解析器
├── SKILL.md                        WorkBuddy Skill 定义
├── tests/
│   └── test_planner.py37 个单元测试
├── docs/
│   └── demo.html                   可视化演示页
├── references/
│   └── nutrition-data.json         75 条 MCP 真实数据快照
├── README.md
├── MCP_INTEGRATION.md              MCP 集成说明
├── CONTEST_DECLARATION.md          官方声明（原文）
├── workbuddy.md                    WorkBuddy 开发上下文
├── mcp-config.example.json         脱敏 MCP 配置
├── LICENSE
└── .gitignore
```

---

## 🧪 测试

```bash
$ python tests/test_planner.py
Ran 37 tests in 1.157s
OK
```

覆盖范围：TOON 解析（9 项）、数据完整性（5 项）、参数校验（5 项）、热量模式（6 项）、控钠模式（4 项）、密度模式（2 项）、输出格式（6 项）。

控钠模式的测试包含**差异化验证**——断言控钠模式的钠含量显著低于热量模式，且必定避开高钠单品。

---

## 👥 目标用户

| 用户 | 典型诉求 |
|---|---|
| 控压/控钠人群 | 「高血压能怎么点麦当劳」——需要钠含量可见、可替换 |
| 减脂期人群 | 「500 大卡以内吃什么」——需要精确热量而非模糊建议 |
| 增肌人群 | 「30g 蛋白怎么凑」——需要蛋白数达标 |
| 家庭用户 | 「带孩子吃什么」——儿童餐低热量选择 |
| 健身 + 餐饮爱好者 | 可导出 JSON 做饮食记录 |

---

## ⚠️ 已知局限

1. **不支持门店定位**——`query-nearby-stores` 依赖收藏门店，因此不做「就近门店有什么券」查询
2. **营养数据为快照**——采集于 2026-10-09，菜品会更新，**以官方实时数据为准**
3. **不含价格**——未接 `calculate-price`，只做营养维度
4. **钠上限 2000mg** 依据一般成人膳食建议值，**高血压、肾病患者请遵医嘱**
5. **严格低钠主食在菜单内基本不存在**——本工具给最优解并诚实告知边界

---

## 📜免责声明

本项目为**麦当劳程序员创意开发大赛参赛作品**，由参赛者独立开发，**非麦当劳官方产品**。

本项目输出仅供参考，**不构成医疗、营养或其他专业建议**。餐品信息、价格及供应状态以麦当劳官方渠道的实时结果为准。营养数据为接口调用时的快照，可能与实际出品存在差异。

---

## License

MIT · 数据来源：麦当劳中国 MCP Server `list-nutrition-foods`（采集时间 2026-10-09T15:17:11+08:00）

---

<div align="center">

**觉得有用的话，点个 ⭐ Star 支持一下！**

Star 越多排名越靠前，这是麦当劳官方开发赛的排名依据。

</div>
