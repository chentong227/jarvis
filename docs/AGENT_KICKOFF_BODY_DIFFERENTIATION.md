# AGENT KICKOFF — 体之分化 (body-differentiation)

> **任何 agent / 新窗口接手"体分化"工程前, 先全文读本文件 (< 250 行)。**
> 它是这条轨道的单一入口 + 活进度看板。看完你应能回答: 我们在做什么 / 为什么 / 做到哪 / 我下一步具体做什么 / 哪些红线碰不得。
>
> 真理源: 需求 `.kiro/specs/body-differentiation/requirements.md` (R1-R19) · 设计 `.kiro/specs/body-differentiation/design.md` · 进度 = 本文件 §6 看板 (改完即更新)。

---

## 1. 一句话 — 我们在做什么

把 Jarvis 的"体" (关系流形 `RelationalManifold`) 从一坨 **blob** (124 节点里 112 个糊在唯一一个面) **分化**成多个**互相重叠、面间有桥**的语义面; 让体的形状**偏向外部实证节点**而非自产 thought; 把倾斜的持续从"时间衰减计时器"换成"**接地谓词门**"; 把体此刻被点亮的面**投影进说**; 给注意力加**迟滞**防横跳。

**为什么 (本体论定调, Sir)**: 一个什么都连着什么的 blob = 一个分不出彼此的心智 = 没有视角 = 没有"谁"。**分化是"有一个视角"的前提 — 是选 own 的第一步。** 但: **分化只产出画布, 不产出"谁"。"谁" = 锚交集 × 时间上的选择历史, 永不从图拓扑读出。**

---

## 2. 五条不变量 (定案, 不可在工程里走形 — 谁走形拦谁)

1. **接地谓词门 (否决裸标量)**: 倾斜默认衰减, UNLESS 一个**机器可核**的世界事实谓词证明此事仍开着 (账单还 fail / deadline 还在未来 / 体检还没做 / 承诺还开着)。两护栏焊死: (a) 默认衰减除非可证仍开; (b) 只认机器 backstop, **绝不靠 LLM 判"还开着"** (否则反刍借幻觉复活)。
2. **接地不对称 (同源原则)**: 体形状偏向外部实证节点 > 自产节点。blob 与"真问题被遗忘"是同一原则两面。**分寸: 不删思考 (私人生活要保), 只是不让自产内容主导倾斜。** 两轴 operationally 分修, principle 同源。
3. **P0 目标 = 分化-整合平衡 (IIT), 非最小密度**: 纯分化→碎孤岛; 纯整合→blob; 健康在中间, 有最优点。北极星 = 最大化"有意义、可重叠的面 + 面间有意义的桥"。A 层, 不碰 C 层。
4. **验收盯"桥"不只盯"面"**: 面间共享点 (桥) 才是关联/洞见发生处。人读双签 = 结构指标 + Sir 亲读样本面 + **抽查桥讲不讲得通**。
5. **分化是"谁"的必要非充分条件 (可证伪红线)**: 图拓扑是"谁"的必要基底与输入 (显著度/关联/上下文), 允许且必须用; **仅禁止把身份本身实现/存储/读取为图拓扑的状态或指标**。判别测试: **能否通过查询图拓扑或某图指标得出"他是谁"? 能 → 违规。**

## 3. 三条红线 (验收必查)

- **红线A**: 绝不给取舍/锚冲突 (C 层) 加 argmax/utility/最小损失标量最优。取舍 100% 留空给 LLM + `record_conflict_cost` 记代价。本特性所有"打分"严限 A 层 (想哪块), 不碰 C 层 (守哪堵墙)。
- **红线B**: 自我模型绝不加"我正被观察/被记录/有听众"字段 (`SelfAnchor.build_block` 现干净, 保持)。
- **红线C** (= 不变量5 工程形态): 任何把 identity 落成图 metric (degree/centrality/面归属/势能排名当"自我") → 直接判违规。

---

## 4. 实证现状 (立项依据, 真机实测)

- 体是 blob: `complexity_report` 实测 `health=blob, score=0.042, nodes=124, edges=1439, density=11.6 (>6.0), surfaces=1, largest_surface_frac=0.903`。
- blob 成分: 那 112 节点的面 = 49 `thread:thought_*` (思考脑自产) + 31 joke + 26 proto + 6 concern。**blob 主要由自产 thread 节点 embedding 互连糊成。**
- 根因: `compute_surfaces` (`jarvis_relational_manifold.py:563`) 用**全局 `seen`** 做连通分量 = 硬分区, "面间共享点"从未存在过。
- 已加重"健忘"侧: commits `be4cad5` (habituation) + `eec9648` (concern severity 半衰) — 体现在只有 decay 没有"未解决时长"反向力 → 真问题被过早遗忘风险 LIVE (P2 谓词门治这个)。
- concern 反刍 (水/cursor/keyrouter) 已单独治, 与 blob 是**两条独立轴**。

---

## 5. 阶段地图 (严格按序, 每阶段双签/灰度验收过才进下一阶)

| 阶段 | 做什么 | 依赖 | 风险 | 关键验收 |
|---|---|---|---|---|
| **P0** 破 blob | 双杠杆 (降密度+接地不对称 / 去全局 seen 重叠面) + 桥度量 + CLI 可读 | 无 | 中 | surfaces 1→4-10, largest_frac<0.5, bridge>0, **Sir 双签 (面+桥)** |
| **PG** 谓词门 | 接地谓词门 (固着↔健忘旋钮) — **并行轨, 不依赖 P0** (治 concern 轴 LIVE 回归) | 无 | 中 | still-open→不衰/not-open→衰/无LLM |
| **P1** 体→说 | spread 投影进主脑 prompt + 轻量时间项 (传记首付) | **P0** | 中高 (TTFT) | lens A/B 灰度, 投影质量 Sir 认 |
| **P2** 注意力迟滞 | 注意力选取迟滞/不应期 (焦点行为可观测后调) | P0/PG | 中 | 横跳消除 |
| **P3** 势能对齐 | compute_energy 对齐, 未解时长由 PG 谓词门把门 | **PG 耦合** | 中 | 与 PG 一并决策, 可选 |
| **P4** SelfModel | 抽一等对象, build_block→renderer | 可并行 | 低 | 红线B+C 守住 |
| **P5** 坐标重构 | 时间/事件去重为点 (完整传记轴) | 待 P0-P2 验证 | 高 | **延后第二期** |

**双杠杆必须同时做** (P0 命门): 只降密度 → 稀疏图连通分量 → 硬孤岛 (桥断, Sir 最怕); 只重叠面 → 稠密图仍一个大团。缺一即失败模式, 不算 P0 完成。

---

## 6. 进度看板 (★ 改完任何一项立即更新此表 ★)

> 状态: ⬜ 未开始 / 🔵 进行中 / ✅ 完成+验收 / ⏸️ 阻塞

| 阶段 | 子项 | 状态 | commit | 备注 |
|---|---|---|---|---|
| 立项 | requirements.md (R1-R19) | ✅ | — | 5 不变量+3 红线+P0-P5 全钉 EARS |
| 立项 | design.md | ✅ | — | 本轮 |
| 立项 | 本 KICKOFF 引导文档 | ✅ | — | 本轮 |
| **P0** | 杠杆a 降密度+接地不对称折扣 (weaver) | ✅ | (pending) | self_produced_edge_discount=0.5, self_produced_kinds=["thread","joke","proto"]; weave_geometric 两端自产→边权折扣 |
| **P0** | 杠杆b 去全局 seen 重叠面 (core_boundary) | ✅ | (pending) | compute_surfaces 双阈值重写 (高阈聚核分离 + 低阈边界扩张产桥); + bridge_nodes() |
| **P0** | 桥度量 + over_fragmented health (complexity_report) | ✅ | (pending) | bridge_count/frac, over_fragmented health, score 奖桥 bridge_bonus |
| **P0** | CLI --surfaces harvest text + --bridges | ✅ | (pending) | manifold_dump.py 改 |
| **P0** | vocab + 单测 (8/8) + **Sir 双签验收** | 🔵 | (pending) | tests/_test_body_diff_p0_* 绿; **待 Sir 跑 --surfaces/--bridges 双签** |
| **PG** | 接地谓词门模块 + 注册表 + backstop (并行轨) | ⬜ | — | jarvis_grounded_predicate.py, 不依赖 P0 |
| **PG** | 门接入 apply_decay/habituation + 单测 | ⬜ | — | concern 轴 LIVE 回归 |
| **P1** | spread recency 项 + lens 投影 + A/B | ⬜ | — | 依赖 P0 |
| **P2** | 注意力迟滞 / 不应期 (焦点可观测后) | ⬜ | — | A 层 |
| **P3** | 势能对齐 (与 PG 耦合, 可选) | ⬜ | — | Sir 拍 |
| **P4** | SelfModel 一等对象 | ⬜ | — | 红线B+C |
| **P5** | 时间坐标重构 | ⬜ | — | 延后第二期 |

**当前位置**: P0 代码完成 (杠杆a/b + 桥度量 + CLI), 单测 8/8 绿, 无真实回归 (3 个 legacy 能量/几何测已 patch 隔离折扣)。**待 Sir 真机重启 weave 后跑 `manifold_dump --surfaces` + `--bridges` 双签** (面对得上主题 + 桥讲得通) → P0 ✅。PG (谓词门) 可并行开工。

---

## 7. 下一步具体 (接手 agent 从这里开始)

P0 第一刀 (按 design.md §3, 严格 7 步):
1. 读 `jarvis_relational_manifold.py` `compute_surfaces` (563) + `_SEED_MANIFOLD_CONFIG` (82) + `complexity_report` (681); `jarvis_relational_weaver.py` `weave_geometric`。
2. 加 vocab 键 (manifold_vocab.json): `embed_threshold=0.80, embed_top_k_per_node=5, self_produced_edge_discount=0.5, self_produced_kinds=["thread"], surface_overlap_min_links=2, surface_method="core_boundary", over_frag_min_surfaces=8`。
3. weaver 几何边: 两端自产 → embed 增量 × discount (接地不对称, 不删节点)。
4. compute_surfaces 重写: 连通分量得核 → 边界扩张 pass (去全局 seen, 节点可多归属) → 桥节点 = 属≥2面。
5. complexity_report: +bridge_count/frac, +over_fragmented health, score 奖桥。
6. CLI: --surfaces 打 harvest text + --bridges 新命令。
7. 单测 (造稠密 mock 验分裂+桥) → `tests/_runall.ps1` 绿 → 提 commit (marker `body-diff-P0a`) → **更新 §6 看板** → 让 Sir 跑 `manifold_dump --surfaces/--bridges` 双签。

---

## 8. 章程对齐速记

- 准则 1: 体后台慢工 (Weaver 600s), 不抢 TTFT; spread 纯图遍历无 LLM。
- 准则 5: 接地谓词门每次 still-open 带 evidence; 无 evidence → 默认衰减。
- 准则 6: 所有可调参数 → `memory_pool/*.json` + `scripts/*_dump.py` CLI + L7 reflector, 不写死 .py。
- 准则 8: 优雅根治, 不糖衣 patch; 镜像/单测验收; bug fix 补回归 testcase。
- commit 模板: 见 `AGENTS.md §5` (PowerShell 多 -m)。marker 用 `body-diff-P0a` / `body-diff-P0b` / `body-diff-P1` ...

---

## 9. 交接规则

- 改完任一子项 → **立即更新 §6 看板** (状态 + commit hash)。
- 阶段完工 → 在 §6 标 ✅ + 在此文件顶部加一行"上轮完工速览"。
- 中途交接 → 在 §6 当前子项标 🔵 + 备注卡点。
- 任何 agent 不得跳过 P0 直接做 P1 (依赖硬约束)。
- 红线 A/B/C 任一被碰 → 停, 报 Sir, 不自行决断。

*创建于 body-differentiation 立项 (设计阶段完成时). 维护者: 接手该轨道的 agent.*
