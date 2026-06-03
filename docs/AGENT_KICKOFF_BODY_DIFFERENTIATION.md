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
| **P1** 体→说 | spread 投影进主脑 prompt + 轻量时间项 (传记首付) | **P0 + 杠杆a 减存储密度 (硬前置)** | 中高 (TTFT) | lens A/B 灰度; ⚠️ 杠杆a (embed_threshold↑/top_k↓) 是前置非 follow-up — spread 在 over_dense 存储图扩散会糊投影 (§12.1) |
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
| **P0** | vocab + 单测 (8/8) + **Sir 双签验收** | 🔵 | 261f25f | 杠杆a/b 代码完成; 镜像实测 P0a **不达标** (见下 §10 P0 诊断) |
| **P0b** | route 改判 (Sir ①②③ 签): 两步正解, 非 SLPA / 非降合并阈 | 🔵 | — | 规格 design §3.2; 镜像见 §12 |
| **P0b-③** | alias-fold 接进 compute_surfaces(端点 resolve)/stats(node_count 折叠) | ✅ | (pending) | 真 lever: 27 merges 折叠 → largest_frac 0.299; 单测 5/5; merge_threshold 不动 |
| **P0b-①** | 接地加权成面 surface_self_produced_embed_weight=0.5 (weighted 非 only) | ✅ | (pending) | 单测 5/5 证机制; 但当前真数据 **no-op** (P0a weave 折扣已 subsume, 见 §12); 留作安全网 |
| **P0b-②** | 机器三条验收 (镜像复验) | 🔵 | — | ②.1 largest_frac<0.5 ✅ + ②.3 自产仍在面 ✅; ②.2 bridge>0 需 core_w 0.60→0.80 (2 面 4 桥); 待 Sir 拍调参 + 人读双签 |
| **PG** | 接地谓词门模块 + 注册表 + backstop (并行轨) | ✅ | (pending) | jarvis_grounded_predicate.py, 不依赖 P0, 3 谓词 (deadline/commitment/external) + 4 backstop |
| **PG** | 门接入 apply_decay/habituation + 单测 | ✅ | (pending) | apply_decay still-open→抗衰减 (gate_held), 单测 9/9, 隔离验证 PG 对 18 concern/body 套 0 回归 |
| **P1** | spread recency 项 + lens 投影 + A/B | ⬜ | — | 依赖 P0 |
| **P2** | 注意力迟滞 / 不应期 (焦点可观测后) | ⬜ | — | A 层 |
| **P3** | 势能对齐 (与 PG 耦合, 可选) | ⬜ | — | Sir 拍 |
| **P4** | SelfModel 一等对象 | ⬜ | — | 红线B+C |
| **P5** | 时间坐标重构 | ⬜ | — | 延后第二期 |

**当前位置**: (1) **PG 完成** — 接地谓词门 (固着↔健忘旋钮) 模块 + 注册表 + 4 backstop + 门接入 apply_decay, 单测 9/9 绿, 隔离验证对 18 个 concern/body 套 0 回归 (PG 本身不引入任何新红)。(2) P0a 代码完成但**镜像实测不达标** (largest_frac 0.548 ≥0.5, 见 §10), P0b 改判为合并冗余反刍 thread (非 SLPA), 待镜像复验。**P0 仍待 Sir 真机重启 weave 后跑 `manifold_dump --surfaces` + `--bridges` 双签**。

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

---

## 10. P0 镜像诊断 (2026-06-02, 真数据隔离沙盒, 无 LLM)

P0a (接地不对称折扣 + core_boundary 重叠面 + 桥度量 + CLI) 代码完成 (commit 261f25f), 但**镜像在真实 124 节点 blob 上实测不达标**:
- largest_frac 0.903 → 最好 0.548, **仍 ≥0.5 (blob 未破)**。
- 单调折扣 (discount 0.5→0.15) largest_frac 纹丝不动 (折扣降权但边权仍 > 强边阈)。
- prune-to-top-k 能降 density 但"破团"与"留桥"不可兼得 (top-k=3 → healthy 但 0 桥=孤岛; top-k≥4 → 留桥但仍 blob)。

**诊断 (b) 读那 46 条 thread harvest text → 定案: 冗余反刍, 非多主题。**
那 46 thread = 同 3-4 主题反复嚼一个月 (hydration 反刍 ≥12 / keyrouter ≥8 / "我话太多该收敛"元反刍 ≥10 / interview-pomodoro 若干)。是 concern 反刍在 thread 节点上的镜像。

**P0b 方向改判 (Sir+理论 agent 定案): 不上 SLPA。**
给一团反刍编社区号 = 假分化 (踩不变量③ 过碎 / ⑤ 别把图算法产物当真结构)。**正解 = 巩固/合并近重复反刍 thread** (体里已有 `add_alias` D2 原语 + `auto_merge_dups`, 但阈值 0.93 太高抓不到"同主题不同措辞"的 0.75-0.90 thread)。P0b = 降自产节点间合并阈 + 让巩固在 weave 跑, 把反刍团合并瘦身 (攻因: 减冗余自产节点, 非攻症: 切社区)。
**更深一层 (备选/叠加)**: 让接地边 (cooccur/said/shared = 真实纽带) 成面权重 > 自产 embedding 边 → 面围真实共现长, 非围思考相似长 (不变量② 彻底形态)。
SLPA 仅在"确认是多主题且团稠密破不开"时才上 — 当前诊断**否决**该前提。

**P0a 代码保留** (折扣 + 重叠面框架 + 桥度量 + CLI 是 P0b 地基, 复用)。

---

## 11. P0b route 终判 (Sir 签字 2026-06-03, ①②③ 写进规格)

镜像沙盒推翻"降合并阈"与"SLPA"。Sir 签两步正解, 写进 `design.md §3.2`:

- **③ alias-fold 独立 commit 先做 (修真 bug)**: `compute_surfaces`/`stats`/`complexity_report` 边遍历时 `resolve(a)/resolve(b)` 折叠 dup→rep + 丢自环, 让既有合并 (merge_threshold=0.93) 真生效。**merge_threshold 不动, 不复活"降自产合并阈"** (alias-fold ≠ 降阈合并, 两件事别粘一起)。
- **① 接地加权成面 (weighted 非 only)**: 新 vocab `surface_self_produced_embed_weight` (默 0.5)。成面阶段接地边 (cooccur/said/shared) 全权; 两端自产的 embed-only 边 ×乘子。**绝不"只认 grounded"** — 那会把 49 thread 抹成孤儿 (违 R2.2 删思考)。理想: 自产节点自聚成"内心/私人生活"面, 与外部面并存 + 有桥。
- **② 三条验收缺一不可**: largest_frac<0.5 + bridge_count>0 + 自产节点仍有面归属 + Sir 人读双签 (面+桥)。0.355 那数来自"只认 grounded", 不可 ship; 要 ship 的是 weighted 且确认 weighted 仍能压 largest_frac<0.5。

**清醒项 (不阻塞)**:
- ④ grounded 底盘薄 (300 cooccur / 0 said / 0 shared)。轻调留余量, 别对 300 条调死, 等 said/shared 填上来会变。
- ⑤ thread 被"看 Sir 写代码" + "我话太多"元反刍主导 = 漂移信号, 离红线B 一步。P0b 不处理, 往后盯 SelfModel (P4) 别长观众字段。

**实现顺序**: 先 ③ (alias-fold + 回归单测, 独立 commit) → 再 ① (接地加权 + 单测) → ② 三条验收 + 镜像复验 + runall 绿 → 报 Sir 双签。

---

## 12. P0b 镜像复验结果 (2026-06-03, 只读真数据 1701 边, `scripts/manifold_p0b_mirror.py`)

镜像在**当前真实体** (1701 边, 27 个已存 merges) 上复验, 结论修正了诊断时的预期 (诚实, 准则5):

| 配置 | surfaces | largest_frac | bridges | health | 自产在面 |
|---|---|---|---|---|---|
| ① OFF (sp_w=1.0, core 0.60) | 1 | **0.299** | 0 | over_dense | 29/100 |
| ① ON (sp_w=0.5, core 0.60) | 1 | **0.299** | 0 | over_dense | 29/100 |
| ① ON + **core 0.80** | **2** | **0.224** | **4** | over_dense | 21/100 |

**三个关键发现 (改判 + 诚实)**:
1. **③ alias-fold 是真 lever**: 27 个已存 merges 一旦折叠 → largest_frac 0.299 (已脱 blob)。验证发现 A 是真根因。
2. **① 在当前真数据上是 no-op** (① ON == ① OFF, 都 0.299): **P0a weave 时折扣** (`self_produced_edge_discount=0.5`) 已把自产↔自产 embed 边的**存储权**压到 ~0.30, 低于成面阈 (0.45/0.60), 成面阶段 ① 再打折"无折可打"。诊断的 0.702→0.355 是在**未应用 weave 折扣/未 fold alias** 的沙盒里测的。① 仍是正确的**防御安全网** (若日后放松 weave 折扣), 但**当前不是活 lever**。
3. **②.2 桥的真 lever = `surface_core_min_weight` 轻调**: 默认 0.60 = 1 面 0 桥 (②.2 不达标); 调 **0.80 = 2 面 4 桥 + largest_frac 0.224** (②.1+②.2+②.3 机器侧全达标)。桥语义连贯 (`sir_hydration_habit` + 2 条 hydration proto 桥接"补水"面 ↔ "工作/手痛/面试"面, 讲得通)。≥1.0 反而塌回 1 面 (强 grounded 核独大)。

**残留**: `health=over_dense` (density 15.9) 跨所有配置 — 这是 embed 边密度过高的**独立轴** (非 blob 轴), 可 embed_threshold↑/embed_top_k↓ 轻调, 但 Sir ④ "留余量", 列 follow-up 不阻塞。

**待 Sir 决策**: (a) 是否把 `surface_core_min_weight` 0.60→0.80 落 vocab (轻调, 可逆) → ② 机器达标; (b) Sir 人读 0.80 的 2 面 + 4 桥双签; (c) ① 保留为安全网 (默认 0.5) 还是记为 subsumed。复跑: `python scripts/manifold_p0b_mirror.py`。

## 12.1 Sir 双签 + 终判 (2026-06-03) — P0 是"部分达成", 不是"完成"

**Sir Q1=B (双签在前, 不动 vocab), Q2=C (现在不 commit)。硬话: core_w=0.80 的 2 面 4 桥 ≠ "blob 破了可进 P1"。**

人读双签材料 (`signoff(core_w=0.80)`) 两查结论:
- **查i 内心去向 (私人生活还在结构里吗?)**: core_w 0.80 时**仅 24 节点在面, 83 节点没进任何面** (仍在图有边, 未成面), 其中**自产孤儿 79/100** (joke 24 + proto 34 + thread 21, 全 inner_thought [E] 自语)。Sir ① 设想的"自产自聚成内心面" **未发生** — 内心既没 blob 也没聚面, 散成孤儿。根因 = grounded 底盘薄 (300 cooccur, 自产间共现不足成 min_size-3 面) + embed 被 P0a/① 压制。**非 P0b bug, 是 Sir ④ 薄底盘**; "内心面"要等 said/shared/cooccur 填上来才长得出。
- **查ii 桥单一性**: 第 2 面 size=4, **它 4 成员就是那 4 座桥本身** (hydration_habit + 2 hydration/reminder proto + 1 curate-repo thread), 3/4 偏补水。= "1 大面(24) + 1 个全是桥的小附属(4)", 分化薄、桥种类窄。Sir 判断对。

**P0 状态钉死 = 部分达成**: 只 2 面 (原目标 4-10) + largest_frac 0.224 但大半节点 orphaned → "不再是 blob" 远没到"有区分度的体"。**不得据此进 P1。**

**根因 + 杠杆a P1 前置 (Sir 改判)**: `health=over_dense` (density 15.9) 跨所有 core_w — core_w 只改成面视图, **存储图仍过密**。**杠杆a 真减存储边 (embed_threshold↑/top_k↓) = P1 硬前置** (spread 在过密存储图扩散会糊投影), 已记 design.md P1 + §5 阶段地图。R9 双杠杆: 杠杆b 成, 杠杆a 欠。

**① 处置**: 当前真数据 no-op (P0a weave 折扣已 subsume), **保留为防御冗余** (manifold.py seed 注释 + 本看板已写明, 5 单测守), 不删。

**commit 次序 (Sir Q2=C, 现在不提交)**: 先定 P0a 去留 (它是 P0b 地基; 没 P0a 折扣 ① 反而变活 lever, 提交态行为会和测的不同) → 确定基线上重确认数字 → runall 全绿 (现 T7 红) → 再把 P0b 作两独立 commit (③ 一个 / ①+core_w 一个)。**P0a/T7 走 P0 轨自己 -hotfix** (改过期 beta540 测试对齐 fa9b365 真修复, 非回退), 不替它扛、不捆进 P0b。

**下一步候选**: (1) Sir 定 P0a 去留以锚基线; (2) 杠杆a 减存储密度 (P1 前置, 也可能让内心借更稀疏图重聚面); (3) -hotfix 收 T7 + 3 beta540 旧红。
