# WorkBuddy 开发对话上下文

本文件记录本项目使用腾讯 WorkBuddy 智能体开发的完整对话上下文，用于核验是否符合 WorkBuddy 专项奖励条件。

- **开发工具**：腾讯 WorkBuddy
- **开发时间**：2026-10-09
- **使用的 MCP**：麦当劳中国 MCP Server（`mcd-mcp`）
- **开发阶段**：MCP 接入验证 → 能力边界实测 → 选题决策 → 引擎开发 → 文档编写

---

## 阶段一：赛事规则解析

**用户诉求**：分析麦当劳开发活动赛事规则，判断如何参赛更合适。

**助手工作**：
1. 解析微信公众号文章，提取赛事基本信息
2. 抓取 GitHub 官方仓库 `M-China/mcd-developer-innovation-challenge`，逐条核实活动规则
3. 从 `activityGuidelines.md` 提取排名机制、必交文件清单、奖励设置
4. 输出 A/B/C 三个选题方案并给出推荐

**关键发现**：
- 排名**纯看GitHub公开 Star 数**，10/26 00:00 定榜
- 前 100 名进入获奖范围，Top3 得巨无霸兑换券
- 提交 `workbuddy.md` 可额外获得 3000 WorkBuddy 积分（前 100 名）
- 必交五件套：README.md / CONTEST_DECLARATION.md / MCP_INTEGRATION.md / mcp-config.example.json / workbuddy.md
- 仓库创建时间必须在 2025-12-25 至 2026-10-25 之间（影响开发排期）

---

## 阶段二：MCP Token 获取路径排查

**用户问题**：截图反馈 open.mcd.cn 弹出「商户登录」无法注册，询问是否通过「申请合作」入口。

**助手工作**：
1. 抓取 https://open.mcd.cn/mcp 与 /mcp/doc 页面，核实官方 Token 申请流程
2. 判定「商户登录」与「申请合作」均属 B端商务通道，非开发者入口
3. 给出正确路径：MCP 平台右上角【登录】→ 手机号验证码 → 【控制台】→ 【激活】→ 同意协议
4. 提供备选方案：手机浏览器、400-920-0205 客服

**结论**：MCP 平台入口免注册，手机号验证即自动注册。

---

## 阶段三：MCP 配置与连接排障

**用户反馈**：写入 mcp.json 后在连接器列表找不到 mcd-mcp。

**助手工作**：
1. 读取 `C:\Users\034\.workbuddy\mcp.json` 确认配置已正确写入
2. 查证 WorkBuddy 官方文档中连接器与 MCP 配置说明
3. 诊断根因：WorkBuddy 启动时读取 MCP 配置，写入后需**完全重启进程**才会加载
4. 同时调整 `type` 字段为 `streamable-http`，与环境中已正常运行的 anysearch 条目保持一致
5. 准备降级方案（`type: "http"` + 完整路径 `/mcp-servers/mcd-mcp`）

**用户操作**：重启 WorkBuddy → 连接器页【信任】→ 【启用】
**结果**：mcd-mcp 显示「35/35 个工具已启用」。

---

## 阶段四：MCP 能力边界实测

**助手工作**：使用 ToolSearch 加载工具 schema，通过 DeferExecuteTool 执行真实调用，验证 5 个接口：

| Tool | 结果 | 关键发现 |
|---|---|---|
| `now-time-info` | 成功 | GMT+08:00 时间正确，服务器校时准确 |
| `list-nutrition-foods` | 成功 | 返回 **160 条** TOON 格式营养数据 |
| `campaign-calendar` | 成功 | 返回 10月全月活动，含 13 个日期节点 |
| `available-coupons` | 成功 | 返回 9 张券，区分「可领取/已领取」 |
| `query-nearby-stores` | **失败** | 报`600050 收藏餐厅列表为空`，两次不同参数均复现 |

**关键决策**：
1. `list-nutrition-foods` 返回 160 条带完整营养数值的餐品数据 → 确认「营养量化计算」类选题技术完全成立，不需靠菜单文案估算
2. `query-nearby-stores` 稳定失败 → **否决**依赖门店定位的选题（原A 方案「家庭餐桌规划师」Demo会跑不通）
3. 调整方案为「营养计算（默认）+ 今日券补充（不依赖定位）」的融合架构

---

## 阶段五：引擎开发与验证

**用户决策**：确认融合方案，立即开工。

**助手工作**：
1. 从官方仓库下载 `CONTEST_DECLARATION.md` 原文（内容不可修改）
2. 从 MCP 返回中筛选 75 条常用单品，转换为 JSON 存入 `references/nutrition-data.json`，附加 `_meta` 块记录来源与采集时间
3. 开发 `planner.py` 计算引擎（约 400 行，零第三方依赖）：
   - 数据加载层（MCP 实时刷新预留 + 本地快照回退）
   - `Target` / `Item` / `Combo` 数据类
   - 候选枚举 + 热量剪枝 + 多维打分 + 去重
   - 差值计算与调整建议生成
   - CLI 入口，支持 7 个参数与 JSON 输出
4. 四组场景实测：
   - 800 kcal / 30g 蛋白 → 精确命中 800 kcal
   - 500 kcal 无蛋白目标 → 精确命中 500 kcal
   - 700 kcal 排除 burger → 精确命中 700 kcal
   - JSON 输出 → 结构正确
5. **发现并修复 bug**：未设蛋白目标时输出「蛋白：达标（超出 25g）」的误导性表述，改为「25 g（未设目标，仅供参考）」

---

## 阶段六：文档编写与安全检查

**助手工作**：
1. 编写 `SKILL.md`（含已验证路径与失败回退两节）
2. 编写 `README.md`（含四组真实运行输出示例、计算逻辑说明、已知局限）
3. 编写 `MCP_INTEGRATION.md`（含 3 个实际调用 Tool 的详细说明、明确未使用 Tool 的原因、完整调用流程图）
4. 编写 `mcp-config.example.json`，仅含 `${MCD_MCP_TOKEN}` 环境变量占位符
5. 安全检查：全目录 grep 确认无真实 Token 泄露

---

## 阶段七：仓库创建与推送

**助手工作**：
1. 检查环境：`git 2.55.0` 已安装，但 `user.name`/`user.email` 未配置，`gh` 命令行未安装，GitHub SSH 未授权
2. 分析用户在 GitHub 创建的空仓库页面截图，确认仓库名 `xue034/mcd-meal-planner`、可见性 Public
3. 执行 `git init -b main`，以**仓库级**（非全局）配置身份 `xue034` / `xue034@users.noreply.github.com`，避免污染用户全局配置
4. `git add .` 后逐项核验暂存清单：8 个顶层文件 + `references/` 目录，无多余文件
5. **提交前安全审查**（两道）：
   - 暂存区全文 grep 真实 Token 字符串 → 无命中
   - 正则扫描硬编码凭证模式（`bearer [a-z0-9]{20,}`、`token": "..."`、`sk-...`）→ 无命中
6. 首次提交 `1f25fdd`，关联远程 `https://github.com/xue034/mcd-meal-planner.git`

**遇到的故障与排查过程**：

| 现象 | 根因 | 处理 |
|---|---|---|
| `git push` 报 `CONNECT tunnel failed, response 502` | 环境变量代理 `127.0.0.1:64218` 失效 | 排查系统代理配置，探测 7 个常见代理端口（7890/7897/10809/10808/1080/8888/33210）均无响应，判定需用户重启代理客户端 |
| 代理恢复后推送 | — | `git push -u origin main` 成功 |

**用户反馈**：网络恢复后推送一次通过，GitHub 页面确认 8 个文件 + 1 目录全部就位。

**助手补充动作**：
1. 通过 GitHub API 远程核验文件清单，确认推送完整
2. 发现截图右侧栏 License 显示「暂无」，而 README 声明 MIT → 补建 `LICENSE` 文件（MIT 全文 + 数据来源声明），提交 `fd39db2` 并推送成功

---

## 阶段八：推广规划

**助手工作**：
1. 明确推广核心逻辑：**Star 是排名唯一依据**，需按人群分层设计
2. 产出 `promotion-kit.md`，含：
   - 目标人群痛点分析（减脂健身圈 / 程序员技术圈 / AI 工具圈，优先级排序）
   - 3 版朋友圈文案（痛点共鸣型 / 技术向 / 极简型）
   - 技术社区长文模板（掘金/CSDN/知乎/V2EX），以 TOON 解析和接口踩坑为差异化角度
   - 16 天倒排推广节奏表
   - GitHub 优化清单（Topics 标签等）
   - 规则红线避坑清单
3. **主动否决 9.9 元付费方案**：识别出规则禁止「宣扬奢靡浪费、拜金主义」，且付费咨询与参赛作品定位冲突，改为推荐「免费帮算前 20 位」的安全版本

---

## WorkBuddy 在本次开发中的实际作用

| 环节 | WorkBuddy 的作用 |
|---|---|
| 规则解析 | 抓取并逐条核实官方规则文档，提取关键约束 |
| 故障排查 | 定位 MCP 配置未加载的根因并给出降级方案 |
| 能力实测 | 通过工具调用真实执行 MCP 接口，获取一手数据 |
| 选题决策 | 基于实测结果推翻原方案，避免做跑不通的产品 |
| 引擎开发 | 生成 400 行零依赖计算引擎并实测四组场景 |
| 文档编写 | 生成含真实数据的三份参赛文档 |
| 安全审查 | 两道grep 校验，防止 Token 泄露到提交物 |
| 版本管理 | 仓库级 git 身份配置 + 提交前安全审查 + 推送排障 |
| 推广策划 | 输出分层推广素材包，并主动规避合规风险 |

---

## 交付物清单

| 文件 | 说明 |
|---|---|
| `planner.py` | 400 行零依赖计算引擎 |
| `references/nutrition-data.json` | 75 条 MCP 真实营养数据快照 |
| `SKILL.md` | Skill 定义（含已验证路径 + 失败回退） |
| `README.md` | 项目介绍（含4 组真实运行输出） |
| `MCP_INTEGRATION.md` | 3 个 Tool 详解 + 完整调用流程图 |
| `CONTEST_DECLARATION.md` | 官方声明文件（原文，未修改） |
| `workbuddy.md` | 本文件，WorkBuddy 开发上下文 |
| `mcp-config.example.json` | 脱敏 MCP 配置（仅环境变量占位符） |
| `LICENSE` | MIT 许可 |
| `.gitignore` | 防凭证泄露 |

**GitHub 仓库**：https://github.com/xue034/mcd-meal-planner
**提交记录**：`1f25fdd`（初始提交）→ `fd39db2`（添加 LICENSE）

---

*本项目为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品。*

